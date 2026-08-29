"""Slack: Socket Mode, who it answers, and every button doing something.

Socket Mode is the reason this channel is as easy to set up as Telegram — the
app opens a websocket outward, so nothing needs a public address. Most of what
can go wrong is in that loop, and all of it is silent: an unacknowledged
envelope is redelivered and becomes a second turn, a routine `disconnect` taken
as a failure kills a bot every few hours, and a bot that answers its own
messages is a loop with a rate limit on it.
"""

from __future__ import annotations

from typing import Any

import pytest

from comodor.config import Config, Paths
from comodor.slack import blocks as ui
from comodor.slack.api import Slack, SlackError, Unauthorised, split
from comodor.slack.socket import Envelope, SocketMode


@pytest.fixture
def config(tmp_path):
    made = Config(paths=Paths(user=tmp_path / "home", project=tmp_path / "work"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    (tmp_path / "work").mkdir(parents=True, exist_ok=True)
    made.slack.bot_token = "xoxb-a-real-looking-token"
    made.slack.app_token = "xapp-1-a-real-looking-token"
    made.slack.allowed = ["U0000001"]
    return made


# --------------------------------------------------------------------------- #
# the two tokens, which are the commonest way this fails
# --------------------------------------------------------------------------- #


def test_the_app_token_in_the_bot_slot_is_named(config):
    with pytest.raises(SlackError, match="app-level token"):
        Slack("xapp-1-abc")


def test_the_bot_token_in_the_app_slot_is_named(config):
    with pytest.raises(SlackError, match="bot token"):
        Slack("xoxb-abc", "xoxb-def")


def test_something_that_is_neither_is_refused_before_the_network():
    with pytest.raises(SlackError, match="starts `xoxb-`"):
        Slack("token-please")


def test_neither_token_appears_in_an_error():
    slack = Slack("xoxb-SUPER-SECRET-BOT", "xapp-1-SUPER-SECRET-APP")
    hidden = slack._hide("failed with xoxb-SUPER-SECRET-BOT and "
                         "xapp-1-SUPER-SECRET-APP")

    assert "SUPER-SECRET" not in hidden
    assert "SECRET" not in repr(slack)


def test_a_missing_scope_says_to_reinstall(monkeypatch):
    """A scope added without reinstalling does not reach the token you have,
    and the error alone does not say so."""
    from comodor.slack import api

    class Refused:
        status_code = 200
        headers: dict[str, str] = {}

        def json(self):
            return {"ok": False, "error": "missing_scope",
                    "needed": "chat:write"}

    monkeypatch.setattr(api.http, "post", lambda *a, **k: Refused())
    with pytest.raises(Unauthorised, match="reinstall"):
        Slack("xoxb-x").me()


def test_being_rate_limited_carries_how_long_to_wait(monkeypatch):
    from comodor.slack import api

    class Slowed:
        status_code = 429
        headers = {"Retry-After": "7"}

        def json(self):
            return {"ok": False, "error": "ratelimited"}

    monkeypatch.setattr(api.http, "post", lambda *a, **k: Slowed())
    with pytest.raises(api.RateLimited) as caught:
        Slack("xoxb-x").me()
    assert caught.value.retry_after == 7


@pytest.mark.parametrize("length", [0, 1, 3899, 3900, 3901, 20000])
def test_every_piece_fits_what_slack_will_take(length):
    pieces = split("x" * length)
    assert all(len(piece) <= 3900 for piece in pieces)
    assert "".join(pieces).replace(" ", "") == "x" * length


# --------------------------------------------------------------------------- #
# the socket
# --------------------------------------------------------------------------- #


class FakeSocket:
    """A websocket that hands over a script and records what was sent back."""

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.sent: list[str] = []
        self.closed = False
        self.pings = 0

    def receive(self) -> str:
        from comodor.net.ws import WebSocketError

        if not self.script:
            raise WebSocketError("the server closed the connection")
        return self.script.pop(0)

    def send(self, text: str) -> None:
        self.sent.append(text)

    def ping(self, payload: bytes = b"") -> None:
        self.pings += 1

    def close(self) -> None:
        self.closed = True


def a_socket(monkeypatch, script: list[str], seen: list[Envelope]):
    from comodor.slack import socket as socket_mod

    fake = FakeSocket(script)
    monkeypatch.setattr(socket_mod, "WebSocket",
                        lambda url, timeout=10.0: fake)

    class Opener:
        def open_socket(self):
            return "wss://example.invalid/link"

    mode = SocketMode(Opener(), seen.append, announce=lambda line: None)
    return mode, fake


def test_every_envelope_is_acknowledged(monkeypatch):
    """Slack redelivers anything it does not hear about, and for an agent that
    runs commands one message becoming three turns is not merely noisy."""
    import json

    seen: list[Envelope] = []
    mode, fake = a_socket(monkeypatch, [
        json.dumps({"type": "hello"}),
        json.dumps({"type": "events_api", "envelope_id": "e1",
                    "payload": {"event": {"type": "message", "text": "hi"}}}),
        json.dumps({"type": "disconnect", "reason": "refresh_requested"}),
    ], seen)

    mode._session("wss://example.invalid/link")

    assert [json.loads(s)["envelope_id"] for s in fake.sent] == ["e1"]
    assert len(seen) == 1
    assert seen[0].event["text"] == "hi"


def test_a_redelivered_envelope_is_not_a_second_turn(monkeypatch):
    import json

    seen: list[Envelope] = []
    same = json.dumps({"type": "events_api", "envelope_id": "e1",
                       "payload": {"event": {"type": "message", "text": "hi"}}})
    mode, fake = a_socket(monkeypatch, [
        same, same,
        json.dumps({"type": "disconnect", "reason": "refresh_requested"}),
    ], seen)

    mode._session("wss://example.invalid/link")

    assert len(seen) == 1, "the same envelope became two turns"
    assert len(fake.sent) == 2, "both deliveries must still be acknowledged"


def test_a_disconnect_is_routine_not_a_failure(monkeypatch):
    """Slack rotates connections on a schedule. Treating that as an error
    produces a bot that dies every few hours."""
    import json

    seen: list[Envelope] = []
    mode, _ = a_socket(monkeypatch, [
        json.dumps({"type": "disconnect", "reason": "refresh_requested"}),
    ], seen)

    mode._session("wss://example.invalid/link")     # returns rather than raises


def test_a_handler_that_throws_does_not_stop_the_loop(monkeypatch):
    import json

    def explode(envelope):
        raise RuntimeError("bad")

    from comodor.slack import socket as socket_mod

    fake = FakeSocket([
        json.dumps({"type": "events_api", "envelope_id": "e1", "payload": {}}),
        json.dumps({"type": "events_api", "envelope_id": "e2", "payload": {}}),
        json.dumps({"type": "disconnect", "reason": "warning"}),
    ])
    monkeypatch.setattr(socket_mod, "WebSocket",
                        lambda url, timeout=10.0: fake)

    class Opener:
        def open_socket(self):
            return "wss://example.invalid"

    mode = SocketMode(Opener(), explode, announce=lambda line: None)
    mode._session("wss://example.invalid")

    assert len(fake.sent) == 2, "it stopped after the first failure"


def test_a_bad_app_token_is_not_retried_for_ever(monkeypatch):
    """It will never come right by waiting, and a loop that keeps trying looks
    like a network fault."""
    said: list[str] = []

    class Refusing:
        def open_socket(self):
            raise SlackError("apps.connections.open: invalid_auth")

    mode = SocketMode(Refusing(), lambda e: None, announce=said.append)
    mode.run()                                    # returns rather than looping

    assert any("refused" in line for line in said)


# --------------------------------------------------------------------------- #
# the buttons
# --------------------------------------------------------------------------- #


def test_the_menu_fits_slack_block_limits():
    blocks = ui.main_menu(busy=False, mode="plan", rules=11,
                          model="claude-sonnet-5", body="*Comodor*")

    assert len(blocks) <= 50
    for block in blocks:
        if block["type"] == "actions":
            assert len(block["elements"]) <= 25
            for element in block["elements"]:
                assert len(element["text"]["text"]) <= 75
                assert len(element["action_id"]) <= 255


def test_a_busy_menu_offers_stopping_and_nothing_else():
    blocks = ui.main_menu(busy=True, mode="act")
    keys = [e["action_id"] for b in blocks if b["type"] == "actions"
            for e in b["elements"]]

    assert keys == ["stop"]


def test_the_widest_commitment_is_not_the_first_button():
    rows = [b for b in ui.permission("r1", "npm test")
            if b["type"] == "actions"]
    labels = [e["text"]["text"] for e in rows[0]["elements"]]

    assert "once" in labels[0].lower()
    assert "session" in labels[1].lower()


def test_a_page_of_a_long_list_has_its_arrows():
    items = [(str(n), f"skill-{n}") for n in range(40)]
    blocks = ui.page("skill", items, body="*Skills*", page_number=2)
    labels = [e["text"]["text"] for b in blocks if b["type"] == "actions"
              for e in b["elements"]]

    assert any("Previous" in label for label in labels)
    assert any("Next" in label for label in labels)
    assert any("Back" in label for label in labels)


# --------------------------------------------------------------------------- #
# who it answers, and where
# --------------------------------------------------------------------------- #


class Recorder:
    """Slack, remembered rather than called."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []

    def me(self):
        return {"ok": True, "user": "comodor", "user_id": "UBOT",
                "team": "Acme"}

    def open_dm(self, user):
        return f"D{user}"

    def send(self, channel, text, blocks=None, thread=""):
        self.sent.append({"channel": channel, "text": text,
                          "blocks": blocks or [], "thread": thread})
        return {"ok": True, "ts": f"1.{len(self.sent)}"}

    def edit(self, channel, ts, text, blocks=None):
        self.edits.append({"text": text, "blocks": blocks or []})
        return {"ok": True}


class Pretend:
    cursor = 0

    def __init__(self, cfg):
        self.config = cfg

    def state(self):
        return {"busy": False, "mode": "plan", "provider": "openai",
                "model": "gpt-4o", "project": "/w",
                "context": {"used": 10, "limit": 100},
                "usage": {"cost": 0.25}}

    def chats(self, query="", limit=40):
        return [{"id": f"s{n}", "title": f"chat {n}", "messages": n,
                 "current": n == 0} for n in range(9)]

    def open_chat(self, session_id):
        return True, f"Opened {session_id}", []

    def models_for(self, provider, refresh=False):
        return {"models": [{"id": f"model-{n}"} for n in range(9)]}

    def setting(self, key, value):
        return True, f"{key} is now {value}"

    def skill_shelf(self, refresh=False):
        return {"skills": [{"id": f"skill-{n}", "installed": n == 0}
                           for n in range(9)], "error": ""}

    def skill(self, action, name):
        return True, f"{name} {action}ed"

    def rules(self):
        return {"rules": [{"statement": "Use double quotes."}], "active": 1}

    def folder(self):
        return {"current": "/w", "confined": True}

    def set_mode(self, mode):
        return True

    def send(self, text):
        return False          # nothing is started; the tests are about routing

    def wait_for(self, cursor, timeout=8.0):
        return []

    def interrupt(self):
        pass

    def close(self):
        pass


@pytest.fixture
def talking(config, monkeypatch):
    from comodor.slack.bot import Service

    monkeypatch.setattr("comodor.web.session.Session", Pretend)
    made = Service(config, slack=Recorder(), announce=lambda line: None)
    made.me = "UBOT"
    return made


def dm(user: str = "U0000001", text: str = "", channel: str = "D1"):
    return {"type": "message", "user": user, "channel": channel,
            "channel_type": "im", "text": text, "ts": "1.0"}


def test_a_stranger_in_the_workspace_is_ignored(talking):
    """A workspace can have hundreds of people in it."""
    talking._on_event(dm(user="U9999999", text="hello"))
    talking._on_event(dm(user="U9999999", text="/start"))

    assert talking.slack.sent == []


def test_its_own_messages_are_not_answered(talking):
    """A bot that replies to itself is a loop with a rate limit on it."""
    talking._on_event({"type": "message", "user": "UBOT", "channel": "D1",
                       "channel_type": "im", "text": "hello"})
    talking._on_event({"type": "message", "bot_id": "B1", "channel": "D1",
                       "channel_type": "im", "text": "hello"})

    assert talking.slack.sent == []


def test_in_a_channel_it_answers_only_when_spoken_to(talking):
    """A bot that answers everything in a shared channel is a bot somebody
    removes that afternoon."""
    talking._on_event({"type": "message", "user": "U0000001",
                       "channel": "C1", "channel_type": "channel",
                       "text": "morning everyone", "ts": "1.0"})
    assert talking.slack.sent == []

    talking._on_event({"type": "app_mention", "user": "U0000001",
                       "channel": "C1", "channel_type": "channel",
                       "text": "<@UBOT> status", "ts": "1.0"})
    assert talking.slack.sent


def test_a_channel_answer_stays_in_its_thread(talking):
    """Otherwise a question asked in a thread is answered in the channel, in
    front of everybody, out of context."""
    talking._on_event({"type": "app_mention", "user": "U0000001",
                       "channel": "C1", "channel_type": "channel",
                       "text": "<@UBOT>", "ts": "1.0",
                       "thread_ts": "0.9"})

    assert talking.slack.sent[-1]["thread"] == "0.9"


def test_a_direct_message_is_not_forced_into_a_thread(talking):
    talking._on_event(dm(text=""))

    assert talking.slack.sent[-1]["thread"] == ""


def test_every_button_does_something(talking):
    talking._on_event(dm(text=""))
    first = talking.slack.sent[-1]

    def keys(sent):
        return [e["action_id"] for b in sent["blocks"]
                if b["type"] == "actions" for e in b["elements"]]

    assert len(keys(first)) >= 8

    skip = {"stop", "new", "ok", "okall", "no", "q", "qw", "qs"}
    seen: set[str] = set()
    queue = list(keys(first))
    dead: list[str] = []

    while queue:
        action = queue.pop(0)
        if action in seen or action.split(":")[0] in skip:
            continue
        seen.add(action)
        before = len(talking.slack.sent)
        talking._on_tap(talking._conversation("U0000001"), action)
        replies = talking.slack.sent[before:]
        if not replies:
            dead.append(action)
            continue
        queue.extend(keys(replies[-1]))

    assert dead == [], f"buttons with nothing behind them: {dead}"
    assert len(seen) > 15


def test_a_stale_row_says_so_rather_than_guessing(talking):
    talking._on_event(dm(text=""))
    talking._on_tap(talking._conversation("U0000001"), "model:99")

    assert "moved on" in talking.slack.sent[-1]["text"]


def test_slack_cannot_widen_its_own_permissions(talking):
    talking._on_event(dm(text=""))
    talking._on_tap(talking._conversation("U0000001"), "mode:act")

    said = " ".join(s["text"] for s in talking.slack.sent)
    assert "comodor slack writes on" in said


def test_a_project_may_not_add_itself_to_the_list():
    from comodor.config import project_filtered

    kept, refused = project_filtered({
        "slack": {"allowed": ["U9999999"], "allow_writes": True}})

    assert "slack" not in kept
    assert "slack" in refused
