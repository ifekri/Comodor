"""The Discord bot: the same agent, on a server.

It runs the same `web.session.Session` the terminal, the phone channels and
Slack run, so a task started here lands in the same history and learns the
same lessons.

Discord is the fourth channel and reads most like Telegram: one token, an
allow-list of numeric ids, a message that can be **edited** so a reply is one
message that grows. What is Discord's own is the shape of the conversation:

*It answers direct messages, and in a server only when mentioned.* A bot that
replies to everything in a server with three thousand people in it is a bot
somebody bans that afternoon — the same rule as Slack, with stakes an order
of magnitude larger.

*It answers by snowflake id and nobody else.* Not the username, not the
display name: both are changeable and both can be given up. The id cannot.

*It answers from the terminal, not the app.* Pairing is a one-time code typed
at the machine that runs the bot — the only place a decision about who may
reach an agent that edits files should be made.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..channels.breaker import CircuitBreaker
from ..channels.busy import interrupt_note, start_or_steer
from ..channels.markdown import to_discord
from ..channels.settings import Settings, keep_current
from ..config import Config
from .api import EDIT_EVERY, MOST_CHARACTERS, DiscordError, RateLimited, split
from .api import Bot as Rest
from .gateway import Gateway

#: How long one turn may hold a worker before it is abandoned.
TURN_PATIENCE = 3600.0

#: `<@123456789012345678>` as a mention arrives in message content, with the
#: nickname variant beside it.
MENTION = re.compile(r"<@!?[0-9]+>")

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
    message_id: str
    last_drawn: float = 0.0
    finished: bool = False

class Conversation:
    """One Discord user and the agent session behind them.

    Keyed by *user*, not by channel: the same person messaging from a DM and
    from a server is one conversation with one history, which is what they
    expect and what the terminal would have given them.
    """

    def __init__(self, config: Config, user: str) -> None:
        from ..web.session import Session

        self.user = user
        self.session = Session(config)
        self.cursor = self.session.cursor
        self.reply: Reply | None = None
        #: Where to answer: the channel last spoken from.
        self.channel = ""
        self.lock = threading.Lock()

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass

class Service:
    """The gateway, and everything it dispatches to."""

    def __init__(self, config: Config, bot: Rest | None = None,
                 announce: Callable[[str], None] | None = None) -> None:
        self.config = config
        #: The configuration file, watched — the same live settings the other
        #: adapters read, so `comodor discord writes on` reaches a running bot.
        self.settings = Settings(config)
        settings = config.discord
        self.bot = bot or Rest(settings.token)
        self.announce = announce or (lambda line: None)
        self.chats: dict[str, Conversation] = {}
        self.pairing: Pairing | None = None
        self.stopping = threading.Event()
        #: The bot's own user id, so its own messages are not answered — a bot
        #: that replies to itself is an infinite loop with a rate limit.
        self.me: str = ""
        self._breaker = CircuitBreaker("discord")
        self.gateway = Gateway(settings.token, self._on_message,
                               announce=self.announce,
                               breaker=self._breaker)

    def say(self, line: str) -> None:
        try:
            self.announce(line)
        except Exception:
            pass

    # -- pairing ----------------------------------------------------------- #

    def offer_pairing(self) -> str:
        code = f"{secrets.randbelow(900000) + 100000}"
        self.pairing = Pairing(
            code=code, until=time.time() + self.config.discord.pair_window)
        return code

    def _maybe_pair(self, user: str, channel: str, text: str) -> bool:
        offer = self.pairing
        if offer is None or not offer.live or text.strip() != offer.code:
            return False

        self.config.discord.allowed.append(int(user))
        self.pairing = None
        try:
            from .. import config as config_mod

            config_mod.save_user_config(self.config)
        except Exception:
            pass
        self.say(f"paired {user}")
        talk = self._conversation(user)
        talk.channel = channel
        self._send(talk, "**Paired.** You can reach Comodor from here now.")
        return True

    # -- the loop ---------------------------------------------------------- #

    def run(self) -> None:
        try:
            who = self.bot.me()
            self.me = str(who.get("id") or "")
            self.say(f"connected as {who.get('username')}")
        except DiscordError as problem:
            self.say(f"Discord refused the bot token: {problem}")
            return

        settings = self.config.discord
        self.say(f"{len(settings.allowed)} paired account(s) · "
                 + ("may edit files" if settings.allow_writes
                    else "read-only"))
        self.gateway.run()

    def stop(self) -> None:
        self.stopping.set()
        self.gateway.stop()
        for talk in list(self.chats.values()):
            talk.close()
        self.chats.clear()

    # -- what arrives -------------------------------------------------------- #

    def _on_message(self, event: dict[str, Any]) -> None:
        # Before anything is decided: the answer to "what may this turn do"
        # has to be the answer as of now, not as of whenever the bot started.
        keep_current(self)

        author = event.get("author") or {}
        user = str(author.get("id") or "")
        if not user or user == self.me or author.get("bot"):
            return

        channel = str(event.get("channel_id") or "")
        content = str(event.get("content") or "")
        text = MENTION.sub("", content).strip()

        # In a server, only when spoken to. In a DM, always. The guild id is
        # absent exactly when the channel is a DM.
        if event.get("guild_id") and f"<@{self.me}>" not in content \
                and f"<@!{self.me}>" not in content:
            return

        if not self.config.discord.may(int(user) if user.isdigit() else 0):
            self._maybe_pair(user, channel, text)
            return

        talk = self._conversation(user)
        talk.channel = channel

        if not text:
            return
        if text.startswith("/"):
            self._on_command(talk, text)
            return
        self._start_turn(talk, text)

    def _conversation(self, user: str) -> Conversation:
        talk = self.chats.get(user)
        if talk is None:
            talk = Conversation(self.config, user)
            if not self.config.discord.allow_writes:
                talk.session.set_mode("plan")
            self.chats[user] = talk
        return talk

    # -- sending ------------------------------------------------------------ #

    def _send(self, talk: Conversation, text: str) -> str:
        """One message, split if Discord would refuse its length."""
        if not talk.channel:
            return ""
        message_id = ""
        for piece in split(text):
            try:
                sent = self.bot.send(talk.channel, piece)
                message_id = str((sent or {}).get("id") or "")
                self._breaker.ok()
            except RateLimited as problem:
                time.sleep(problem.retry_after)
            except DiscordError as problem:
                self._send_failed(problem)
                return ""
        return message_id

    def _send_failed(self, problem: Exception) -> None:
        if self._breaker.fail(str(problem)):
            self.say(f"{problem} — paused; send /platform in Discord to "
                     "resume it")
            return
        self.say(f"could not send: {problem}")

    # -- commands ------------------------------------------------------------ #

    def _on_command(self, talk: Conversation, text: str) -> None:
        name = text[1:].split()[0].lower()
        rest = text[len(name) + 1:].strip()

        if name in ("start", "menu", "help"):
            self._send(talk, self._welcome(talk) if name != "help"
                       else self._help())
        elif name == "new":
            self._new_chat(talk)
        elif name == "stop":
            self._stop_turn(talk)
        elif name == "mode":
            if rest.lower() in MODES:
                self._set_mode(talk, rest.lower())
            else:
                self._send(talk, self._mode_menu())
        elif name == "status":
            self._send(talk, self._status(talk))
        elif name == "platform":
            breaker = self._breaker
            if breaker.paused:
                breaker.resume()
                self._send(talk, "Discord is listening again.")
                return
            self._send(talk, breaker.describe())
        else:
            self._send(talk, f"No command called `/{name}`.")

    def _mode_menu(self) -> str:
        words = {"act": "may change things", "plan": "plans, asks first",
                 "ask": "answers only", "chat": "conversation"}
        return "**Mode**\n" + "\n".join(
            f"• `/mode {name}` — {what}" for name, what in words.items())

    # -- turns ---------------------------------------------------------------- #

    def _start_turn(self, talk: Conversation, text: str,
                    images: list[str] | None = None) -> None:
        def refuse(note: str) -> None:
            self._send(talk, note)

        if not start_or_steer(talk.session, text, images,
                              self.config.discord.busy_mode, refuse):
            return
        self.bot.typing(talk.channel)
        message_id = self._send(talk, "_working…_")
        talk.reply = Reply(channel=talk.channel, message_id=message_id) \
            if message_id else None
        threading.Thread(target=self._follow, args=(talk,),
                         name=f"comodor-discord-{talk.user}",
                         daemon=True).start()

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
                    self._send(talk, str(event.get("text")
                                         or event.get("prompt")
                                         or "Comodor has a question."))
                elif kind == "error":
                    streamed += f"\n\n⚠ {event.get('text', '')}"
                elif kind == "turn_end":
                    self._draw(talk, streamed, tools, final=True)
                    return
                elif kind == "cancelled":
                    self._draw(talk, streamed + "\n\n_stopped_"
                               + interrupt_note(event), tools, final=True)
                    return

            self._draw(talk, streamed, tools)

        self._draw(talk, streamed, tools, final=True)

    def _draw(self, talk: Conversation, text: str, tools: list[str],
              final: bool = False) -> None:
        """Rewrite the reply, no more often than Discord will take."""
        reply = talk.reply
        if reply is None or reply.finished or not reply.message_id:
            return
        now = time.monotonic()
        if not final and now - reply.last_drawn < EDIT_EVERY:
            return
        reply.last_drawn = now

        # Discord reads Markdown almost as the model writes it, so this is
        # the lightest conversion of any channel — mostly escape what would
        # start an element and leave the emphasis.
        body = to_discord(text.strip())[:MOST_CHARACTERS] or "_working…_"
        if tools:
            recent = tools[-3:]
            body = (body[:MOST_CHARACTERS - 80] + "\n\n_"
                    + escape(" · ".join(recent)) + "_")

        if not final:
            try:
                self.bot.edit(reply.channel, reply.message_id, body)
            except RateLimited:
                return
            except DiscordError as problem:
                self.say(f"could not update the reply: {problem}")
            return
        try:
            self.bot.edit(reply.channel, reply.message_id, body)
        except Exception as problem:
            self._send_failed(problem)
            return
        reply.finished = True
        talk.reply = None

    def _stop_turn(self, talk: Conversation) -> None:
        talk.session.interrupt()
        if talk.reply is not None:
            talk.reply.finished = True
        talk.reply = None
        self._send(talk, "Stopped.")

    def _new_chat(self, talk: Conversation) -> None:
        talk.session.new_chat()
        talk.cursor = talk.session.cursor
        talk.reply = None
        self._send(talk, "New chat. What would you like done?")

    def _set_mode(self, talk: Conversation, mode: str) -> None:
        if mode == "act" and not self.config.discord.allow_writes:
            self._send(talk, self._writes())
            return
        talk.session.set_mode(mode)
        self._send(talk, f"Mode is now **{mode}**.")

    # -- what it says ----------------------------------------------------------- #

    def _writes(self) -> str:
        on = self.config.discord.allow_writes
        return (
            "**What it may do from here**\n"
            + ("It *can* edit files and run commands, asking you first each "
               "time.\n" if on else
               "It *reads and plans only*. It will not edit a file or run a "
               "command from Discord.\n")
            + "\nChanged at the terminal, on the machine it runs on:\n"
            + f"```\ncomodor discord writes {'off' if on else 'on'}\n```\n"
            + "_Not from here — a bot that could widen its own permissions "
              "would only need somebody's Discord account._")

    def _welcome(self, talk: Conversation) -> str:
        state: dict[str, Any] = {}
        try:
            state = talk.session.state() or {}
        except Exception:
            state = {}
        model = str(state.get("model") or self.config.model or "—")
        folder = str(state.get("project") or self.config.paths.project or "")
        folder = folder.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "—"
        return (f"**Comodor**\nSend a task and it gets on with it.\n\n"
                f"**Model** `{model}`   **Folder** `{folder}`\n\n"
                + ("It may edit files, asking first." if
                   self.config.discord.allow_writes else
                   "It reads and plans only from here."))

    def _help(self) -> str:
        return (
            "**What this can do**\n\n"
            "Type a task — _why is the build failing?_, _add a health "
            "endpoint_ — and it works on it.\n"
            "In a server, mention it. In a DM, just type.\n\n"
            "**Commands**\n"
            "• `/new` — forget the conversation so far\n"
            "• `/stop` — interrupt what is running\n"
            "• `/mode` — whether it may change anything\n"
            "• `/status` — model, folder, context, spend\n\n"
            "When it needs to run something, it says so and waits — the "
            "approval is given at the terminal, on the machine it runs on.")

    def _status(self, talk: Conversation) -> str:
        try:
            state = talk.session.state() or {}
        except Exception:
            state = {}
        context = state.get("context") or {}
        usage = state.get("usage") or {}
        used = int(context.get("used") or 0)
        limit = int(context.get("limit") or 0)
        share = f"{used / limit:.0%}" if limit else "—"
        cost = usage.get("cost")
        spend = f"${cost:.4f}" if isinstance(cost, (int, float)) else "—"
        return ("**Status**\n"
                f"Model   `{state.get('provider', '—')} / "
                f"{state.get('model', '—')}`\n"
                f"Mode    `{state.get('mode', '—')}`\n"
                f"Folder  `{state.get('project', '—')}`\n"
                f"Context `{share} of {limit:,}`\n"
                f"Spend   `{spend}`")


#: The modes the /mode command may set. Matches what the TUI and the other
#: channels offer.
MODES = ("act", "plan", "ask", "chat")


def escape(text: str) -> str:
    """The two characters Discord reads as markup in ordinary text.

    Not the full escape — asterisks and underscores are wanted, because the
    bot writes with them. These are the ones that make Discord eat a
    mention or start a link out of something that is neither.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">",
                                                                   "&gt;")
