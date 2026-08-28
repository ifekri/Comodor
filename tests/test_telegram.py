"""The Telegram bot: who it answers, what it will do, and what it never says.

A bot's username is public and its address is guessable, so most of what
matters here is refusal. The tests are weighted accordingly.
"""

from __future__ import annotations

from typing import Any

import pytest

from comodor.telegram import api
from comodor.telegram import keyboard as kb
from comodor.telegram.api import Bot, TelegramError, Unauthorised, split

# --------------------------------------------------------------------------- #
# the client
# --------------------------------------------------------------------------- #


def test_a_token_that_is_not_one_is_refused_before_the_network():
    for bad in ("", "nonsense", "no-colon-here"):
        with pytest.raises(TelegramError, match="bot token"):
            Bot(bad)


def test_the_token_never_appears_in_an_error(monkeypatch):
    """It is in every URL, so anything that echoes a URL echoes the secret."""
    token = "123456:SUPER-SECRET-VALUE"
    bot = Bot(token)

    class Boom:
        status_code = 400

        def json(self):
            return {"ok": False,
                    "description": f"failed for https://api.telegram.org/bot{token}/x"}

    monkeypatch.setattr(api.http, "post", lambda *a, **k: Boom())
    with pytest.raises(TelegramError) as caught:
        bot.call("sendMessage")
    assert "SUPER-SECRET-VALUE" not in str(caught.value)
    assert "123456" in str(caught.value), "the public half may stay"


def test_the_token_is_not_in_the_repr():
    assert "SECRET" not in repr(Bot("42:SECRET"))


def test_a_refused_token_is_its_own_error(monkeypatch):
    class Refused:
        status_code = 401

        def json(self):
            return {"ok": False, "description": "Unauthorized"}

    monkeypatch.setattr(api.http, "post", lambda *a, **k: Refused())
    with pytest.raises(Unauthorised):
        Bot("42:x").me()


def test_the_poll_can_say_how_long_to_hold_the_connection(monkeypatch):
    """`getUpdates` has a `timeout` of its own, and so did the client. Passing
    both through one signature raised a TypeError on the first real poll."""
    seen: dict[str, Any] = {}

    class Empty:
        status_code = 200

        def json(self):
            return {"ok": True, "result": []}

    def post(url, data=None, timeout=None, **kwargs):
        seen["sent"] = data
        seen["waited"] = timeout
        return Empty()

    monkeypatch.setattr(api.http, "post", post)
    Bot("42:x").updates(timeout=30)

    assert seen["sent"]["timeout"] == 30, "Telegram was not told how long to hold"
    assert seen["waited"][1] > 30, "the client would give up before the poll ends"


def test_the_offset_advances_so_a_restart_replays_nothing(monkeypatch):
    """Without it every message the bot ever saw is answered again — which,
    for an agent that runs commands, is not merely noisy."""
    class Some:
        status_code = 200

        def json(self):
            return {"ok": True, "result": [{"update_id": 7}, {"update_id": 9}]}

    monkeypatch.setattr(api.http, "post", lambda *a, **k: Some())
    bot = Bot("42:x")
    bot.updates()
    assert bot.offset == 10


@pytest.mark.parametrize("length", [0, 1, 4095, 4096, 4097, 20000])
def test_every_piece_fits_what_telegram_will_take(length):
    pieces = split("x" * length)
    assert all(len(piece) <= api.MOST_CHARACTERS for piece in pieces)
    assert "".join(pieces).replace(" ", "") == "x" * length


def test_a_long_message_breaks_where_a_reader_would():
    paragraph = ("word " * 900).strip()
    text = paragraph + "\n\n" + paragraph
    pieces = split(text)
    assert len(pieces) > 1
    assert not pieces[0].endswith("wor"), "it cut a word in half"


# --------------------------------------------------------------------------- #
# the buttons
# --------------------------------------------------------------------------- #


def test_no_callback_payload_can_be_silently_dropped():
    """Telegram refuses to send a keyboard whose data is over 64 bytes, and
    says nothing — the message simply arrives with no buttons under it."""
    boards = [
        kb.main_menu(busy=False, mode="act", rules=3),
        kb.main_menu(busy=True, mode="plan"),
        kb.mode_menu("plan"),
        kb.settings_menu(provider="Anthropic", model="claude-opus-5", folder="/x"),
        kb.permission("a" * 12),
        kb.question("r" * 12, 3, ["one", "two", "three"], {1}, multi=True),
        kb.picker("open", [(f"id{n}", f"Item {n}") for n in range(30)]),
        kb.confirm("wipe"),
        kb.just_back(),
    ]
    for board in boards:
        for row in board["inline_keyboard"]:
            for button in row:
                if "callback_data" in button:
                    assert len(button["callback_data"].encode()) <= 64


def test_an_oversized_payload_is_caught_where_it_is_made():
    with pytest.raises(ValueError, match="107 bytes"):
        kb.button("x", "action:" + "y" * 100)


def test_a_busy_menu_offers_stopping_and_not_starting():
    """A button that is present and does nothing is the most confusing control
    there is, so the state changes what is offered rather than disabling it."""
    busy = kb.main_menu(busy=True, mode="act")
    labels = [b["text"] for row in busy["inline_keyboard"] for b in row]
    assert any("Stop" in text for text in labels)
    assert not any("New chat" in text for text in labels)

    idle = kb.main_menu(busy=False, mode="act")
    labels = [b["text"] for row in idle["inline_keyboard"] for b in row]
    assert any("New chat" in text for text in labels)
    assert not any("Stop" in text for text in labels)


def test_every_screen_has_a_way_back():
    for board in (kb.mode_menu("act"),
                  kb.settings_menu(provider="x", model="y", folder="z"),
                  kb.picker("open", [("a", "A")]),
                  kb.just_back()):
        labels = [b["text"] for row in board["inline_keyboard"] for b in row]
        assert any("Back" in text for text in labels)


def test_the_widest_commitment_is_not_the_first_thing_under_a_thumb():
    """On a phone the buttons are close together and "always" is not undoable."""
    rows = kb.permission("r1")["inline_keyboard"]
    assert "once" in rows[0][0]["text"].lower()
    assert "stop asking" in rows[1][0]["text"].lower()


def test_the_modes_say_what_they_do():
    """`plan` could as easily mean "make a plan and carry it out", and this is
    the setting that decides whether the next message edits somebody's files."""
    labels = [b["text"] for row in kb.mode_menu("act")["inline_keyboard"]
              for b in row]
    joined = " ".join(labels).lower()
    assert "edits files" in joined
    assert "reads only" in joined


# --------------------------------------------------------------------------- #
# who it answers
# --------------------------------------------------------------------------- #


class Recorder:
    """Stands in for the network, and remembers everything sent."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self.answered: list[str] = []
        self.offset = 0

    def me(self):
        return {"id": 1, "username": "comodor_bot", "first_name": "Comodor"}

    def drop_webhook(self):
        pass

    def commands(self, entries):
        pass

    def typing(self, chat):
        pass

    def send(self, chat, text, *, keyboard=None, **kwargs):
        self.sent.append({"chat": chat, "text": text, "keyboard": keyboard})
        return {"message_id": len(self.sent)}

    def edit(self, chat, message, text, keyboard=None):
        self.edits.append({"chat": chat, "text": text})
        return {}

    def answer_callback(self, query, text="", alert=False):
        self.answered.append(text)

    def updates(self, timeout=0):
        return []


@pytest.fixture
def service(config, monkeypatch):
    from comodor.telegram.bot import Service

    config.telegram.token = "42:test"
    config.telegram.enabled = True
    monkeypatch.setattr("comodor.web.session.Session.__init__",
                        lambda self, cfg: None)
    made = Service(config, bot=Recorder())
    return made


def a_message(user: int, text: str, chat: int | None = None):
    return {"update_id": 1, "message": {
        "message_id": 1,
        "from": {"id": user, "username": "someone"},
        "chat": {"id": chat if chat is not None else user},
        "text": text,
    }}


def test_a_stranger_is_met_with_silence(service):
    """A bot that says "you are not allowed" has told somebody it exists, that
    it is a Comodor, and that there is a list worth getting onto."""
    service._handle(a_message(999, "hello"))
    service._handle(a_message(999, "/start"))
    service._handle(a_message(999, "rm -rf /"))
    assert service.bot.sent == []


def test_the_wrong_pairing_code_is_also_silence(service):
    service.offer_pairing()
    service._handle(a_message(999, "000000"))
    assert service.bot.sent == []
    assert 999 not in service.config.telegram.allowed


def test_the_right_code_pairs_once_and_stops_working(service, monkeypatch):
    monkeypatch.setattr("comodor.config.save_user_config", lambda cfg: None)
    code = service.offer_pairing()

    service._handle(a_message(555, code))
    assert 555 in service.config.telegram.allowed
    assert service.bot.sent, "it should say hello"

    # A second account cannot reuse it.
    service._handle(a_message(777, code))
    assert 777 not in service.config.telegram.allowed


def test_an_expired_code_pairs_nobody(service, monkeypatch):
    import time

    monkeypatch.setattr("comodor.config.save_user_config", lambda cfg: None)
    code = service.offer_pairing()
    service.pairing.until = time.time() - 1
    service._handle(a_message(555, code))
    assert 555 not in service.config.telegram.allowed


def test_a_tap_from_a_stranger_is_refused(service):
    service._handle({"update_id": 2, "callback_query": {
        "id": "q1", "from": {"id": 999},
        "message": {"chat": {"id": 999}}, "data": "stop"}})
    assert service.bot.sent == []
    assert service.bot.answered == ["Not paired."]


def test_allowed_is_by_id_not_username(config):
    """A username can be given up and taken by somebody else; an id cannot."""
    config.telegram.allowed = [555]
    assert config.telegram.may(555)
    assert config.telegram.may("555")
    assert not config.telegram.may(556)
    assert not config.telegram.may(0)


def test_a_project_cannot_add_itself_to_the_allowed_list():
    """It would be a backdoor that nothing on screen would ever show."""
    from comodor.config import project_filtered

    kept, refused = project_filtered(
        {"telegram": {"allowed": [999], "token": "x"}, "agent": {"mode": "plan"}})
    assert "telegram" in refused
    assert "telegram" not in kept


def test_writes_are_off_until_somebody_says_otherwise(config):
    assert config.telegram.allow_writes is False
    assert config.telegram.enabled is False
    assert config.telegram.allowed == []


def test_the_token_is_not_written_into_a_project_config(config):
    from comodor.config import project_filtered

    _, refused = project_filtered({"telegram": {"token": "42:stolen"}})
    assert "telegram" in refused


# --------------------------------------------------------------------------- #
# what it says
# --------------------------------------------------------------------------- #


def test_angle_brackets_survive(config):
    """Agent output is full of them — generics, JSX, shell redirects — and one
    unescaped turns the rest into an unclosed tag that Telegram rejects
    wholesale, so the message never arrives and nothing says why."""
    from comodor.telegram.bot import escape

    assert escape("List<String> x = a > b") == "List&lt;String&gt; x = a &gt; b"
    assert escape("<script>alert(1)</script>").startswith("&lt;script&gt;")


def test_the_welcome_says_whether_it_can_change_anything(service):
    service.config.telegram.allow_writes = False
    assert "Reading only" in service._welcome()

    service.config.telegram.allow_writes = True
    assert "Reading only" not in service._welcome()
    assert "run commands" in service._welcome()


def test_the_slash_commands_are_registered_and_few():
    """The buttons are the interface; a command list mirroring every button is
    two things to keep in step."""
    names = [name for name, _ in kb.COMMANDS]
    assert "start" in names and "stop" in names
    assert len(kb.COMMANDS) <= 8
    assert all(what for _, what in kb.COMMANDS), "every command needs a blurb"


def test_backoff_climbs_and_stops():
    steps = [api.backoff(n) for n in range(10)]
    assert steps == sorted(steps)
    assert max(steps) <= 60


def test_the_status_survives_having_no_spend_yet(service, monkeypatch):
    """Written as one concatenation with a trailing conditional, the `if` bound
    to the whole expression rather than the last line — so a fresh session
    reported its entire status as the words "Spend —"."""
    class Talk:
        class session:
            @staticmethod
            def state():
                return {"provider": "xiaomi", "model": "mimo", "mode": "plan",
                        "cwd": "/w", "context_used": 0, "context_limit": 128000,
                        "cost_usd": None}

    text = service._status(Talk())
    assert "<b>Status</b>" in text
    assert "xiaomi" in text and "plan" in text and "/w" in text
    assert "Spend" in text and text.count("\n") >= 5


def test_the_status_shows_a_real_spend_when_there_is_one(service):
    class Talk:
        class session:
            @staticmethod
            def state():
                return {"provider": "x", "model": "y", "mode": "act", "cwd": "/w",
                        "context_used": 100, "context_limit": 1000,
                        "cost_usd": 0.0412}

    text = service._status(Talk())
    assert "$0.0412" in text
    assert "10% of 1,000" in text
