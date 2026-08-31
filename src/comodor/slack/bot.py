"""The Slack bot: the same agent, in a workspace.

It runs the same `web.session.Session` the terminal, the browser, Telegram and
WhatsApp run, so a task started here learns the same lessons and lands in the
same history.

Of the three phone channels this is the closest to Telegram, because Slack has
the two things WhatsApp lacks: a message can be **edited**, so a reply is one
message that grows rather than a notification per paragraph; and buttons are
plentiful, so the whole menu fits one screen.

What is different from both is **where a message can come from**. Telegram and
WhatsApp are one person in one chat. A Slack app lives in a workspace with
channels, threads and other people in them, which produces three rules:

*It answers direct messages, and in a channel only when mentioned.* A bot that
replies to everything in a shared channel is a bot somebody removes that
afternoon.

*It answers in the thread it was spoken to in.* Otherwise a question asked in a
thread is answered in the channel, in front of everybody, out of context.

*It answers a fixed list of user ids and nobody else* — the same rule as the
other two. A workspace can have hundreds of people in it and the agent reads
and writes somebody's files.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..channels.busy import start_or_steer
from ..channels.markdown import to_slack
from ..channels.settings import Settings, keep_current
from ..config import Config
from ..media.ingest import MediaError, ingest
from . import blocks as ui
from .api import EDIT_EVERY, RateLimited, Slack, SlackError, escape, split
from .socket import Envelope, SocketMode

#: How long one turn may hold a worker before it is abandoned.
TURN_PATIENCE = 3600.0

#: `<@U123>` as it arrives in the text of a message that mentioned the bot.
MENTION = re.compile(r"<@[A-Z0-9]+>")


@dataclass
class Pairing:
    """A one-time code that adds one account to the allow-list."""

    code: str
    until: float

    @property
    def live(self) -> bool:
        return time.time() < self.until


@dataclass
class Reply:
    """The message a running turn is rewriting."""

    channel: str
    ts: str
    thread: str = ""
    last_drawn: float = 0.0
    finished: bool = False


@dataclass
class Waiting:
    """A question the agent asked, and what has been chosen so far."""

    request_id: str
    questions: list[dict[str, Any]] = field(default_factory=list)
    index: int = 0
    picked: dict[int, set[int]] = field(default_factory=dict)
    writing: bool = False


class Conversation:
    """One Slack user and the agent session behind them.

    Keyed by *user*, not by channel: the same person messaging from a DM and
    from a thread is one conversation with one history, which is what they
    expect and what the terminal would have given them.
    """

    def __init__(self, config: Config, user: str) -> None:
        from ..web.session import Session

        self.user = user
        self.session = Session(config)
        self.cursor = self.session.cursor
        self.reply: Reply | None = None
        self.waiting: Waiting | None = None
        self.shelf: dict[str, list[tuple[str, str]]] = {}
        #: Where to answer: the channel last spoken from, and the thread if
        #: there was one.
        self.channel = ""
        self.thread = ""
        self.lock = threading.Lock()

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass


class Service:
    """The socket, and everything it dispatches to."""

    def __init__(self, config: Config, slack: Slack | None = None,
                 announce: Callable[[str], None] | None = None) -> None:
        self.config = config
        #: The configuration file, watched. A bot is a detached process: every
        #: setting changed from the terminal or the web panel while it runs was
        #: invisible to it, and the command that changed the setting said it
        #: had worked. `allow_writes` is the one people hit — Act went on being
        #: refused with a message telling them to run what they had just run.
        self.settings = Settings(config)
        settings = config.slack
        self.slack = slack or Slack(settings.bot_token, settings.app_token)
        self.announce = announce or (lambda line: None)
        self.chats: dict[str, Conversation] = {}
        self.pairing: Pairing | None = None
        self.stopping = threading.Event()
        #: The bot's own user id, so its own messages are not answered — a bot
        #: that replies to itself is an infinite loop with a rate limit.
        self.me: str = ""
        self.socket = SocketMode(self.slack, self._on_envelope,
                                 announce=self.announce)

    def say(self, line: str) -> None:
        try:
            self.announce(line)
        except Exception:
            pass

    # -- pairing ----------------------------------------------------------- #

    def offer_pairing(self) -> str:
        code = f"{secrets.randbelow(900000) + 100000}"
        self.pairing = Pairing(
            code=code, until=time.time() + self.config.slack.pair_window)
        return code

    def _maybe_pair(self, user: str, channel: str, text: str) -> bool:
        offer = self.pairing
        if offer is None or not offer.live or text.strip() != offer.code:
            return False

        self.config.slack.allowed.append(user)
        self.pairing = None
        try:
            from .. import config as config_mod

            config_mod.save_user_config(self.config)
        except Exception:
            pass
        self.say(f"paired {user}")
        talk = self._conversation(user)
        talk.channel = channel
        self._menu(talk, "*Paired.* You can reach Comodor from here now.")
        return True

    # -- the loop ---------------------------------------------------------- #

    def run(self) -> None:
        try:
            who = self.slack.me()
            self.me = str(who.get("user_id") or "")
            self.say(f"connected as {who.get('user')} in {who.get('team')}")
        except SlackError as problem:
            self.say(f"Slack refused the bot token: {problem}")
            return

        settings = self.config.slack
        self.say(f"{len(settings.allowed)} paired account(s) · "
                 + ("may edit files" if settings.allow_writes
                    else "read-only"))
        self.socket.run()

    def stop(self) -> None:
        self.stopping.set()
        self.socket.stop()
        for talk in list(self.chats.values()):
            talk.close()
        self.chats.clear()

    # -- what arrives -------------------------------------------------------- #

    def _on_envelope(self, envelope: Envelope) -> None:
        # Before anything is decided: the answer to "what may this turn do"
        # has to be the answer as of now, not as of whenever the bot started.
        keep_current(self)

        if envelope.kind == "events_api":
            self._on_event(envelope.event)
        elif envelope.kind == "interactive":
            self._on_action(envelope.payload)

    def _on_event(self, event: dict[str, Any]) -> None:
        kind = str(event.get("type") or "")
        if kind not in ("message", "app_mention"):
            return
        # A bot's own message, an edit, a join notice. Answering any of them
        # is a loop.
        if event.get("bot_id") or event.get("subtype"):
            return

        user = str(event.get("user") or "")
        channel = str(event.get("channel") or "")
        if not user or user == self.me:
            return

        text = MENTION.sub("", str(event.get("text") or "")).strip()
        channel_kind = str(event.get("channel_type") or "")
        mentioned = kind == "app_mention" or f"<@{self.me}>" in str(
            event.get("text") or "")

        # In a shared channel, only when spoken to. A bot that answers every
        # message in a channel is a bot somebody removes that afternoon.
        if channel_kind not in ("im", "") and not mentioned:
            return

        if not self.config.slack.may(user):
            self._maybe_pair(user, channel, text)
            return

        talk = self._conversation(user)
        talk.channel = channel
        talk.thread = str(event.get("thread_ts") or "") or str(
            event.get("ts") or "") if channel_kind not in ("im", "") else ""

        if not text:
            if event.get("files"):
                self._on_media(talk, channel, event)
                return
            self._menu(talk)
            return
        if talk.waiting is not None and talk.waiting.writing:
            self._write_answer(talk, text)
            return
        if text.startswith("/"):
            self._on_command(talk, text)
            return
        self._start_turn(talk, text)

    def _on_action(self, payload: dict[str, Any]) -> None:
        user = str((payload.get("user") or {}).get("id") or "")
        if not user or not self.config.slack.may(user):
            return
        channel = str((payload.get("channel") or {}).get("id") or "")
        actions = payload.get("actions") or []
        if not actions:
            return
        action = str(actions[0].get("action_id")
                     or actions[0].get("value") or "")

        talk = self._conversation(user)
        if channel:
            talk.channel = channel
        message = payload.get("message") or {}
        if message.get("thread_ts"):
            talk.thread = str(message["thread_ts"])
        self._on_tap(talk, action)

    def _conversation(self, user: str) -> Conversation:
        talk = self.chats.get(user)
        if talk is None:
            talk = Conversation(self.config, user)
            if not self.config.slack.allow_writes:
                talk.session.set_mode("plan")
            self.chats[user] = talk
        return talk

    # -- sending ------------------------------------------------------------ #

    def _where(self, talk: Conversation) -> str:
        """The channel to answer in, opening a DM if there is none yet."""
        if talk.channel:
            return talk.channel
        try:
            talk.channel = self.slack.open_dm(talk.user)
        except SlackError as problem:
            self.say(f"could not open a DM with {talk.user}: {problem}")
        return talk.channel

    def _send(self, talk: Conversation, text: str,
              blocks: list[dict[str, Any]] | None = None) -> str:
        channel = self._where(talk)
        if not channel:
            return ""
        pieces = split(text) if not blocks else [text]
        ts = ""
        for piece in pieces:
            try:
                sent = self.slack.send(channel, piece, blocks=blocks,
                                       thread=talk.thread)
                ts = str(sent.get("ts") or "")
            except RateLimited as problem:
                time.sleep(problem.retry_after)
            except SlackError as problem:
                self.say(f"could not send: {problem}")
                return ""
        return ts

    def _menu(self, talk: Conversation, note: str = "") -> None:
        state = self._state(talk)
        self._send(talk, note or "Comodor", ui.main_menu(
            busy=bool(state.get("busy")),
            mode=str(state.get("mode") or self.config.agent.mode),
            rules=self._rule_count(talk),
            model=str(state.get("model") or ""),
            writes=self.config.slack.allow_writes,
            body=note or self._welcome(talk)))

    # -- commands and taps ---------------------------------------------------- #

    def _on_command(self, talk: Conversation, text: str) -> None:
        name = text[1:].split()[0].lower()
        rest = text[len(name) + 1:].strip()

        if name in ("start", "menu", "comodor"):
            self._menu(talk)
        elif name == "help":
            self._send(talk, self._help())
        elif name == "new":
            self._new_chat(talk)
        elif name == "stop":
            self._stop_turn(talk)
        elif name == "status":
            self._send(talk, self._status(talk))
        elif name == "mode":
            if rest.lower() in ui.MODES:
                self._set_mode(talk, rest.lower())
            else:
                self._send(talk, "Mode", ui.mode_menu(self._mode(talk)))
        else:
            self._menu(talk, f"No command called `/{name}`.")

    def _on_tap(self, talk: Conversation, action: str) -> None:
        verb, _, argument = action.partition(":")

        if verb == "menu":
            self._menu(talk)
        elif verb == "stop":
            self._stop_turn(talk)
        elif verb == "new":
            self._new_chat(talk)
        elif verb == "mode" and not argument:
            self._send(talk, "Mode", ui.mode_menu(self._mode(talk)))
        elif verb == "mode":
            self._set_mode(talk, argument)
        elif verb == "status":
            self._send(talk, self._status(talk))
        elif verb == "help":
            self._send(talk, self._help())
        elif verb == "writes":
            self._send(talk, self._writes())
        elif verb == "rules":
            self._send(talk, self._rules(talk))
        elif verb == "folder":
            self._send(talk, self._folder(talk))
        elif verb in ("chats", "models", "skills"):
            kind = {"chats": "chat", "models": "model",
                    "skills": "skill"}[verb]
            self._show(talk, kind, int(argument or 0))
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
            self._await_written(talk)
        elif verb == "qs":
            self._send_answers(talk)
        else:
            self._menu(talk)

    # -- media ---------------------------------------------------------------- #

    def _on_media(self, talk: Conversation, channel: str,
                  event: dict[str, Any]) -> None:
        """A file shared into the chat: download, type, and route it.

        Slack names files with an id and serves the bytes through
        `files.info`, whose URL carries the bot's own token — so the fetch is
        two calls, the same shape as every other channel's.
        """
        if not self.config.media.enabled:
            self._send(talk, "I can only read text here.")
            return
        f = (event.get("files") or [])[0] or {}
        file_id = str(f.get("id") or "")
        name = str(f.get("name") or "file")
        if not file_id:
            self._send(talk, "I could not read that file.")
            return
        try:
            data = self.slack.download(file_id)
            item = ingest(data, name=name, directory=self._media_dir(),
                          max_mb=self.config.media.max_download_mb)
        except MediaError as problem:
            self._send(talk, str(problem))
            return
        except Exception as problem:
            self._send(talk, f"I could not fetch that file: {problem}")
            return

        from ..media.route import route
        from ..providers.profile import of as profile_of

        routed = route(item, profile_of(self.config),
                       voice_to_text=self._transcriber())
        self._start_turn(talk, routed.text, images=routed.images)

    def _media_dir(self):
        from pathlib import Path

        configured = self.config.media.save_dir
        root = Path(configured) if configured else \
            Path(self.config.paths.user) / "media"
        return root / "slack"

    def _transcriber(self):
        if not self.config.media.voice_to_text:
            return None
        return None   # no transcription backend is wired yet; the note says so

    # -- turns ---------------------------------------------------------------- #

    def _start_turn(self, talk: Conversation, text: str,
                    images: list[str] | None = None) -> None:
        def refuse(note: str) -> None:
            self._menu(talk, note)

        if not start_or_steer(talk.session, text, images,
                              self.config.slack.busy_mode, refuse):
            return
        ts = self._send(talk, "_working…_")
        talk.reply = Reply(channel=self._where(talk), ts=ts,
                           thread=talk.thread) if ts else None
        threading.Thread(target=self._follow, args=(talk,),
                         name=f"comodor-slack-{talk.user}", daemon=True).start()

    def _follow(self, talk: Conversation) -> None:
        """Drain the event stream into one message that grows."""
        deadline = time.time() + TURN_PATIENCE
        streamed = ""
        tools: list[str] = []

        while time.time() < deadline and not self.stopping.is_set():
            events = talk.session.wait_for(talk.cursor, timeout=8.0)
            if events:
                talk.cursor = talk.session.cursor

            for event in events:
                kind = event.get("kind")
                if kind == "assistant_delta":
                    streamed += event.get("text", "")
                elif kind == "assistant_end" and event.get("text"):
                    streamed = event["text"]
                elif kind == "tool_start":
                    tools.append(event.get("summary") or event.get("name", ""))
                elif kind == "request":
                    self._ask(talk, event)
                elif kind == "error":
                    streamed += f"\n\n:warning: {event.get('text', '')}"
                elif kind == "turn_end":
                    self._draw(talk, streamed, tools, final=True)
                    return
                elif kind == "cancelled":
                    self._draw(talk, streamed + "\n\n_stopped_", tools,
                               final=True)
                    return

            self._draw(talk, streamed, tools)

        self._draw(talk, streamed, tools, final=True)

    def _draw(self, talk: Conversation, text: str, tools: list[str],
              final: bool = False) -> None:
        """Rewrite the reply, no more often than Slack will take."""
        reply = talk.reply
        if reply is None or reply.finished:
            return
        now = time.monotonic()
        if not final and now - reply.last_drawn < EDIT_EVERY:
            return
        reply.last_drawn = now

        # Slack reads mrkdwn, not Markdown: `*bold*` rather than `**bold**`,
        # `<url|text>` rather than `[text](url)`. Handed the model's own
        # markup it printed the punctuation.
        body = to_slack(text.strip()) or "_working…_"
        if tools:
            body += "\n\n_" + escape(" · ".join(tools[-3:])) + "_"

        state = self._state(talk)
        blocks = [ui.section(body[:2900])]
        if final:
            blocks = ui.main_menu(
                busy=False, mode=str(state.get("mode") or "plan"),
                rules=self._rule_count(talk),
                model=str(state.get("model") or ""),
                writes=self.config.slack.allow_writes, body=body[:2900])

        try:
            self.slack.edit(reply.channel, reply.ts, body[:2900], blocks)
        except RateLimited:
            return
        except SlackError as problem:
            self.say(f"could not update the reply: {problem}")
        if final:
            reply.finished = True
            talk.reply = None

    def _stop_turn(self, talk: Conversation) -> None:
        talk.session.interrupt()
        if talk.reply is not None:
            talk.reply.finished = True
        talk.reply = None
        self._menu(talk, "Stopped.")

    def _new_chat(self, talk: Conversation) -> None:
        talk.session.new_chat()
        talk.cursor = talk.session.cursor
        talk.reply = None
        talk.waiting = None
        self._menu(talk, "New chat. What would you like done?")

    def _set_mode(self, talk: Conversation, mode: str) -> None:
        if mode not in ui.MODES:
            self._menu(talk)
            return
        if mode == "act" and not self.config.slack.allow_writes:
            self._send(talk, self._writes())
            return
        talk.session.set_mode(mode)
        self._menu(talk, f"Mode is now *{ui.MODE_WORDS[mode]}*.")

    # -- questions and permissions -------------------------------------------- #

    def _ask(self, talk: Conversation, event: dict[str, Any]) -> None:
        what = event.get("what") or event.get("request") or {}
        request_id = str(event.get("id") or event.get("request_id") or "")

        if event.get("about") == "mode" or what.get("kind") == "mode":
            options = [option for option in event.get("options", []) if option]
            body = what.get("prompt") or event.get("prompt") or "Change mode?"
            self._send(talk, "Comodor suggests a mode change",
                       ui.mode_choices(request_id, body, options))
            return

        if what.get("kind") == "permission" or event.get("permission"):
            body = what.get("text") or event.get("text") or "May I?"
            self._send(talk, "Comodor wants to run something",
                       ui.permission(request_id, f"```{body}```"))
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
        self._send(talk, str(question.get("question") or "Which one?"),
                   ui.question(waiting.request_id, waiting.index,
                               str(question.get("question") or "Which one?"),
                               options, waiting.picked.get(waiting.index),
                               bool(question.get("multi")),
                               len(waiting.questions)))

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

    def _await_written(self, talk: Conversation) -> None:
        if talk.waiting is None:
            return
        talk.waiting.writing = True
        self._send(talk, "Type your answer and send it.")

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

    # -- paged lists ----------------------------------------------------------- #

    def _show(self, talk: Conversation, kind: str, page: int = 0) -> None:
        items, body = self._shelf_for(talk, kind)
        if not items:
            self._menu(talk, body)
            return
        talk.shelf[kind] = items
        rows = [(str(slot), label)
                for slot, (_, label) in enumerate(items)]
        self._send(talk, body, ui.page(kind, rows, body=body,
                                       page_number=page))

    def _shelf_for(self, talk: Conversation,
                   kind: str) -> tuple[list[tuple[str, str]], str]:
        if kind == "chat":
            found = talk.session.chats(limit=60)
            if not found:
                return [], "Nothing saved yet."
            return ([(str(c["id"]),
                      ("● " if c.get("current") else "")
                      + str(c.get("title") or "Untitled")) for c in found],
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
            return ([(n, ("● " if n == current else "") + n) for n in names],
                    f"*Model* — using `{current or '—'}` on {provider}.")
        if kind == "skill":
            shelf = talk.session.skill_shelf()
            cards = shelf.get("skills") or []
            if not cards:
                return [], "Nothing to show."
            installed = sum(1 for c in cards if c.get("installed"))
            return ([(str(c["id"]),
                      ("● " if c.get("installed") else "") + str(c["id"]))
                     for c in cards],
                    f"*Skills* — {installed} installed of {len(cards)}. "
                    f"Tap one to add or remove it.")
        return [], "Nothing here."

    def _chose(self, talk: Conversation, kind: str, slot: str) -> None:
        items = talk.shelf.get(kind) or []
        if not (slot.isdigit() and int(slot) < len(items)):
            self._menu(talk, "That list has moved on — open it again.")
            return
        key = items[int(slot)][0]

        if kind == "chat":
            ok, note, _ = talk.session.open_chat(key)
            talk.cursor = talk.session.cursor
            self._menu(talk, note or ("Opened." if ok else "Could not."))
        elif kind == "model":
            ok, note = talk.session.setting("model", key)
            self._menu(talk, note or (f"Now using `{key}`." if ok
                                      else "That did not take."))
        elif kind == "skill":
            shelf = talk.session.skill_shelf()
            here = next((c for c in shelf.get("skills") or []
                         if c.get("id") == key), None)
            action = "remove" if here and here.get("installed") else "install"
            ok, note = talk.session.skill(action, key)
            self._menu(talk, note or f"`{key}` {action}ed.")

    # -- what it says ----------------------------------------------------------- #

    def _state(self, talk: Conversation) -> dict[str, Any]:
        try:
            return talk.session.state() or {}
        except Exception:
            return {}

    def _mode(self, talk: Conversation) -> str:
        return str(self._state(talk).get("mode") or self.config.agent.mode)

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
        return (f"*Comodor*\nSend a task and it gets on with it.\n\n"
                f"*Model* `{model}`   *Folder* `{folder}`")

    def _help(self) -> str:
        return (
            "*What this can do*\n\n"
            "Type a task — _why is the build failing?_, _add a health "
            "endpoint_ — and it works on it.\n"
            "In a channel, mention it. In a DM, just type.\n\n"
            "*Buttons*\n"
            "• *New chat* — forget the conversation so far\n"
            "• *History* — re-open an earlier one\n"
            "• *Mode* — what it may do\n"
            "• *Status* — model, folder, context, spend\n"
            "• *Model* — switch to another\n"
            "• *Skills* — procedures it follows\n"
            "• *Rules* — what it learned from your corrections\n\n"
            "When it needs to run something, you approve it here first."
        )

    def _status(self, talk: Conversation) -> str:
        state = self._state(talk)
        context = state.get("context") or {}
        usage = state.get("usage") or {}
        used = int(context.get("used") or 0)
        limit = int(context.get("limit") or 0)
        share = f"{used / limit:.0%}" if limit else "—"
        cost = usage.get("cost")
        spend = f"${cost:.4f}" if isinstance(cost, (int, float)) else "—"
        return ("*Status*\n"
                f"Model   `{state.get('provider', '—')} / "
                f"{state.get('model', '—')}`\n"
                f"Mode    `{state.get('mode', '—')}`\n"
                f"Folder  `{state.get('project', '—')}`\n"
                f"Context `{share} of {limit:,}`\n"
                f"Spend   `{spend}`")

    def _rules(self, talk: Conversation) -> str:
        try:
            entries = (talk.session.rules() or {}).get("rules") or []
        except Exception:
            entries = []
        if not entries:
            return ("*Rules*\nNothing yet. Rules are written when you correct "
                    "something it did, and it follows them after.")
        lines = [f"*Rules* · {len(entries)}"]
        lines += ["• " + str(rule.get("statement", ""))[:160]
                  for rule in entries[:12]]
        return "\n".join(lines)

    def _folder(self, talk: Conversation) -> str:
        try:
            data = talk.session.folder() or {}
        except Exception:
            data = {}
        return (f"*Folder*\n`{data.get('current', '')}`\n"
                + ("It only reads and writes inside this folder."
                   if data.get("confined")
                   else "It is not confined to this folder."))

    def _writes(self) -> str:
        on = self.config.slack.allow_writes
        return (
            "*What it may do from here*\n"
            + ("It *can* edit files and run commands, asking you first each "
               "time.\n\n" if on else
               "It *reads and plans only*. It will not edit a file or run a "
               "command from Slack.\n\n")
            + "Changed at the terminal, on the machine it runs on:\n"
            + f"```comodor slack writes {'off' if on else 'on'}```\n"
            + "_Not from here — a bot that could widen its own permissions "
              "would only need somebody's Slack account._"
        )
