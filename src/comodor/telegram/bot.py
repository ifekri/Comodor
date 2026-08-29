"""The bot: one Telegram chat, driving one agent session.

The session is the same object the browser interface uses. That is the whole
design — `web.session.Session` already turns the agent into something a
disconnected client can talk to, with an event cursor, a permission channel and
every management call. A second implementation of any of that would be a second
place for it to be wrong.

**Who may talk to it.** A bot's username is public and anybody who guesses it
can send it a message. This one answers a fixed list of numeric user ids and
nobody else — silently, because a bot that says "you are not allowed" to a
stranger has confirmed it exists and is worth attacking. The list is filled by
pairing from the terminal, where somebody is already trusted.

**What a turn may do.** Approving a shell command with a thumb, on a phone, in
a queue, is a decision made with less attention than the same approval at a
keyboard. So `telegram.allow_writes` is off by default and the session is held
in plan mode regardless of what the terminal is set to — the bot reads, plans
and answers, and cannot edit or run anything until somebody deliberately turns
that on.

**Streaming.** The agent produces tokens; Telegram charges a round trip per
edit and rate-limits them. So the reply is edited on a timer rather than per
token, which is the difference between a message that grows readably and one
that is rate-limited into arriving all at once at the end.
"""

from __future__ import annotations

import html
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..channels.markdown import to_telegram
from ..config import Config
from . import keyboard as kb
from .api import Bot, TelegramError, Unauthorised, backoff

#: How often a streaming reply is rewritten. Telegram's limit is about one
#: edit a second per chat; under that and the edits are dropped, over it and
#: the message crawls.
EDIT_EVERY = 1.6

#: How long a turn may run before the bot stops waiting on it. The agent keeps
#: going; this only decides when the message stops being updated.
TURN_PATIENCE = 1800.0


def escape(text: str) -> str:
    """For Telegram's HTML parse mode.

    Agent output is full of angle brackets — generics, JSX, shell redirects —
    and an unescaped one turns the rest of the message into an unclosed tag,
    which Telegram rejects wholesale. The message then never arrives and
    nothing says why.
    """
    return html.escape(text or "", quote=False)


def code(text: str) -> str:
    return f"<pre>{escape(text)}</pre>"


@dataclass
class Pairing:
    """A code shown in the terminal, waiting to be typed into Telegram."""

    code: str
    until: float

    @property
    def live(self) -> bool:
        return time.time() < self.until


@dataclass
class Reply:
    """A message being written to, as the agent produces it."""

    chat: int
    message: int
    text: str = ""
    last_drawn: float = 0.0
    finished: bool = False


@dataclass
class Waiting:
    """A question or a permission prompt the agent is blocked on."""

    request_id: str
    kind: str
    questions: list[dict[str, Any]] = field(default_factory=list)
    answers: dict[int, set[int]] = field(default_factory=dict)
    written: dict[int, str] = field(default_factory=dict)
    at: int = 0
    message: int = 0
    #: Set while the bot is waiting for the next thing typed to be an answer
    #: rather than a new task.
    typing_into: int | None = None


class Conversation:
    """One Telegram chat and the agent session behind it."""

    def __init__(self, config: Config, chat: int) -> None:
        from ..web.session import Session

        self.chat = chat
        self.session = Session(config)
        self.cursor = self.session.cursor
        self.reply: Reply | None = None
        self.waiting: Waiting | None = None
        self.page: dict[str, int] = {}
        #: What each paged list is currently showing, so a tap can name a row
        #: by number. Callback data is capped at sixty-four bytes and a model
        #: id or a session id will not always fit inside one — so the id stays
        #: here and the button carries an index into this.
        self.shelf: dict[str, list[tuple[str, str]]] = {}
        self.lock = threading.Lock()

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass


class Service:
    """The long-poll loop and everything it dispatches to."""

    def __init__(self, config: Config, bot: Bot | None = None,
                 announce=None) -> None:
        self.config = config
        self.bot = bot or Bot(config.telegram.token)
        self.chats: dict[int, Conversation] = {}
        self.pairing: Pairing | None = None
        self.stopping = threading.Event()
        #: Called with a line of text for the terminal that started this.
        self.announce = announce or (lambda line: None)
        self._lock = threading.Lock()

    # -- lifecycle --------------------------------------------------------- #

    def offer_pairing(self) -> str:
        """A one-time code that adds whoever types it to the allowed list."""
        code_ = f"{secrets.randbelow(900000) + 100000}"
        self.pairing = Pairing(
            code=code_, until=time.time() + self.config.telegram.pair_window)
        return code_

    def run(self) -> None:
        """Poll until stopped. Blocks."""
        self.bot.drop_webhook()
        try:
            self.bot.commands(kb.COMMANDS)
        except TelegramError:
            pass

        me = self.bot.me()
        self.announce(f"@{me['username']} is listening")

        failures = 0
        while not self.stopping.is_set():
            try:
                for update in self.bot.updates():
                    if self.stopping.is_set():
                        break
                    self._handle(update)
                failures = 0
            except Unauthorised as problem:
                self.announce(f"the token was refused: {problem}")
                return
            except TelegramError as problem:
                failures += 1
                pause = backoff(failures)
                self.announce(f"{problem} — retrying in {pause:.0f}s")
                if self.stopping.wait(pause):
                    return
            except Exception as problem:      # pragma: no cover - defensive
                failures += 1
                self.announce(f"unexpected: {type(problem).__name__}: {problem}")
                if self.stopping.wait(backoff(failures)):
                    return

    def stop(self) -> None:
        self.stopping.set()
        for conversation in list(self.chats.values()):
            conversation.close()

    # -- dispatch ---------------------------------------------------------- #

    def _handle(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        tapped = update.get("callback_query")

        if tapped:
            user = (tapped.get("from") or {}).get("id", 0)
            chat = ((tapped.get("message") or {}).get("chat") or {}).get("id", 0)
            if not self._allowed(user):
                self.bot.answer_callback(tapped["id"], "Not paired.", alert=True)
                return
            self._on_tap(chat, tapped)
            return

        if not message:
            return
        user = (message.get("from") or {}).get("id", 0)
        chat = (message.get("chat") or {}).get("id", 0)
        text = (message.get("text") or "").strip()

        if not self._allowed(user):
            self._maybe_pair(chat, user, text, message)
            return
        if text:
            self._on_text(chat, text)

    def _allowed(self, user: int) -> bool:
        return self.config.telegram.may(user)

    def _maybe_pair(self, chat: int, user: int, text: str,
                    message: dict[str, Any]) -> None:
        """The only thing an unpaired account can do.

        Everything else is met with silence. A bot that explains it is not
        talking to you has told a stranger that it exists, that it is a Comodor
        instance, and that there is a list to get onto.
        """
        pairing = self.pairing
        if not (pairing and pairing.live and text == pairing.code):
            return

        with self._lock:
            if user not in self.config.telegram.allowed:
                self.config.telegram.allowed.append(int(user))
            self.pairing = None

        from .. import config as config_mod
        config_mod.save_user_config(self.config)

        who = (message.get("from") or {}).get("username") or user
        self.announce(f"paired with @{who} ({user})")
        self.bot.send(chat, self._welcome(), keyboard=self._menu(chat))

    # -- text -------------------------------------------------------------- #

    def _on_text(self, chat: int, text: str) -> None:
        talk = self._conversation(chat)

        # An answer being typed into a question takes precedence over anything
        # that looks like a command, because somebody answering "what should
        # the database be?" with "/new" means the word, not the command.
        if talk.waiting and talk.waiting.typing_into is not None:
            self._write_answer(talk, text)
            return

        if text.startswith("/"):
            self._on_command(talk, text)
            return

        self._start_turn(talk, text)

    def _on_command(self, talk: Conversation, text: str) -> None:
        name = text[1:].split()[0].split("@")[0].lower()
        rest = text[len(name) + 1:].strip()

        if name in ("start", "menu", "help"):
            self.bot.send(talk.chat, self._welcome() if name != "help"
                          else self._help(), keyboard=self._menu(talk.chat))
        elif name == "new":
            self._new_chat(talk)
        elif name == "stop":
            self._stop_turn(talk)
        elif name == "mode":
            if rest.lower() in kb.MODES:
                self._set_mode(talk, rest.lower())
            else:
                self.bot.send(talk.chat, "<b>Mode</b>",
                              keyboard=kb.mode_menu(self.config.agent.mode))
        elif name == "status":
            self.bot.send(talk.chat, self._status(talk),
                          keyboard=kb.just_back())
        else:
            self.bot.send(talk.chat, f"No command <code>/{escape(name)}</code>.",
                          keyboard=self._menu(talk.chat))

    # -- taps -------------------------------------------------------------- #

    def _on_tap(self, chat: int, tapped: dict[str, Any]) -> None:
        talk = self._conversation(chat)
        data = tapped.get("data") or ""
        query = tapped["id"]
        verb, _, argument = data.partition(":")

        def done(note: str = "") -> None:
            self.bot.answer_callback(query, note)

        if verb == "menu":
            done()
            self.bot.send(chat, "<b>Comodor</b>", keyboard=self._menu(chat))
        elif verb == "stop":
            done("Stopping")
            self._stop_turn(talk)
        elif verb == "new":
            done("New chat")
            self._new_chat(talk)
        elif verb == "mode" and not argument:
            done()
            self.bot.send(chat, "<b>Mode</b>\n\nWhat the next message is "
                                "allowed to do.",
                          keyboard=kb.mode_menu(self.config.agent.mode))
        elif verb == "mode":
            done(argument.capitalize())
            self._set_mode(talk, argument)
        elif verb == "status":
            done()
            self.bot.send(chat, self._status(talk), keyboard=kb.just_back())
        elif verb == "settings":
            done()
            state = talk.session.state()
            self.bot.send(chat, "<b>Settings</b>", keyboard=kb.settings_menu(
                provider=state.get("provider", "—"),
                model=state.get("model", "—"),
                folder=state.get("project", "")))
        elif verb == "rules":
            done()
            self.bot.send(chat, self._rules(talk), keyboard=kb.just_back())
        elif verb == "folder":
            done()
            self.bot.send(chat, self._folder(talk), keyboard=kb.just_back())
        elif verb == "cost":
            done()
            self.bot.send(chat, self._status(talk), keyboard=kb.just_back("settings"))
        elif verb == "help":
            done()
            self.bot.send(chat, self._help(), keyboard=kb.just_back())
        elif verb == "writes":
            done()
            self.bot.send(chat, self._writes(), keyboard=kb.just_back("settings"))
        elif verb == "chats":
            done()
            self._show_chats(talk, int(argument or 0))
        elif verb == "chat":
            done("Opening")
            self._open_chat(talk, argument)
        elif verb == "models":
            done()
            self._show_models(talk, int(argument or 0))
        elif verb == "model":
            done("Switching")
            self._use_model(talk, argument)
        elif verb == "skills":
            done()
            self._show_skills(talk, int(argument or 0))
        elif verb == "skill":
            done()
            self._toggle_skill(talk, argument)
        elif verb == "page":
            done()
            where, _, number = argument.partition(":")
            page = int(number or 0)
            if where == "chat":
                self._show_chats(talk, page)
            elif where == "model":
                self._show_models(talk, page)
            elif where == "skill":
                self._show_skills(talk, page)
        elif verb in ("ok", "okall", "no"):
            done({"ok": "Approved", "okall": "Approved",
                  "no": "Refused"}[verb])
            self._answer_permission(talk, argument, verb)
        elif verb == "q":
            done()
            self._pick_option(talk, argument, tapped)
        elif verb == "qw":
            done("Type your answer")
            self._await_written(talk, argument)
        elif verb == "qs":
            done("Sent")
            self._send_answers(talk)
        else:
            done()

    # -- turns ------------------------------------------------------------- #

    def _start_turn(self, talk: Conversation, text: str) -> None:
        if not talk.session.send(text):
            self.bot.send(talk.chat,
                          "Something is already running. Stop it first.",
                          keyboard=self._menu(talk.chat))
            return

        self.bot.typing(talk.chat)
        sent = self.bot.send(talk.chat, "<i>thinking…</i>")
        talk.reply = Reply(chat=talk.chat, message=sent["message_id"]) \
            if sent else None
        threading.Thread(target=self._follow, args=(talk,),
                         name=f"comodor-tg-{talk.chat}", daemon=True).start()

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
                    streamed += f"\n\n⚠ {event.get('text', '')}"
                elif kind == "turn_end":
                    self._draw(talk, streamed, tools, final=True)
                    return
                elif kind == "cancelled":
                    self._draw(talk, streamed + "\n\n<i>stopped</i>", tools,
                               final=True)
                    return

            self._draw(talk, streamed, tools)

        self._draw(talk, streamed, tools, final=True)

    def _draw(self, talk: Conversation, text: str, tools: list[str],
              final: bool = False) -> None:
        """Rewrite the reply, but not more often than Telegram will take."""
        reply = talk.reply
        if reply is None or reply.finished:
            return
        now = time.monotonic()
        if not final and now - reply.last_drawn < EDIT_EVERY:
            return
        reply.last_drawn = now

        # The model writes Markdown and Telegram reads HTML, so this used to
        # escape the answer and hand somebody a wall of asterisks, brackets
        # and backticks. It is converted now, not escaped.
        body = to_telegram(text.strip()) or "<i>working…</i>"
        if tools:
            recent = tools[-3:]
            body += "\n\n<i>" + escape(" · ".join(recent)) + "</i>"

        self.bot.edit(reply.chat, reply.message, body,
                      keyboard=self._menu(talk.chat) if final else None)
        if final:
            reply.finished = True
            talk.reply = None

    def _stop_turn(self, talk: Conversation) -> None:
        talk.session.interrupt()
        self.bot.send(talk.chat, "Stopped.", keyboard=self._menu(talk.chat))

    def _new_chat(self, talk: Conversation) -> None:
        talk.session.new_chat()
        talk.cursor = talk.session.cursor
        talk.reply = None
        talk.waiting = None
        self.bot.send(talk.chat, "New chat. What would you like done?",
                      keyboard=self._menu(talk.chat))

    def _set_mode(self, talk: Conversation, mode: str) -> None:
        if mode == "act" and not self.config.telegram.allow_writes:
            self.bot.send(
                talk.chat,
                "<b>Act mode is off for Telegram.</b>\n\n"
                "Approving a command with a thumb is a decision made with less "
                "attention than the same one at a keyboard, so this starts off. "
                "Turn it on from the terminal:\n\n"
                + code("comodor telegram writes on"),
                keyboard=kb.just_back())
            return
        talk.session.set_mode(mode)
        self.bot.send(talk.chat, f"Mode is now <b>{escape(mode)}</b>.",
                      keyboard=self._menu(talk.chat))

    # -- what the agent asks ----------------------------------------------- #

    def _ask(self, talk: Conversation, event: dict[str, Any]) -> None:
        request_id = event.get("id", "")
        if event.get("about") == "questions":
            questions = event.get("questions") or []
            talk.waiting = Waiting(request_id=request_id, kind="questions",
                                   questions=questions)
            self._show_question(talk)
            return

        talk.waiting = Waiting(request_id=request_id, kind="permission")
        text = f"<b>{escape(event.get('prompt', 'Allow this?'))}</b>"
        if event.get("detail"):
            text += "\n\n" + code(event["detail"][:900])
        self.bot.send(talk.chat, text, keyboard=kb.permission(request_id))

    def _show_question(self, talk: Conversation) -> None:
        waiting = talk.waiting
        if not waiting or not waiting.questions:
            return
        question = waiting.questions[waiting.at]
        options = [o.get("label", "") for o in question.get("options", [])
                   if not o.get("free")]

        head = (f"<b>Question {waiting.at + 1} of {len(waiting.questions)}</b>\n\n"
                if len(waiting.questions) > 1 else "")
        sent = self.bot.send(
            talk.chat, head + to_telegram(question.get("prompt", "")),
            keyboard=kb.question(waiting.request_id, waiting.at, options,
                                 waiting.answers.get(waiting.at, set()),
                                 multi=bool(question.get("multi"))))
        if sent:
            waiting.message = sent["message_id"]

    def _pick_option(self, talk: Conversation, argument: str,
                     tapped: dict[str, Any]) -> None:
        waiting = talk.waiting
        if not waiting:
            return
        try:
            _, index, slot = argument.split(":")
            index, slot = int(index), int(slot)
        except ValueError:
            return

        question = waiting.questions[index]
        chosen = waiting.answers.setdefault(index, set())
        if question.get("multi"):
            chosen.symmetric_difference_update({slot})
        else:
            chosen.clear()
            chosen.add(slot)
            waiting.written.pop(index, None)

        options = [o.get("label", "") for o in question.get("options", [])
                   if not o.get("free")]
        self.bot.edit(
            talk.chat, waiting.message,
            to_telegram(question.get("prompt", "")),
            keyboard=kb.question(waiting.request_id, index, options, chosen,
                                 multi=bool(question.get("multi"))))

        # A single-answer question with more to come moves on by itself; making
        # somebody tap "next" after every choice is a tap that carries no
        # information.
        if not question.get("multi"):
            if index + 1 < len(waiting.questions):
                waiting.at = index + 1
                self._show_question(talk)
            else:
                self._send_answers(talk)

    def _await_written(self, talk: Conversation, argument: str) -> None:
        waiting = talk.waiting
        if not waiting:
            return
        try:
            _, index = argument.split(":")
        except ValueError:
            return
        waiting.typing_into = int(index)
        self.bot.send(talk.chat,
                      "Send your answer as a message.",
                      keyboard=kb.just_back("menu"))

    def _write_answer(self, talk: Conversation, text: str) -> None:
        waiting = talk.waiting
        if not waiting or waiting.typing_into is None:
            return
        index = waiting.typing_into
        waiting.written[index] = text
        waiting.answers.pop(index, None)
        waiting.typing_into = None

        if index + 1 < len(waiting.questions):
            waiting.at = index + 1
            self._show_question(talk)
        else:
            self._send_answers(talk)

    def _send_answers(self, talk: Conversation) -> None:
        from ..questions import Answer, encode_answers

        waiting = talk.waiting
        if not waiting:
            return
        answers = []
        for index, question in enumerate(waiting.questions):
            options = question.get("options", [])
            picked = [options[slot].get("label", "")
                      for slot in sorted(waiting.answers.get(index, set()))
                      if slot < len(options)]
            answers.append(Answer(
                header=question.get("header", ""),
                prompt=question.get("prompt", ""),
                chosen=picked,
                written=waiting.written.get(index, ""),
            ))
        talk.session.answer(waiting.request_id, encode_answers(answers))
        talk.waiting = None
        self.bot.send(talk.chat, "Thanks — carrying on.")

    def _answer_permission(self, talk: Conversation, request_id: str,
                           verb: str) -> None:
        choice = {"ok": "allow", "okall": "allow_always", "no": "deny"}[verb]
        took, why = talk.session.answer(request_id, choice)
        if not took and why:
            self.bot.send(talk.chat, escape(why))
        talk.waiting = None

    # -- what it says ------------------------------------------------------ #

    def _conversation(self, chat: int) -> Conversation:
        with self._lock:
            talk = self.chats.get(chat)
            if talk is None:
                talk = Conversation(self.config, chat)
                if not self.config.telegram.allow_writes:
                    # Held in plan whatever the terminal is set to.
                    talk.session.set_mode("plan")
                self.chats[chat] = talk
            return talk

    def _menu(self, chat: int) -> dict[str, Any]:
        talk = self.chats.get(chat)
        state = talk.session.state() if talk else {}
        # The count comes from the rules themselves. `state()` carries no
        # `rules` key, so the button read "Rules" with no number on it however
        # many had been learned — which is the one thing that button is for.
        learned = 0
        if talk is not None:
            try:
                learned = int((talk.session.rules() or {}).get("active") or 0)
            except Exception:
                learned = 0
        return kb.main_menu(busy=bool(state.get("busy")),
                            mode=state.get("mode", self.config.agent.mode),
                            rules=learned,
                            model=str(state.get("model") or ""))

    # -- the paged screens -------------------------------------------------- #
    #
    # Three buttons here — History, Model, Skills — were on the keyboard with
    # nothing behind them. Tapping did nothing at all: no message, no error,
    # no note. A control that appears to work and does not is worse than one
    # that is missing, because the person taps it again.

    def _shelve(self, talk: Conversation, kind: str,
                items: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Remember a list, and hand back index-keyed rows for the buttons."""
        talk.shelf[kind] = items
        return [(str(slot), label) for slot, (_, label) in enumerate(items)]

    def _shelved(self, talk: Conversation, kind: str, slot: str) -> str:
        """The id behind a tapped row, or empty if the list has moved on."""
        items = talk.shelf.get(kind) or []
        if slot.isdigit() and int(slot) < len(items):
            return items[int(slot)][0]
        return ""

    def _show_chats(self, talk: Conversation, page: int = 0) -> None:
        found = talk.session.chats(limit=60)
        if not found:
            self.bot.send(talk.chat, "<b>History</b>\n\nNothing saved yet.",
                          keyboard=kb.just_back())
            return
        rows = self._shelve(talk, "chat", [
            (str(card["id"]),
             (f"{kb.PICKED} " if card.get("current") else "")
             + escape(str(card.get("title") or "Untitled"))[:44]
             + f" · {card.get('messages', 0)}")
            for card in found])
        self.bot.send(
            talk.chat,
            f"<b>History</b>\n\n{len(found)} saved. "
            f"Opening one brings its whole conversation back.",
            keyboard=kb.picker("chat", rows, page=page))

    def _open_chat(self, talk: Conversation, slot: str) -> None:
        session_id = self._shelved(talk, "chat", slot)
        if not session_id:
            self.bot.send(talk.chat, "That list has moved on — open History "
                                     "again.", keyboard=kb.just_back())
            return
        ok, note, _ = talk.session.open_chat(session_id)
        talk.cursor = talk.session.cursor
        self.bot.send(talk.chat, escape(note or ("Opened." if ok else "Could "
                                                 "not open that one.")),
                      keyboard=self._menu(talk.chat))

    def _show_models(self, talk: Conversation, page: int = 0) -> None:
        state = talk.session.state()
        provider = str(state.get("provider") or self.config.provider)
        current = str(state.get("model") or "")
        found = talk.session.models_for(provider)
        names = [str(entry.get("id") or entry.get("name") or "")
                 for entry in found.get("models") or []]
        names = [name for name in names if name]
        if not names:
            self.bot.send(
                talk.chat,
                f"<b>Model</b>\n\nCurrently <b>{escape(current or '—')}</b> "
                f"on {escape(provider)}.\n\nCould not list what else "
                f"{escape(provider)} offers"
                + (f" ({escape(str(found.get('error')))})."
                   if found.get("error") else " right now."),
                keyboard=kb.just_back())
            return
        rows = self._shelve(talk, "model", [
            (name, (f"{kb.PICKED} " if name == current
                    else f"{kb.UNPICKED} ") + name[:56])
            for name in names])
        self.bot.send(
            talk.chat,
            f"<b>Model</b>\n\nUsing <b>{escape(current or '—')}</b> on "
            f"{escape(provider)}. {len(names)} available.",
            keyboard=kb.picker("model", rows, page=page, back="settings"))

    def _use_model(self, talk: Conversation, slot: str) -> None:
        name = self._shelved(talk, "model", slot)
        if not name:
            self.bot.send(talk.chat, "That list has moved on — open Model "
                                     "again.", keyboard=kb.just_back())
            return
        ok, note = talk.session.setting("model", name)
        self.bot.send(
            talk.chat,
            escape(note) if note else
            (f"Now using <b>{escape(name)}</b>." if ok
             else "That did not take."),
            keyboard=self._menu(talk.chat))

    def _show_skills(self, talk: Conversation, page: int = 0) -> None:
        shelf = talk.session.skill_shelf()
        cards = shelf.get("skills") or []
        if not cards:
            self.bot.send(
                talk.chat,
                "<b>Skills</b>\n\nNothing to show"
                + (f" ({escape(str(shelf.get('error')))})."
                   if shelf.get("error") else "."),
                keyboard=kb.just_back())
            return
        rows = self._shelve(talk, "skill", [
            (str(card["id"]),
             (f"{kb.PICKED} " if card.get("installed")
              else f"{kb.UNPICKED} ") + str(card["id"])[:40])
            for card in cards])
        installed = sum(1 for card in cards if card.get("installed"))
        self.bot.send(
            talk.chat,
            f"<b>Skills</b>\n\nA written procedure the agent follows when the "
            f"work calls for it.\n{installed} installed of {len(cards)}. "
            f"Tapping one installs it, or removes it if it is already there.",
            keyboard=kb.picker("skill", rows, page=page, back="settings"))

    def _toggle_skill(self, talk: Conversation, slot: str) -> None:
        name = self._shelved(talk, "skill", slot)
        if not name:
            self.bot.send(talk.chat, "That list has moved on — open Skills "
                                     "again.", keyboard=kb.just_back())
            return
        shelf = talk.session.skill_shelf()
        here = next((card for card in shelf.get("skills") or []
                     if card.get("id") == name), None)
        action = "remove" if here and here.get("installed") else "install"
        ok, note = talk.session.skill(action, name)
        self.bot.send(
            talk.chat,
            escape(note) if note else
            (f"<b>{escape(name)}</b> {action}ed." if ok
             else f"Could not {action} {escape(name)}."),
            keyboard=kb.just_back("skills"))

    def _writes(self) -> str:
        """What a Telegram turn is allowed to do, and where to change it.

        Read-only from a phone is the default and it is not changeable from the
        phone: approving a shell command with a thumb, in a queue, is a
        decision made with less attention than the same approval at a keyboard,
        and the consequences are identical. Saying so plainly is better than a
        button that refuses.
        """
        on = self.config.telegram.allow_writes
        return (
            "<b>What it may do from here</b>\n\n"
            + ("It <b>can</b> edit files and run commands, asking you first "
               "each time.\n\n" if on else
               "It <b>reads and plans only</b>. It will not edit a file or "
               "run a command from Telegram.\n\n")
            + "This one is changed at the terminal, on the machine it runs "
              "on:\n\n<code>comodor telegram writes "
            + ("off" if on else "on")
            + "</code>\n\n<i>Not from here — a bot that could widen its own "
              "permissions would only need somebody's phone.</i>"
        )

    def _welcome(self) -> str:
        """The first thing anybody sees, and the only screen they arrive on.

        It says what it is pointed at — model, folder, what it may do — because
        those are the three things somebody wants to know before they trust it
        with a task, and a greeting that makes them tap three buttons to find
        out is a greeting that wasted their first message.

        Each button is named with what it changes, so the keyboard underneath
        reads as a list of settings rather than a row of symbols.
        """
        writes = self.config.telegram.allow_writes
        state: dict[str, Any] = {}
        for talk in list(self.chats.values()):
            try:
                state = talk.session.state()
            except Exception:
                state = {}
            break

        model = escape(str(state.get("model") or self.config.model or "—"))
        folder = str(state.get("project") or self.config.paths.project or "")
        folder = escape(folder.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "—")

        return (
            "<b>Comodor</b>\n\n"
            "Send a task and it gets on with it — it reads your project, works "
            "out what to change, and tells you what it found.\n\n"
            f"<b>Model</b>  {model}\n"
            f"<b>Folder</b>  {folder}\n"
            + ("<b>May</b>  edit files and run commands, asking first\n"
               if writes else
               "<b>May</b>  read and plan only\n")
            + "\nThe buttons below are the settings:\n"
              "<b>Mode</b> what it may do · <b>Model</b> which one it uses · "
              "<b>Folder</b> where it works · <b>Skills</b> procedures to "
              "follow · <b>Rules</b> what it learned from you\n\n"
              "<i>Or just send a task.</i>"
        )

    def _help(self) -> str:
        return (
            "<b>What this can do</b>\n\n"
            "Type a task — <i>why is the build failing?</i>, <i>add a health "
            "endpoint</i> — and it works on it, showing what it is doing as it "
            "goes.\n\n"
            "<b>Buttons</b>\n"
            "• <b>New chat</b> — forget the conversation so far\n"
            "• <b>Stop</b> — interrupt what is running\n"
            "• <b>Mode</b> — whether it may change anything\n"
            "• <b>Status</b> — model, folder, context, spend\n"
            "• <b>Folder</b> — which project it is working in\n"
            "• <b>Rules</b> — what it has learned from your corrections\n\n"
            "When it needs a decision it asks with buttons. When it needs to "
            "run something, you approve it here first."
        )

    def _status(self, talk: Conversation) -> str:
        state = talk.session.state()
        # Read from where `Session.state()` actually puts them. These used to
        # ask for `context_used`, `context_limit`, `cost_usd` and `cwd` — four
        # keys that have never been in that dictionary — so Folder, Context
        # and Spend reported nothing on every status anybody asked for, with
        # no error anywhere to say why.
        context = state.get("context") or {}
        usage = state.get("usage") or {}
        used = int(context.get("used") or 0)
        limit = int(context.get("limit") or 0)
        share = f"{used / limit:.0%}" if limit else "—"
        cost = usage.get("cost")
        # Built as a list. Written as one concatenation with a trailing
        # conditional, the `if` bound to the whole expression rather than to
        # the last line — so a session with no spend yet reported its entire
        # status as the words "Spend —".
        spend = f"${cost:.4f}" if isinstance(cost, (int, float)) else "—"
        lines = [
            "<b>Status</b>",
            "",
            f"Model     <code>{escape(str(state.get('provider', '—')))}"
            f" / {escape(str(state.get('model', '—')))}</code>",
            f"Mode      <code>{escape(str(state.get('mode', '—')))}</code>",
            f"Folder    <code>{escape(str(state.get('project', '—')))}</code>",
            f"Context   <code>{share} of {limit:,}</code>",
            f"Spend     <code>{spend}</code>",
        ]
        return "\n".join(lines)

    def _rules(self, talk: Conversation) -> str:
        data = talk.session.rules()
        entries = data.get("rules") or []
        if not entries:
            return ("<b>Rules</b>\n\nNothing yet. Rules are written when you "
                    "correct something it did, and it follows them afterwards.")
        lines = [f"<b>Rules</b> · {len(entries)}\n"]
        for rule in entries[:12]:
            # `statement`, which is what a rule card carries. `text` was never
            # a key on it, so every rule printed as an empty bullet.
            lines.append("• " + escape(str(rule.get("statement", ""))[:160]))
        return "\n".join(lines)

    def _folder(self, talk: Conversation) -> str:
        data = talk.session.folder()
        return ("<b>Folder</b>\n\n"
                f"<code>{escape(str(data.get('current', '')))}</code>\n\n"
                + ("It only reads and writes inside this folder."
                   if data.get("confined")
                   else "It is not confined to this folder."))
