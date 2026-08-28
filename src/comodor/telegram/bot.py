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
                folder=state.get("cwd", "")))
        elif verb == "rules":
            done()
            self.bot.send(chat, self._rules(talk), keyboard=kb.just_back())
        elif verb == "folder":
            done()
            self.bot.send(chat, self._folder(talk), keyboard=kb.just_back())
        elif verb == "cost":
            done()
            self.bot.send(chat, self._status(talk), keyboard=kb.just_back("settings"))
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

        body = escape(text.strip()) or "<i>working…</i>"
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
            talk.chat, head + escape(question.get("prompt", "")),
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
            escape(question.get("prompt", "")),
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
        return kb.main_menu(busy=bool(state.get("busy")),
                            mode=state.get("mode", self.config.agent.mode),
                            rules=int(state.get("rules") or 0))

    def _welcome(self) -> str:
        writes = self.config.telegram.allow_writes
        return (
            "<b>Comodor</b>\n\n"
            "Send a task and it gets on with it — it reads your project, works "
            "out what to change, and tells you what it found.\n\n"
            + ("It can edit files and run commands.\n"
               if writes else
               "<b>Reading only.</b> It will not edit files or run commands "
               "from here until that is turned on at the terminal.\n")
            + "\nEverything else is a button below."
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
        used = int(state.get("context_used") or 0)
        limit = int(state.get("context_limit") or 0)
        share = f"{used / limit:.0%}" if limit else "—"
        cost = state.get("cost_usd")
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
            f"Folder    <code>{escape(str(state.get('cwd', '—')))}</code>",
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
            lines.append("• " + escape(str(rule.get("text", ""))[:160]))
        return "\n".join(lines)

    def _folder(self, talk: Conversation) -> str:
        data = talk.session.folder()
        return ("<b>Folder</b>\n\n"
                f"<code>{escape(str(data.get('cwd', '')))}</code>\n\n"
                "It only reads and writes inside this folder.")
