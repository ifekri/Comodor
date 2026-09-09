"""A permission prompt, from the tool that needs it to the client that answers.

End to end over the real transport: a scripted provider asks for a write, the
engine stops and asks the person, the prompt crosses the wire as JSON, a reply
comes back, and the turn ends in the state that decision implies.

This is the path where a client and the core have to agree exactly, because a
misunderstanding is one of two failures and both are bad: a tool that runs when
it should not have, or a turn that hangs waiting for an answer already given.
So it is driven through `Server` and `Channel` rather than by calling the
service directly, and the provider is scripted rather than mocked, and the tool
that asks is the real `write_file`.

Nothing here sleeps on a duration. A prompt nobody answers is arranged with a
zero timeout — which is a claim, not a race — and everything else waits on a
condition that says what arrived.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any, Callable

import pytest

from comodor import protocol as P
from comodor.agent import AgentLoop, Conversation
from comodor.application import Assembly, CoreService
from comodor.events import EventBus
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry
from comodor.transport.jsonl import Channel
from comodor.transport.server import Server

PATIENCE = 20.0


# --------------------------------------------------------------------------- #
# a wire, in memory
# --------------------------------------------------------------------------- #

class Feeder:
    """The client's end of the pipe: lines in, on demand."""

    def __init__(self) -> None:
        self._lines: "queue.Queue[str | None]" = queue.Queue()

    def send(self, method: str, params: dict[str, Any] | None = None,
             id: str | None = None) -> str:
        wanted = id or f"{method}-{time.monotonic_ns()}"
        self._lines.put(json.dumps(P.request(wanted, method, params)))
        return wanted

    def close(self) -> None:
        self._lines.put(None)

    def __iter__(self):
        while True:
            line = self._lines.get(timeout=PATIENCE)
            if line is None:
                return
            yield line


class Collector:
    """The client's other end: every message the core wrote, as it arrives."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self._arrived = threading.Condition()

    def write(self, text: str) -> int:
        for line in text.splitlines():
            if not line.strip():
                continue
            with self._arrived:
                self.messages.append(json.loads(line))
                self._arrived.notify_all()
        return len(text)

    def flush(self) -> None:
        pass

    def wait_for(self, matches: Callable[[dict[str, Any]], bool],
                 what: str = "") -> dict[str, Any]:
        deadline = time.monotonic() + PATIENCE
        with self._arrived:
            while True:
                found = next((message for message in self.messages
                              if matches(message)), None)
                if found is not None:
                    return found
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    seen = [message.get("event") or message.get("type")
                            for message in self.messages]
                    raise AssertionError(
                        f"nothing matching {what or 'the predicate'}; saw {seen}")
                self._arrived.wait(timeout=remaining)

    def event(self, name: str) -> dict[str, Any]:
        return self.wait_for(
            lambda message: message.get("type") == "event"
            and message.get("event") == name, name)

    def events(self, name: str) -> list[dict[str, Any]]:
        return [message for message in self.messages
                if message.get("type") == "event" and message.get("event") == name]

    def answer_to(self, id: str) -> dict[str, Any]:
        return self.wait_for(
            lambda message: message.get("id") == id
            and message.get("type") in ("response", "error"), f"a reply to {id}")


def build_wire(config, capabilities: tuple[str, ...] = ("questions",
                                                        "permissions")):
    """A real core on a real transport, with a provider that asks for a write.

    Auto-approval is off, because a prompt that answers itself tests nothing.
    """
    config.safety.auto_approve_safe = False
    config.safety.auto_approve_writes = False
    config.safety.auto_approve_shell = False
    config.agent.mode = "act"

    scripts = [
        Script(text="Writing the file.", tool_calls=[ToolCall(
            id="c1", name="write_file",
            arguments={"path": "out.txt", "content": "hello"})]),
        Script(text="Done."),
    ]
    built: dict[str, Any] = {}

    def assemble(built_config, *, bus=None, plugins=None,
                 delegates=False) -> Assembly:
        # `delegates` is accepted and ignored: this assembly is a scripted
        # minimum, with no spawner a delegate manager could run on.
        bus = bus or EventBus()
        permissions = PermissionEngine(built_config, bus)
        agent = AgentLoop(built_config, Gateway(built_config, scripts=scripts),
                          ToolRegistry(config=built_config), bus, permissions,
                          Conversation())
        built["permissions"] = permissions
        return Assembly(config=built_config, bus=bus, gateway=None, memory=None,
                        permissions=permissions, skills=None, mcp=None,
                        tools=agent.tools, agent=agent)

    service = CoreService(config, assemble_with=assemble)
    feeder = Feeder()
    collector = Collector()
    server = Server(service, Channel(reader=feeder, writer=collector,
                                     log=None))
    serving = threading.Thread(target=server.serve, daemon=True)
    serving.start()

    handshake = feeder.send("client.hello", {
        "protocol_version": P.PROTOCOL_VERSION,
        "client": {"name": "permission-test", "version": "0"},
        "capabilities": list(capabilities)})
    hello = collector.answer_to(handshake)
    assert hello["type"] == "response", hello
    created = feeder.send("session.create")
    session = collector.answer_to(created)["result"]["session"]["id"]

    class Wire:
        pass

    made = Wire()
    made.service = service
    made.server = server
    made.feeder = feeder
    made.collector = collector
    made.serving = serving
    made.session = session
    made.permissions = built["permissions"]
    made.target = config.paths.project / "out.txt"
    return made


def shut(made) -> None:
    made.feeder.close()
    made.serving.join(timeout=PATIENCE)
    made.service.close()


@pytest.fixture
def wire(config):
    made = build_wire(config)
    yield made
    shut(made)


def start_turn(wire) -> None:
    wire.feeder.send("session.send",
                     {"session_id": wire.session, "text": "write the file"})


def asked(wire) -> dict[str, Any]:
    return wire.collector.event("permission.requested")["params"]


def settled(wire) -> None:
    """Wait for the turn to end, on the wire's own say-so.

    `permission.resolved` and the first `message.completed` both arrive while
    the turn is still running — one before the tool has done anything, the
    other before it has been called. Asserting on the file, or on `busy`, at
    either point is a race the test would win or lose by luck.
    """
    wire.collector.wait_for(
        lambda message: message.get("event") == "session.updated"
        and message["params"]["session"]["busy"] is False,
        "the turn ending")


def written(wire) -> None:
    """Wait until the write a decision allowed has actually happened."""
    wire.collector.event("tool.completed")
    settled(wire)


# --------------------------------------------------------------------------- #
# the two decisions
# --------------------------------------------------------------------------- #

def test_a_denied_write_never_happens_and_the_turn_says_so(wire):
    start_turn(wire)
    prompt = asked(wire)
    assert prompt["tool"] == "write_file"
    assert prompt["risk"] == "write"
    assert prompt["options"] == ["allow", "allow_always", "deny"]
    assert not wire.target.exists(), "it must not have run yet"

    reply = wire.feeder.send("permission.reply",
                             {"id": prompt["id"], "choice": "deny"})
    assert wire.collector.answer_to(reply)["type"] == "response"

    resolved = wire.collector.event("permission.resolved")["params"]
    assert resolved["id"] == prompt["id"]
    assert resolved["choice"] == "deny"

    failed = wire.collector.event("tool.failed")["params"]
    assert failed["call_id"] == "c1"
    assert not wire.target.exists(), "a denied write wrote something"

    # The turn still finishes, and says what it ended up doing.
    settled(wire)
    assert wire.service.session(wire.session).busy is False
    statuses = [event["params"]["status"]
                for event in wire.collector.events("message.completed")]
    assert statuses and all(status in ("completed", "cancelled")
                            for status in statuses)


def test_an_allowed_write_happens_and_the_turn_completes(wire):
    start_turn(wire)
    prompt = asked(wire)

    wire.feeder.send("permission.reply", {"id": prompt["id"], "choice": "allow"})
    resolved = wire.collector.event("permission.resolved")["params"]
    assert resolved["choice"] == "allow"

    written(wire)
    done = [event["params"]
            for event in wire.collector.events("tool.completed")]
    assert done and done[0]["call_id"] == "c1"
    assert wire.target.exists(), "an allowed write did not write"
    assert wire.target.read_text(encoding="utf-8") == "hello"


def test_allow_always_is_a_real_decision_the_core_remembers(wire):
    """Not a UI invention: the engine keeps a session grant for it."""
    start_turn(wire)
    prompt = asked(wire)

    wire.feeder.send("permission.reply",
                     {"id": prompt["id"], "choice": "allow_always"})
    assert wire.collector.event("permission.resolved")["params"]["choice"] \
        == "allow_always"

    written(wire)
    assert wire.target.exists()
    assert wire.permissions.grants, "the session grant was not recorded"


# --------------------------------------------------------------------------- #
# the paths where nobody, or nobody in time, answers
# --------------------------------------------------------------------------- #

def test_a_prompt_nobody_answers_resolves_itself_on_the_wire(wire):
    """The client is told, so the card it is showing stops being actionable."""
    wire.permissions.prompt_timeout = 0.0
    start_turn(wire)

    prompt = asked(wire)
    resolved = wire.collector.event("permission.resolved")["params"]
    assert resolved["id"] == prompt["id"]
    assert resolved["choice"] == "deny"
    assert not wire.target.exists()

    # And a snapshot taken afterwards carries nothing to answer.
    asked_for = wire.feeder.send("session.snapshot",
                                 {"session_id": wire.session})
    snapshot = wire.collector.answer_to(asked_for)["result"]["snapshot"]
    assert "permission" not in snapshot
    assert not snapshot.get("interactions")


def test_a_reply_that_arrives_after_the_timeout_is_refused(wire):
    """Refused, not accepted: the core already acted on the denial."""
    wire.permissions.prompt_timeout = 0.0
    start_turn(wire)
    prompt = asked(wire)
    wire.collector.event("permission.resolved")

    late = wire.feeder.send("permission.reply",
                            {"id": prompt["id"], "choice": "allow"})
    answer = wire.collector.answer_to(late)
    assert answer["type"] == "error"
    assert answer["error"]["code"] == P.UNKNOWN_REQUEST
    assert not wire.target.exists(), "a late allow ran the tool"


def test_a_second_reply_to_the_same_prompt_is_refused(wire):
    """One decision per request, however many keys were pressed."""
    start_turn(wire)
    prompt = asked(wire)

    first = wire.feeder.send("permission.reply",
                             {"id": prompt["id"], "choice": "allow"})
    assert wire.collector.answer_to(first)["type"] == "response"
    second = wire.feeder.send("permission.reply",
                              {"id": prompt["id"], "choice": "deny"})
    answer = wire.collector.answer_to(second)
    assert answer["type"] == "error"
    assert answer["error"]["code"] == P.UNKNOWN_REQUEST
    assert len(wire.collector.events("permission.resolved")) == 1


def test_a_choice_the_core_does_not_offer_is_refused(wire):
    """The options are the core's, and the reply is checked against them."""
    start_turn(wire)
    prompt = asked(wire)

    reply = wire.feeder.send("permission.reply",
                             {"id": prompt["id"], "choice": "allow_every_time"})
    answer = wire.collector.answer_to(reply)
    assert answer["type"] == "error"
    assert answer["error"]["code"] == P.NOT_ALLOWED
    assert not wire.target.exists()

    # The prompt is still waiting: a bad reply is not a decision.
    snapshot_id = wire.feeder.send("session.snapshot",
                                   {"session_id": wire.session})
    snapshot = wire.collector.answer_to(snapshot_id)["result"]["snapshot"]
    assert snapshot["permission"]["id"] == prompt["id"]


def test_cancelling_over_the_wire_releases_the_prompt(wire):
    """Stop means stop, including when the turn is parked on a person."""
    start_turn(wire)
    prompt = asked(wire)

    cancelled = wire.feeder.send("session.cancel", {"session_id": wire.session})
    assert wire.collector.answer_to(cancelled)["result"]["cancelled"] is True

    resolved = wire.collector.event("permission.resolved")["params"]
    assert resolved["id"] == prompt["id"]
    assert resolved["choice"] == "deny"
    assert not wire.target.exists()


# --------------------------------------------------------------------------- #
# rebuilding a client that missed the prompt
# --------------------------------------------------------------------------- #

def test_a_client_that_remounts_can_still_answer_the_prompt(wire):
    """The case F2 could carry but not complete.

    A prompt raised before this client existed has to be answerable by it, or
    the agent waits out its timeout on a decision the person was never shown.
    """
    start_turn(wire)
    prompt = asked(wire)

    asked_for = wire.feeder.send("session.snapshot",
                                 {"session_id": wire.session})
    snapshot = wire.collector.answer_to(asked_for)["result"]["snapshot"]
    waiting = snapshot["interactions"]
    assert [entry["kind"] for entry in waiting] == ["permission"]
    restored = waiting[0]["permission"]
    assert restored["id"] == prompt["id"]
    assert restored["tool"] == "write_file"
    assert restored["risk"] == "write"
    assert restored["options"] == prompt["options"]

    # Answered from the rebuilt client, and the turn goes on.
    reply = wire.feeder.send("permission.reply",
                             {"id": restored["id"], "choice": "allow"})
    assert wire.collector.answer_to(reply)["type"] == "response"
    assert wire.collector.event("permission.resolved")["params"]["choice"] \
        == "allow"
    written(wire)
    assert wire.target.exists()


def test_a_resolved_prompt_is_not_restored_by_a_snapshot(wire):
    start_turn(wire)
    prompt = asked(wire)
    wire.feeder.send("permission.reply", {"id": prompt["id"], "choice": "deny"})
    wire.collector.event("permission.resolved")

    asked_for = wire.feeder.send("session.snapshot",
                                 {"session_id": wire.session})
    snapshot = wire.collector.answer_to(asked_for)["result"]["snapshot"]
    assert "permission" not in snapshot
    assert not snapshot.get("interactions"), "a stale card would be restored"


def test_no_credential_crosses_the_wire_in_a_prompt(wire, config):
    start_turn(wire)
    prompt = asked(wire)

    body = json.dumps(prompt)
    for forbidden in ("api_key", "apiKey", "providers", "ANTHROPIC",
                      "Authorization", "Bearer"):
        assert forbidden not in body, f"{forbidden} reached a client"
    for entry in config.providers.values():
        if entry.api_key:
            assert entry.api_key not in body


# --------------------------------------------------------------------------- #
# a client that cannot answer
# --------------------------------------------------------------------------- #

def test_a_client_that_cannot_draw_a_permission_is_denied_at_once(config):
    """An unannounced capability is answered by the core, not waited on.

    Sending a prompt to a client that never said it could draw one leaves the
    tool blocked for the whole prompt timeout on an answer nobody can give,
    which reads to a person as the agent having hung. Refusing at once is the
    safe direction: an unanswered permission is never an approval.
    """
    made = build_wire(config, capabilities=())
    try:
        made.feeder.send("session.send",
                         {"session_id": made.session, "text": "write the file"})

        settled(made)
        assert not made.target.exists(), \
            "a client that cannot answer must not end up authorising the write"
        # The core resolved it on the client's behalf rather than waiting.
        assert made.collector.events("permission.resolved"), \
            "the refusal was never reported"
        assert not made.collector.events("permission.requested"), \
            "a prompt was sent to a client that said it could not draw one"
        assert made.service.session(made.session).busy is False
    finally:
        shut(made)
