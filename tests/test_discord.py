"""Discord: the fourth channel.

Two layers, tested separately. The *gateway* is a protocol with a fixed
handshake — HELLO, IDENTIFY or RESUME, a heartbeat on a clock Discord names —
and a bot that gets one step wrong connects and hears nothing, so the
handshake is checked against a recorded conversation. The *bot* is judgement,
and the tests there are the ones the spec names: an unlisted stranger gets
silence, a listed account gets turns, writes stay off until the terminal says
otherwise.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from comodor.channels import DISCORD
from comodor.discord.api import split
from comodor.net.ws import WebSocketError


@pytest.fixture
def config(tmp_path):
    from comodor.config import load

    return load(str(tmp_path))


# --------------------------------------------------------------------------- #
# the REST layer
# --------------------------------------------------------------------------- #

def test_a_message_discord_would_refuse_is_split():
    long = "word " * 600
    pieces = split(long)
    assert all(len(p) <= 1900 for p in pieces)
    assert " ".join(pieces).replace("\n", " ") .startswith("word")


def test_a_split_never_leaves_an_open_code_fence():
    text = ("```python\n" + "x = 1\n" * 400)      # the fence opens inside
    pieces = split(text)
    for piece in pieces:
        assert piece.count("```") % 2 == 0, (
            "a reader would see everything after this as code")


def test_a_short_message_is_not_split():
    assert split("hello") == ["hello"]


# --------------------------------------------------------------------------- #
# the gateway protocol, against a recorded conversation
# --------------------------------------------------------------------------- #

class FakeSocket:
    """The wire, remembered. Sends come back as a script to replay."""

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.sent: list[str] = []
        self.closed = False

    def send(self, text: str) -> None:
        self.sent.append(text)

    def settimeout(self, seconds: float) -> None:
        pass

    def receive(self) -> str:
        if not self.script:
            raise WebSocketError("the script is exhausted")
        return self.script.pop(0)

    def close(self) -> None:
        self.closed = True


def a_packet(op: int, d: Any, seq: int | None = None,
             t: str | None = None) -> str:
    packet: dict[str, Any] = {"op": op, "d": d}
    if seq is not None:
        packet["s"] = seq
    if t is not None:
        packet["t"] = t
    return json.dumps(packet)


@pytest.fixture
def gateway(config):
    from comodor.discord.gateway import Gateway

    seen: list[dict[str, Any]] = []
    gw = Gateway("tok", seen.append, announce=lambda line: None)
    gw.seen = seen
    return gw


def test_the_first_connection_identifies_with_intents(gateway, monkeypatch):
    from comodor.discord.gateway import INTENTS, OP_DISPATCH, OP_HELLO, OP_IDENTIFY

    socket = FakeSocket([
        a_packet(OP_HELLO, {"heartbeat_interval": 41250}),
        a_packet(OP_DISPATCH, {"session_id": "s1"}, seq=1, t="READY"),
    ])
    import comodor.discord.gateway as gw_module
    monkeypatch.setattr(gw_module, "WebSocket", lambda *a, **k: socket)

    with pytest.raises(WebSocketError):
        gateway._session()

    identify = json.loads(socket.sent[0])
    assert identify["op"] == OP_IDENTIFY
    assert identify["d"]["token"] == "tok"
    assert identify["d"]["intents"] == INTENTS


def test_a_ready_dispatch_names_the_session_and_events_flow(gateway,
                                                            monkeypatch):
    from comodor.discord.gateway import OP_DISPATCH, OP_HELLO

    socket = FakeSocket([
        a_packet(OP_HELLO, {"heartbeat_interval": 41250}),
        a_packet(OP_DISPATCH, {"session_id": "s1"}, seq=1, t="READY"),
        a_packet(OP_DISPATCH, {"content": "hi", "author": {"id": "7"}},
                 seq=2, t="MESSAGE_CREATE"),
    ])
    import comodor.discord.gateway as gw_module
    monkeypatch.setattr(gw_module, "WebSocket", lambda *a, **k: socket)

    with pytest.raises(WebSocketError):
        gateway._session()
    assert gateway._session_id == "s1"
    assert gateway.seen == [{"content": "hi", "author": {"id": "7"}}]


def test_a_reconnect_resumes_rather_than_reidentify(gateway, monkeypatch):
    from comodor.discord.gateway import OP_DISPATCH, OP_HELLO, OP_RESUME

    gateway._session_id = "s1"
    gateway._last_seq = 42
    socket = FakeSocket([
        a_packet(OP_HELLO, {"heartbeat_interval": 41250}),
        a_packet(OP_DISPATCH, {}, seq=43, t="RESUMED"),
    ])
    import comodor.discord.gateway as gw_module
    monkeypatch.setattr(gw_module, "WebSocket", lambda *a, **k: socket)

    with pytest.raises(WebSocketError):
        gateway._session()
    resume = json.loads(socket.sent[0])
    assert resume["op"] == OP_RESUME
    assert resume["d"]["session_id"] == "s1"
    assert resume["d"]["seq"] == 42


def test_an_invalid_session_forgets_the_old_one(gateway, monkeypatch):
    from comodor.discord.gateway import OP_HELLO, OP_INVALID_SESSION

    gateway._session_id = "s1"
    gateway._last_seq = 42
    socket = FakeSocket([
        a_packet(OP_HELLO, {"heartbeat_interval": 41250}),
        a_packet(OP_INVALID_SESSION, False),
    ])
    import comodor.discord.gateway as gw_module
    monkeypatch.setattr(gw_module, "WebSocket", lambda *a, **k: socket)

    with pytest.raises(RuntimeError):
        gateway._session()
    assert gateway._session_id == ""


def test_the_heartbeat_is_sent_when_asked(gateway, monkeypatch):
    from comodor.discord.gateway import OP_HEARTBEAT, OP_HELLO

    socket = FakeSocket([
        a_packet(OP_HELLO, {"heartbeat_interval": 41250}),
        a_packet(OP_HEARTBEAT, None),
    ])
    import comodor.discord.gateway as gw_module
    monkeypatch.setattr(gw_module, "WebSocket", lambda *a, **k: socket)

    with pytest.raises(WebSocketError):
        gateway._session()
    beat = json.loads(socket.sent[-1])
    assert beat["op"] == OP_HEARTBEAT


def test_a_failing_event_handler_does_not_kill_the_socket(gateway,
                                                          monkeypatch):
    from comodor.discord.gateway import OP_DISPATCH, OP_HELLO

    calls = []
    def explode(event: dict[str, Any]) -> None:
        calls.append(event)
        raise ValueError("boom")

    gw = gateway.__class__("tok", explode, announce=lambda line: None)
    socket = FakeSocket([
        a_packet(OP_HELLO, {"heartbeat_interval": 41250}),
        a_packet(OP_DISPATCH, {"content": "one"}, seq=1, t="MESSAGE_CREATE"),
        a_packet(OP_DISPATCH, {"content": "two"}, seq=2, t="MESSAGE_CREATE"),
    ])
    import comodor.discord.gateway as gw_module
    monkeypatch.setattr(gw_module, "WebSocket", lambda *a, **k: socket)

    with pytest.raises(WebSocketError):
        gw._session()
    assert len(calls) == 2, "the second message still arrived"


# --------------------------------------------------------------------------- #
# the bot layer: who is answered, and what they may do
# --------------------------------------------------------------------------- #

@pytest.fixture
def service(config, monkeypatch):
    from comodor.discord.bot import Service

    config.discord.token = "a.b.c"
    config.discord.enabled = True
    config.discord.allowed = [7]

    class Rest:
        def me(self):
            return {"id": "42", "username": "comodor"}

        def send(self, channel, text, reply_to=None):
            return {"id": "100"}

        def edit(self, channel, message, text):
            return {}

        def typing(self, channel):
            pass

    made = Service(config, bot=Rest())
    made.me = "42"
    return made


def a_message(user: int, text: str, guild: str | None = None) -> dict:
    return {"author": {"id": str(user)}, "channel_id": "999",
            "content": text, "guild_id": guild}


def test_a_stranger_in_a_dm_is_met_with_silence(service):
    service._on_message(a_message(999, "hello"))
    assert service.chats == {}


def test_a_stranger_with_the_pairing_code_is_paired(service, config):
    code = service.offer_pairing()
    service._on_message(a_message(999, code))
    assert 999 in config.discord.allowed
    assert "999" in service.chats


def test_an_expired_pairing_code_is_silence(service, config):
    service.offer_pairing()
    service.pairing.until = 0.0
    service._on_message(a_message(999, "123456"))
    assert 999 not in config.discord.allowed


def test_a_server_message_without_a_mention_is_ignored(service):
    service._on_message(a_message(7, "hello", guild="1"))
    assert service.chats == {}


def test_a_mentioned_server_message_starts_a_turn(service, monkeypatch):
    started = []
    monkeypatch.setattr(service, "_start_turn", lambda talk, text:
                        started.append(text))
    service._on_message(a_message(7, "<@42> hello", guild="1"))
    assert started == ["hello"], "the mention itself is not the task"


def test_a_bot_is_never_answered_not_even_itself(service):
    service._on_message(a_message(42, "hello"))          # its own id
    assert service.chats == {}
    service._on_message({"author": {"id": "5", "bot": True},
                         "channel_id": "9", "content": "hi"})
    assert service.chats == {}


def test_writes_are_off_until_somebody_says_otherwise(service, config,
                                                      monkeypatch):
    """A stranger with no pairing offer must not become a turn; a paired
    account starts in plan mode unless the terminal said otherwise."""
    config.discord.allowed = []
    started = []
    monkeypatch.setattr(service, "_start_turn", lambda talk, text:
                        started.append(text))
    service._on_message(a_message(7, "hello"))
    assert started == []

    config.discord.allowed = [7]
    talk = service._conversation("7")
    assert talk.session.state().get("mode") == "plan", \
        "reads and plans only, until the terminal says otherwise"


def test_the_channel_is_listed_as_ready_when_configured(config):
    config.discord.token = "a.b.c"
    config.discord.allowed = [7]
    ok, why = DISCORD.can_run(config)
    assert ok and why == ""

def test_the_channel_is_not_ready_without_pairing(config):
    config.discord.token = "a.b.c"
    ok, why = DISCORD.can_run(config)
    assert not ok and "pair" in why
