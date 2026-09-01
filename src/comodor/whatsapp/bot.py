"""The WhatsApp bot: the same agent, reached from a phone number.

It runs the same `web.session.Session` the browser interface and the Telegram
bot run, so a task started here learns the same lessons and appears in the same
history. What differs is everything about the medium, and the differences are
not cosmetic:

**No editing.** Telegram streams a reply by rewriting one message as tokens
arrive. WhatsApp has no edit, so a turn cannot be watched growing. Instead it
sends one line when it starts, a line when it takes an unusually long time, and
the answer when there is one. Sending a message per token would be a hundred
notifications for one question.

**Three buttons.** Menus that Telegram draws as a grid are a list here — one
tap to open, ten rows inside. `menu.py` holds that arithmetic.

**A phone number, not a username.** Anybody with the number can message it, so
the allow-list is the whole of the security and strangers get silence rather
than a refusal — a refusal tells somebody they found something worth finding.

**A day-long window.** Meta only permits free-form messages within twenty-four
hours of the person's last one. A task that finishes after that cannot be
reported, so the bot says so rather than failing silently, and the fix is for
the person to write again.
"""

from __future__ import annotations

import queue
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..channels.breaker import CircuitBreaker
from ..channels.busy import interrupt_note, start_or_steer
from ..channels.markdown import to_whatsapp
from ..channels.settings import Settings, keep_current
from ..config import Config
from ..media.ingest import MediaError, ingest
from . import menu as ui
from .api import Cloud, OutsideWindow, WhatsAppError, split
from .webhook import Endpoint, Inbound

#: How long one turn may hold a worker before it is abandoned.
TURN_PATIENCE = 3600.0

#: How often a running turn says it is still going. WhatsApp cannot edit, so
#: each of these is a new notification on somebody's phone — rare on purpose.
STILL_WORKING_EVERY = 45.0


@dataclass
class Pairing:
    """A one-time code that adds one account to the allow-list."""

    code: str
    until: float

    @property
    def live(self) -> bool:
        return time.time() < self.until


@dataclass
class Waiting:
    """A question the agent asked, and what has been chosen so far."""

    request_id: str
    questions: list[dict[str, Any]] = field(default_factory=list)
    index: int = 0
    picked: dict[int, set[int]] = field(default_factory=dict)
    writing: bool = False


@dataclass
class Turn:
    """One running task, and when it last said anything."""

    started: float = field(default_factory=time.monotonic)
    last_spoke: float = field(default_factory=time.monotonic)
    finished: bool = False


class Conversation:
    """One WhatsApp number and the agent session behind it."""

    def __init__(self, config: Config, wa_id: str) -> None:
        from ..web.session import Session

        self.wa_id = wa_id
        self.session = Session(config)
        self.cursor = self.session.cursor
        self.turn: Turn | None = None
        self.waiting: Waiting | None = None
        #: Paged lists, so a tapped row can name its item by number: a model id
        #: is longer than a row id has room for once a verb is prefixed.
        self.shelf: dict[str, list[tuple[str, str]]] = {}
        self.lock = threading.Lock()

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass


class Service:
    """The webhook, the queue it fills, and everything that reads from it."""

    def __init__(self, config: Config, cloud: Cloud | None = None,
                 endpoint: Endpoint | None = None,
                 announce: Callable[[str], None] | None = None) -> None:
        self.config = config
        #: The configuration file, watched. A bot is a detached process: every
        #: setting changed from the terminal or the web panel while it runs was
        #: invisible to it, and the command that changed the setting said it
        #: had worked.
        self.settings = Settings(config)
        settings = config.whatsapp
        self.cloud = cloud or Cloud(settings.token, settings.phone_number_id,
                                    version=settings.api_version)
        self.endpoint = endpoint or Endpoint(
            verify_token=settings.verify_token,
            app_secret=settings.app_secret,
            path=settings.path, host=settings.host, port=settings.port,
            announce=announce)
        self.chats: dict[str, Conversation] = {}
        self.pairing: Pairing | None = None
        self.stopping = threading.Event()
        self.announce = announce or (lambda line: None)
        #: The outbound-delivery ledger: every reply is noted before it is
        #: sent, so a crash between producing an answer and delivering it
        #: leaves a record the next start can recover. Created lazily where
        #: tests inject a cloud, since it touches the user directory.
        from ..channels.ledger import DeliveryLedger

        self._ledger = DeliveryLedger(
            config.paths.delivery_ledger("whatsapp"), "whatsapp")
        self._breaker = CircuitBreaker("whatsapp")

    def say(self, line: str) -> None:
        try:
            self.announce(line)
        except Exception:
            pass

    # -- pairing ----------------------------------------------------------- #

    def offer_pairing(self) -> str:
        """A code somebody sends the number to add themselves to the list."""
        code = f"{secrets.randbelow(900000) + 100000}"
        self.pairing = Pairing(
            code=code, until=time.time() + self.config.whatsapp.pair_window)
        return code

    def _maybe_pair(self, item: Inbound) -> bool:
        offer = self.pairing
        if offer is None or not offer.live:
            return False
        if item.text.strip() != offer.code:
            return False

        self.config.whatsapp.allowed.append(item.wa_id)
        self.pairing = None
        try:
            from .. import config as config_mod

            config_mod.save_user_config(self.config)
        except Exception:
            pass
        self.say(f"paired {item.wa_id}")
        self._send(item.wa_id,
                   "*Paired.* This number can now reach Comodor.\n\n"
                   "Send a task, or open the menu below.")
        self._menu(self._conversation(item.wa_id))
        return True

    # -- the loop ---------------------------------------------------------- #

    def run(self) -> None:
        """Serve the webhook and turn what arrives into work."""
        self.endpoint.start()
        self._resume_ledger()
        settings = self.config.whatsapp
        self.say(f"{len(settings.allowed)} paired number(s) · "
                 + ("may edit files" if settings.allow_writes
                    else "read-only"))
        if settings.public_url:
            self.say(f"Meta should be posting to {settings.public_url}")

        while not self.stopping.is_set():
            try:
                item = self.endpoint.inbox.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._handle(item)
            except Exception as problem:          # never let one message stop it
                self.say(f"failed on a message: {problem}")

    def _resume_ledger(self) -> None:
        """Redeliver replies a crash left pending, then sweep old records.

        Runs once at start, before any new traffic: recovery is about the
        previous life of this process, and interleaving it with fresh turns
        would answer the older question second.
        """
        from ..channels.ledger import DeliveryLedger, resume

        ledger = DeliveryLedger(
            self.config.paths.delivery_ledger("whatsapp"), "whatsapp")
        try:
            recovered = resume(ledger, self._send)
        except Exception:
            recovered = 0
        if recovered:
            self.say(f"redelivered {recovered} reply/replies that a restart "
                     "had interrupted")
        ledger.sweep()

    def stop(self) -> None:
        self.stopping.set()
        self.endpoint.stop()
        for talk in list(self.chats.values()):
            talk.close()
        self.chats.clear()

    def _handle(self, item: Inbound) -> None:
        keep_current(self)

        if not item.wa_id:
            return
        if not self.config.whatsapp.may(item.wa_id):
            # Not a refusal. A stranger who gets an answer of any kind has
            # learned that this number is a Comodor and that there is a list
            # worth getting onto.
            self._maybe_pair(item)
            return

        self.cloud.mark_read(item.message_id)
        talk = self._conversation(item.wa_id)

        if item.is_media:
            self._on_media(talk, item)
            return
        if item.action.startswith("unsupported:"):
            kind = item.action.split(":", 1)[1]
            self._send(item.wa_id,
                       f"I can only read text here — that was a {kind}.")
            return
        if item.tapped:
            self._on_tap(talk, item.action)
            return
        text = item.text.strip()
        if not text:
            return
        if talk.waiting is not None and talk.waiting.writing:
            self._write_answer(talk, text)
            return
        if text.startswith("/"):
            self._on_command(talk, text)
            return
        self._start_turn(talk, text)

    def _conversation(self, wa_id: str) -> Conversation:
        talk = self.chats.get(wa_id)
        if talk is None:
            talk = Conversation(self.config, wa_id)
            if not self.config.whatsapp.allow_writes:
                # Held in plan whatever the terminal is set to, for the same
                # reason as Telegram: a thumb approves with less attention than
                # a keyboard, and the consequences are identical.
                talk.session.set_mode("plan")
            self.chats[wa_id] = talk
        return talk

    # -- sending ----------------------------------------------------------- #

    def _send(self, wa_id: str, text: str) -> None:
        """One answer, split if it is long, and never a crash on a closed window."""
        for piece in split(text):
            if not piece.strip():
                continue
            try:
                self._ledger.send(wa_id, piece, self.cloud.send)
            except OutsideWindow:
                self.say(f"{wa_id} has not written for a day; WhatsApp will "
                         f"not take a message until they do")
                return
            except WhatsAppError as problem:
                self._send_failed(problem)
                return

    def _send_failed(self, problem: Exception) -> None:
        """A send error: count it, and pause the adapter at the cap.

        WhatsApp sends fail for reasons the retry loop cannot fix — an
        expired token, an account under review. Counting them here means a
        string of them trips the breaker and the human is told once, in the
        channel, instead of the daemon muttering to its log forever.
        """
        if self._breaker.fail(str(problem)):
            self.say(f"{problem} — WhatsApp sends are paused; send /platform "
                     "here to resume them")
            return
        self.say(f"could not send: {problem}")

    def _menu(self, talk: Conversation, note: str = "") -> None:
        """The main screen, as a list."""
        state = self._state(talk)
        rows = ui.main_menu(
            busy=bool(state.get("busy")),
            mode=str(state.get("mode") or self.config.agent.mode),
            rules=self._rule_count(talk),
            model=str(state.get("model") or ""),
            writes=self.config.whatsapp.allow_writes)

        body = note or self._welcome(talk)
        if len(rows) == 1:
            self._buttons(talk.wa_id, body, [(rows[0].key, rows[0].title)])
            return
        self._list(talk.wa_id, body, "Menu", rows)

    def _list(self, wa_id: str, body: str, open_label: str,
              rows: list[ui.Row], header: str = "") -> None:
        try:
            self.cloud.send_list(wa_id, body, open_label,
                                 [row.as_tuple() for row in rows],
                                 header=header)
        except OutsideWindow:
            self.say(f"{wa_id} is outside the 24-hour window")
        except WhatsAppError as problem:
            self.say(f"could not send the menu: {problem}")
            self._send(wa_id, body)

    def _buttons(self, wa_id: str, body: str,
                 choices: list[tuple[str, str]]) -> None:
        try:
            self.cloud.send_buttons(wa_id, body, choices)
        except OutsideWindow:
            self.say(f"{wa_id} is outside the 24-hour window")
        except WhatsAppError as problem:
            self.say(f"could not send buttons: {problem}")
            self._send(wa_id, body)

    # -- commands and taps -------------------------------------------------- #

    def _on_command(self, talk: Conversation, text: str) -> None:
        name = text[1:].split()[0].split("@")[0].lower()
        rest = text[len(name) + 1:].strip()

        if name in ("start", "menu"):
            self._menu(talk)
        elif name == "help":
            self._send(talk.wa_id, self._help())
            self._menu(talk, note="Anything else?")
        elif name == "new":
            self._new_chat(talk)
        elif name == "stop":
            self._stop_turn(talk)
        elif name == "mode":
            if rest.lower() in ui.MODES:
                self._set_mode(talk, rest.lower())
            else:
                self._show_modes(talk)
        elif name == "status":
            self._send(talk.wa_id, self._status(talk))
        elif name == "platform":
            self._platform_command(talk)
        else:
            self._menu(talk, note=f"No command called /{name}.")

    def _on_tap(self, talk: Conversation, action: str) -> None:
        verb, _, argument = action.partition(":")

        if verb == "menu":
            self._menu(talk)
        elif verb == "stop":
            self._stop_turn(talk)
        elif verb == "new":
            self._new_chat(talk)
        elif verb == "mode" and not argument:
            self._show_modes(talk)
        elif verb == "mode":
            self._set_mode(talk, argument)
        elif verb == "status":
            self._send(talk.wa_id, self._status(talk))
            self._menu(talk, note="Anything else?")
        elif verb == "help":
            self._send(talk.wa_id, self._help())
            self._menu(talk, note="Anything else?")
        elif verb == "writes":
            self._send(talk.wa_id, self._writes())
            self._menu(talk, note="Anything else?")
        elif verb == "rules":
            self._send(talk.wa_id, self._rules(talk))
            self._menu(talk, note="Anything else?")
        elif verb == "folder":
            self._send(talk.wa_id, self._folder(talk))
            self._menu(talk, note="Anything else?")
        elif verb == "chats":
            self._show(talk, "chat", int(argument or 0))
        elif verb == "models":
            self._show(talk, "model", int(argument or 0))
        elif verb == "skills":
            self._show(talk, "skill", int(argument or 0))
        elif verb == "page":
            where, _, number = argument.partition(":")
            self._show(talk, where, int(number or 0))
        elif verb in ("chat", "model", "skill"):
            self._chose(talk, verb, argument)
        elif verb in ("ok", "okall", "no"):
            self._answer_permission(talk, argument, verb)
        elif verb == "mm":
            # A mode-change suggestion: `mm:<request>:<mode>`.
            request_id, _, mode = argument.partition(":")
            self._answer_mode(talk, request_id, mode)
        elif verb == "q":
            self._pick_option(talk, argument)
        elif verb == "qw":
            self._await_written(talk, argument)
        elif verb == "qs":
            self._send_answers(talk)
        else:
            self._menu(talk)

    # -- turns -------------------------------------------------------------- #

    def _start_turn(self, talk: Conversation, text: str,
                    images: list[str] | None = None) -> None:
        def refuse(note: str) -> None:
            self._menu(talk, note=note)

        if not start_or_steer(talk.session, text, images,
                              self.config.whatsapp.busy_mode, refuse):
            return
        talk.turn = Turn()
        self._send(talk.wa_id, "_Working on it…_")
        threading.Thread(target=self._follow, args=(talk,),
                         name=f"comodor-wa-{talk.wa_id}", daemon=True).start()

    # -- media --------------------------------------------------------------- #

    def _on_media(self, talk: Conversation, item: Inbound) -> None:
        """Download, type, and route one media message."""
        if not self.config.media.enabled:
            self._send(item.wa_id,
                       f"I can only read text here — that was a "
                       f"{item.media_kind}.")
            return
        self.cloud.max_download_bytes = int(
            self.config.media.max_download_mb * 1_000_000)
        try:
            data = self.cloud.download(item.media_id)
            downloaded = ingest(data, name=item.media_name,
                                directory=self._media_dir(),
                                max_mb=self.config.media.max_download_mb)
        except MediaError as problem:
            self._send(item.wa_id, str(problem))
            return
        except WhatsAppError as problem:
            self._send(item.wa_id, f"I could not fetch that file: {problem}")
            return
        try:
            self._start_turn_with_media(talk, downloaded)
        except Exception as problem:
            # A transcription gate refusing (no key, unknown provider); the
            # file is on disk either way, and the reason is said.
            self._send(item.wa_id, f"{problem} The file is kept at "
                                   f"{downloaded.path}, so nothing is lost.")

    def _media_dir(self):
        from pathlib import Path

        configured = self.config.media.save_dir
        root = Path(configured) if configured else \
            Path(self.config.paths.user) / "media"
        return root / "whatsapp"

    def _start_turn_with_media(self, talk: Conversation, item) -> None:
        from ..media.route import route
        from ..providers.profile import of as profile_of

        profile = profile_of(self.config)
        routed = route(item, profile, voice_to_text=self._transcriber())
        self._start_turn(talk, routed.text, images=routed.images)

    def _transcriber(self):
        """The voice-note transcriber, or None where there is none.

        A configured provider whose gate is closed (no key in the
        environment, an unknown provider name) raises here on purpose: the
        media handler turns that into a note the user can act on.
        """
        if not self.config.media.voice_to_text:
            return None
        from ..voice.stt import transcriber
        return transcriber(self.config)

    def _follow(self, talk: Conversation) -> None:
        """Drain the event stream, and speak rarely.

        Telegram edits one message as often as it likes. Every message here is
        a notification on a phone, so a running turn says something at the
        start, occasionally while it works, and once at the end.
        """
        deadline = time.time() + TURN_PATIENCE
        answer = ""
        tools: list[str] = []

        while time.time() < deadline and not self.stopping.is_set():
            events = talk.session.wait_for(talk.cursor, timeout=8.0)
            if events:
                talk.cursor = talk.session.cursor

            for event in events:
                kind = event.get("kind")
                if kind == "assistant_delta":
                    answer += event.get("text", "")
                elif kind == "assistant_end" and event.get("text"):
                    answer = event["text"]
                elif kind == "tool_start":
                    tools.append(event.get("summary") or event.get("name", ""))
                elif kind == "request":
                    self._ask(talk, event)
                elif kind == "error":
                    answer += f"\n\n⚠ {event.get('text', '')}"
                elif kind == "turn_end":
                    self._finish(talk, answer, tools)
                    return
                elif kind == "cancelled":
                    self._finish(talk, answer + "\n\n_stopped_"
                                 + interrupt_note(event), tools)
                    return

            self._still_working(talk, tools)

        self._finish(talk, answer, tools)

    def _still_working(self, talk: Conversation, tools: list[str]) -> None:
        turn = talk.turn
        if turn is None or turn.finished:
            return
        now = time.monotonic()
        if now - turn.last_spoke < STILL_WORKING_EVERY:
            return
        turn.last_spoke = now
        recent = " · ".join(tools[-2:]) if tools else "thinking"
        self._send(talk.wa_id, f"_{recent}…_")

    def _finish(self, talk: Conversation, answer: str,
                tools: list[str]) -> None:
        turn = talk.turn
        if turn is not None:
            if turn.finished:
                return
            turn.finished = True
        talk.turn = None

        # WhatsApp has its own markup and no link syntax at all, so the
        # model's Markdown arrived as punctuation.
        body = to_whatsapp((answer or "").strip()) or "Done."
        if tools:
            body += "\n\n_" + " · ".join(tools[-3:]) + "_"
        self._send(talk.wa_id, body)
        self._menu(talk, note="Anything else?")

    def _stop_turn(self, talk: Conversation) -> None:
        talk.session.interrupt()
        if talk.turn is not None:
            talk.turn.finished = True
        talk.turn = None
        self._menu(talk, note="Stopped.")

    def _new_chat(self, talk: Conversation) -> None:
        talk.session.new_chat()
        talk.cursor = talk.session.cursor
        talk.turn = None
        talk.waiting = None
        self._menu(talk, note="New chat. What would you like done?")

    def _set_mode(self, talk: Conversation, mode: str) -> None:
        if mode not in ui.MODES:
            self._menu(talk)
            return
        if mode == "act" and not self.config.whatsapp.allow_writes:
            self._send(talk.wa_id,
                       "*Not from here.*\n\nThis number reads and plans only. "
                       "At the terminal on the machine it runs on:\n\n"
                       "```comodor whatsapp writes on```")
            self._menu(talk, note="Anything else?")
            return
        talk.session.set_mode(mode)
        self._menu(talk, note=f"Mode is now *{ui.MODE_WORDS[mode]}*.")

    # -- questions and permissions ------------------------------------------ #

    def _ask(self, talk: Conversation, event: dict[str, Any]) -> None:
        what = event.get("what") or event.get("request") or {}
        request_id = str(event.get("id") or event.get("request_id") or "")

        if event.get("about") == "mode" or what.get("kind") == "mode":
            options = [option for option in event.get("options", []) if option]
            body = what.get("prompt") or event.get("prompt") or "Change mode?"
            self._buttons(talk.wa_id, f"*Comodor suggests a mode change*\n\n{body}",
                          ui.mode_choices(request_id, options))
            return

        if what.get("kind") == "permission" or event.get("permission"):
            body = what.get("text") or event.get("text") or "May I?"
            self._buttons(talk.wa_id, f"*Comodor wants to*\n\n{body}",
                          ui.permission(request_id))
            return

        questions = what.get("questions") or event.get("questions") or []
        if not questions:
            return
        talk.waiting = Waiting(request_id=request_id, questions=questions)
        self._show_question(talk)

    def _show_question(self, talk: Conversation) -> None:
        waiting = talk.waiting
        if waiting is None or waiting.index >= len(waiting.questions):
            return
        question = waiting.questions[waiting.index]
        options = [str(o.get("label") or o) for o in question.get("options", [])]
        multi = bool(question.get("multi"))
        label, rows = ui.question(waiting.request_id, waiting.index, options,
                                  waiting.picked.get(waiting.index), multi)
        body = str(question.get("question") or "Which one?")
        if len(waiting.questions) > 1:
            body += f"\n\n_{waiting.index + 1} of {len(waiting.questions)}_"
        self._list(talk.wa_id, body, label, rows)

    def _pick_option(self, talk: Conversation, argument: str) -> None:
        waiting = talk.waiting
        if waiting is None:
            return
        parts = argument.split(":")
        if len(parts) < 2:
            return
        index, slot = int(parts[-2]), int(parts[-1])
        question = waiting.questions[index] if index < len(waiting.questions) else {}
        chosen = waiting.picked.setdefault(index, set())
        if question.get("multi"):
            chosen.symmetric_difference_update({slot})
            self._show_question(talk)
            return
        chosen.clear()
        chosen.add(slot)
        waiting.index = index + 1
        if waiting.index < len(waiting.questions):
            self._show_question(talk)
        else:
            self._send_answers(talk)

    def _await_written(self, talk: Conversation, argument: str) -> None:
        waiting = talk.waiting
        if waiting is None:
            return
        waiting.writing = True
        self._send(talk.wa_id, "Type your answer and send it.")

    def _write_answer(self, talk: Conversation, text: str) -> None:
        waiting = talk.waiting
        if waiting is None:
            return
        waiting.writing = False
        try:
            talk.session.answer(waiting.request_id, text)
        except Exception as problem:
            self.say(f"could not deliver the answer: {problem}")
        talk.waiting = None

    def _send_answers(self, talk: Conversation) -> None:
        waiting = talk.waiting
        if waiting is None:
            return
        picked: list[str] = []
        for index, slots in sorted(waiting.picked.items()):
            question = waiting.questions[index] if index < len(waiting.questions) else {}
            options = [str(o.get("label") or o)
                       for o in question.get("options", [])]
            picked.extend(options[slot] for slot in sorted(slots)
                          if slot < len(options))
        try:
            talk.session.answer(waiting.request_id, ", ".join(picked))
        except Exception as problem:
            self.say(f"could not deliver the answer: {problem}")
        talk.waiting = None

    def _answer_permission(self, talk: Conversation, request_id: str,
                           verb: str) -> None:
        try:
            talk.session.answer(request_id,
                                {"ok": "once", "okall": "always",
                                 "no": "no"}[verb])
        except Exception as problem:
            self.say(f"could not deliver the approval: {problem}")

    def _answer_mode(self, talk: Conversation, request_id: str,
                     mode: str) -> None:
        if not mode:
            return
        try:
            talk.session.answer(request_id, mode)
        except Exception as problem:
            self.say(f"could not deliver the answer: {problem}")

    # -- paged lists --------------------------------------------------------- #

    def _show(self, talk: Conversation, kind: str, page: int = 0) -> None:
        items, body = self._shelf_for(talk, kind)
        if not items:
            self._menu(talk, note=body)
            return
        talk.shelf[kind] = items
        rows = [ui.Row(f"{kind}:{slot}", title[:24], note[:72])
                for slot, (_, title, note) in enumerate(items)]
        self._list(talk.wa_id, body, "Choose",
                   ui.page(kind, rows, page_number=page))

    def _shelf_for(self, talk: Conversation,
                   kind: str) -> tuple[list[tuple[str, str, str]], str]:
        if kind == "chat":
            found = talk.session.chats(limit=60)
            if not found:
                return [], "Nothing saved yet."
            return ([(str(c["id"]),
                      ("● " if c.get("current") else "")
                      + str(c.get("title") or "Untitled"),
                      f"{c.get('messages', 0)} messages") for c in found],
                    f"*History* — {len(found)} saved.")
        if kind == "model":
            state = self._state(talk)
            provider = str(state.get("provider") or self.config.provider)
            current = str(state.get("model") or "")
            found = talk.session.models_for(provider)
            names = [str(e.get("id") or e.get("name") or "")
                     for e in found.get("models") or []]
            names = [n for n in names if n]
            if not names:
                return [], f"Could not list what {provider} offers."
            return ([(n, ("● " if n == current else "") + n, provider)
                     for n in names],
                    f"*Model* — using {current or '—'} on {provider}.")
        if kind == "skill":
            shelf = talk.session.skill_shelf()
            cards = shelf.get("skills") or []
            if not cards:
                return [], "Nothing to show."
            installed = sum(1 for c in cards if c.get("installed"))
            return ([(str(c["id"]),
                      ("● " if c.get("installed") else "") + str(c["id"]),
                      str(c.get("description") or "")) for c in cards],
                    f"*Skills* — {installed} installed of {len(cards)}. "
                    f"Tap one to add or remove it.")
        return [], "Nothing here."

    def _chose(self, talk: Conversation, kind: str, slot: str) -> None:
        items = talk.shelf.get(kind) or []
        if not (slot.isdigit() and int(slot) < len(items)):
            self._menu(talk, note="That list has moved on — open it again.")
            return
        key = items[int(slot)][0]

        if kind == "chat":
            ok, note, _ = talk.session.open_chat(key)
            talk.cursor = talk.session.cursor
            self._menu(talk, note=note or ("Opened." if ok else "Could not."))
        elif kind == "model":
            ok, note = talk.session.setting("model", key)
            self._menu(talk, note=note or (f"Now using *{key}*." if ok
                                           else "That did not take."))
        elif kind == "skill":
            shelf = talk.session.skill_shelf()
            here = next((c for c in shelf.get("skills") or []
                         if c.get("id") == key), None)
            action = "remove" if here and here.get("installed") else "install"
            ok, note = talk.session.skill(action, key)
            self._menu(talk, note=note or f"*{key}* {action}ed.")

    # -- what it says --------------------------------------------------------- #

    def _state(self, talk: Conversation) -> dict[str, Any]:
        try:
            return talk.session.state() or {}
        except Exception:
            return {}

    def _mode(self, talk: Conversation) -> str:
        return str(self._state(talk).get("mode") or self.config.agent.mode)

    def _show_modes(self, talk: Conversation) -> None:
        """The mode screen, as a list — four modes will not fit as buttons."""
        current = self._mode(talk)
        self._list(talk.wa_id, ui.mode_body(current), "Mode",
                   ui.mode_rows(current))

    def _rule_count(self, talk: Conversation) -> int:
        try:
            return int((talk.session.rules() or {}).get("active") or 0)
        except Exception:
            return 0

    def _welcome(self, talk: Conversation) -> str:
        state = self._state(talk)
        model = str(state.get("model") or self.config.model or "—")
        folder = str(state.get("project") or self.config.paths.project or "")
        folder = folder.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "—"
        return (
            "*Comodor*\n\n"
            "Send a task and it gets on with it.\n\n"
            f"*Model* {model}\n"
            f"*Folder* {folder}\n"
            + ("*May* edit files and run commands, asking first\n"
               if self.config.whatsapp.allow_writes
               else "*May* read and plan only\n")
            + "\nOr open the menu below."
        )

    def _help(self) -> str:
        return (
            "*What this can do*\n\n"
            "Type a task — _why is the build failing?_, _add a health "
            "endpoint_ — and it works on it.\n\n"
            "*The menu*\n"
            "• *New chat* — forget the conversation so far\n"
            "• *History* — re-open an earlier one\n"
            "• *Mode* — what it may do\n"
            "• *Status* — model, folder, context, spend\n"
            "• *Model* — switch to another\n"
            "• *Folder* — which project it works in\n"
            "• *Skills* — procedures it follows\n"
            "• *Rules* — what it learned from your corrections\n\n"
            "When it needs a decision it asks with buttons. When it needs to "
            "run something, you approve it here first.\n\n"
            "_WhatsApp only lets me message you within a day of your last "
            "message. If a long task finishes after that, write again and "
            "ask._"
        )

    def _platform_command(self, talk: Conversation) -> None:
        """The WhatsApp adapter's breaker: state, and the resume.

        Sends are what can be paused here — inbound traffic arrives by
        webhook regardless — so resuming clears the send breaker and says
        so, and an unpaused adapter just reports health.
        """
        breaker = self._breaker
        if breaker.paused:
            breaker.resume()
            self._send(talk.wa_id, "WhatsApp sends are on again.")
            return
        self._send(talk.wa_id, breaker.describe())

    def _status(self, talk: Conversation) -> str:
        state = self._state(talk)
        context = state.get("context") or {}
        usage = state.get("usage") or {}
        used = int(context.get("used") or 0)
        limit = int(context.get("limit") or 0)
        share = f"{used / limit:.0%}" if limit else "—"
        cost = usage.get("cost")
        spend = f"${cost:.4f}" if isinstance(cost, (int, float)) else "—"
        return (
            "*Status*\n\n"
            f"Model   {state.get('provider', '—')} / {state.get('model', '—')}\n"
            f"Mode    {state.get('mode', '—')}\n"
            f"Folder  {state.get('project', '—')}\n"
            f"Context {share} of {limit:,}\n"
            f"Spend   {spend}"
        )

    def _rules(self, talk: Conversation) -> str:
        try:
            entries = (talk.session.rules() or {}).get("rules") or []
        except Exception:
            entries = []
        if not entries:
            return ("*Rules*\n\nNothing yet. Rules are written when you "
                    "correct something it did, and it follows them after.")
        lines = [f"*Rules* · {len(entries)}", ""]
        lines += ["• " + str(rule.get("statement", ""))[:160]
                  for rule in entries[:12]]
        return "\n".join(lines)

    def _folder(self, talk: Conversation) -> str:
        try:
            data = talk.session.folder() or {}
        except Exception:
            data = {}
        return ("*Folder*\n\n"
                f"```{data.get('current', '')}```\n\n"
                + ("It only reads and writes inside this folder."
                   if data.get("confined")
                   else "It is not confined to this folder."))

    def _writes(self) -> str:
        on = self.config.whatsapp.allow_writes
        return (
            "*What it may do from here*\n\n"
            + ("It *can* edit files and run commands, asking you first each "
               "time.\n\n" if on else
               "It *reads and plans only*. It will not edit a file or run a "
               "command from WhatsApp.\n\n")
            + "Changed at the terminal, on the machine it runs on:\n\n"
            + f"```comodor whatsapp writes {'off' if on else 'on'}```\n\n"
            + "_Not from here — a bot that could widen its own permissions "
              "would only need somebody's phone._"
        )
