"""The clarification-required outcome on the wire (T046–T048; FR-080, SC-023).

Additive and negotiated. A client that advertises `clarification_required`
receives the event with `outcome`; one that does not never receives it and
sees exactly what it saw before — a completed message and a notification.
The form's new fields are optional and carried only when set.
"""

from __future__ import annotations

import json
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


class Feeder:
    def __init__(self) -> None:
        import queue

        self._lines: queue.Queue = queue.Queue()
        self._next = 0

    def send(self, method: str, params: dict | None = None) -> str:
        self._next += 1
        identifier = f"r{self._next}"
        self._lines.put(json.dumps(P.request(identifier, method, params)))
        return identifier

    def close(self) -> None:
        self._lines.put(None)

    def __iter__(self):
        while True:
            line = self._lines.get(timeout=PATIENCE)
            if line is None:
                return
            yield line


class Collector:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self._arrived = threading.Condition()

    def write(self, text: str) -> int:
        for line in text.splitlines():
            if line.strip():
                with self._arrived:
                    self.messages.append(json.loads(line))
                    self._arrived.notify_all()
        return len(text)

    def flush(self) -> None:
        pass

    def wait_for(self, matches: Callable[[dict], bool], what: str = "") -> dict:
        deadline = time.monotonic() + PATIENCE
        with self._arrived:
            while True:
                found = next((m for m in self.messages if matches(m)), None)
                if found is not None:
                    return found
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    seen = [m.get("event") or m.get("type") for m in self.messages]
                    raise AssertionError(f"nothing matching {what}; saw {seen}")
                self._arrived.wait(timeout=remaining)

    def event(self, name: str) -> dict:
        return self.wait_for(lambda m: m.get("type") == "event" and m.get("event") == name, name)

    def events(self, name: str) -> list[dict]:
        return [m for m in self.messages if m.get("type") == "event" and m.get("event") == name]

    def answer_to(self, identifier: str) -> dict:
        return self.wait_for(lambda m: m.get("id") == identifier
                             and m.get("type") in ("response", "error"), identifier)


def a_question():
    return ToolCall(id="q1", name="ask", arguments={"questions": [{
        "question": "Which database?", "header": "Database", "affects": ["architecture"],
        "options": [{"label": "SQLite", "source": "request", "evidence": "SQLite"},
                    {"label": "PostgreSQL", "source": "request", "evidence": "PostgreSQL"}],
    }]})


def build_wire(config, capabilities):
    scripts = [Script(text="Asking.", tool_calls=[a_question()]), Script(text="never")]

    def assemble(built_config, *, bus=None, plugins=None, delegates=False) -> Assembly:
        bus = bus or EventBus()
        permissions = PermissionEngine(built_config, bus)
        agent = AgentLoop(built_config, Gateway(built_config, scripts=scripts),
                          ToolRegistry(config=built_config), bus, permissions,
                          Conversation())
        return Assembly(config=built_config, bus=bus, gateway=None, memory=None,
                        permissions=permissions, skills=None, mcp=None,
                        tools=agent.tools, agent=agent)

    service = CoreService(config, assemble_with=assemble)
    feeder, collector = Feeder(), Collector()
    server = Server(service, Channel(reader=feeder, writer=collector, log=None))
    serving = threading.Thread(target=server.serve, daemon=True)
    serving.start()
    hello = feeder.send("client.hello", {
        "protocol_version": P.PROTOCOL_VERSION,
        "client": {"name": "clarification-test", "version": "0"},
        "capabilities": list(capabilities)})
    reply = collector.answer_to(hello)
    assert reply["type"] == "response", reply
    created = feeder.send("session.create")
    session = collector.answer_to(created)["result"]["session"]["id"]
    return service, feeder, collector, serving, session, reply["result"]


def _settled(collector):
    collector.wait_for(lambda m: m.get("event") == "session.updated"
                       and m["params"]["session"]["busy"] is False, "the turn ending")


def _shut(service, feeder, serving):
    feeder.close()
    serving.join(timeout=PATIENCE)
    service.close()


@pytest.fixture
def negotiating(config):
    made = build_wire(config, ("questions", "permissions", "clarification_required"))
    yield made
    _shut(made[0], made[1], made[3])


@pytest.fixture
def old_client(config):
    made = build_wire(config, ("questions", "permissions"))
    yield made
    _shut(made[0], made[1], made[3])


def test_the_core_advertises_the_capability(negotiating):
    *_, hello = negotiating
    assert "clarification_required" in hello["capabilities"]
    assert "clarification_required" in P.CORE_CAPABILITIES
    assert "clarification_required" in P.CLIENT_CAPABILITIES


def test_a_negotiating_client_receives_the_outcome_with_its_lifecycle(negotiating):
    service, feeder, collector, _, session, _ = negotiating
    feeder.send("session.send", {"session_id": session, "text": "SQLite or PostgreSQL?"})
    asked = collector.event("question.requested")["params"]
    question = asked["questions"][0]
    assert question["reason"] == "architecture"
    assert question["decision_ref"].startswith("d")
    assert question.get("evidence_consulted", []) == []   # nothing was read first
    P.validate("QuestionRequest", asked)

    feeder.send("question.answer", {"id": asked["id"], "cancelled": True})
    required = collector.event("clarification.required")["params"]
    P.validate("ClarificationRequired", required)
    assert required["kind"] == "clarification_required"
    assert required["outcome"] == "cancelled"
    assert required["decision"] == "Which database?"
    assert [c["label"] for c in required["candidates"]] == ["SQLite", "PostgreSQL"]
    assert required["session_id"] == session
    _settled(collector)
    # The turn is not reported as cancelled: no `cancelled` message status.
    statuses = [m["params"]["status"] for m in collector.events("message.completed")]
    assert "cancelled" not in statuses


def test_an_old_client_never_receives_it_and_sees_what_it_saw_before(old_client):
    service, feeder, collector, _, session, hello = old_client
    feeder.send("session.send", {"session_id": session, "text": "SQLite or PostgreSQL?"})
    asked = collector.event("question.requested")["params"]
    feeder.send("question.answer", {"id": asked["id"], "cancelled": True})
    _settled(collector)

    assert collector.events("clarification.required") == []
    assert collector.events("question.resolved")
    completed = collector.events("message.completed")
    assert completed and all(m["params"]["status"] == "completed" for m in completed)
    notes = [m["params"]["text"] for m in collector.events("notification.created")]
    assert any("decision is needed" in text for text in notes), \
        "a plain sentence still says what happened"
    # The sequence has no holes: the unsent event was never numbered.
    seqs = [m["seq"] for m in collector.messages if m.get("type") == "event"]
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))


def test_a_form_without_the_new_fields_validates_as_before():
    P.validate("QuestionRequest", {
        "id": "ask-1", "session_id": "s", "title": "t",
        "questions": [{"header": "h", "prompt": "p", "multiple": False,
                       "options": [{"id": "a", "label": "a"}]}]})


def test_the_outcome_enum_is_exactly_the_three_lifecycle_values():
    import json as _json
    from pathlib import Path

    schema = _json.loads((Path(__file__).resolve().parents[1]
                          / "schemas/protocol/v2.json").read_text(encoding="utf-8"))
    assert schema["$defs"]["ClarificationOutcome"]["enum"] == \
        ["cancelled", "expired", "unattended"]
    assert "answered" not in schema["$defs"]["ClarificationOutcome"]["enum"]


def test_the_relay_never_sends_an_outcome_outside_the_enum(config):
    """The runtime validator is shallow by design, so the relay is the guard:
    a value the enum does not know is left out rather than sent."""
    from comodor.application import _relay_clarification
    from comodor.events import Event, Kind

    service = CoreService(config)
    try:
        session = service.create_session()["id"]
        handle = service.session(session)
        sent = []
        service.on_event = lambda _s, name, params, _q: sent.append((name, params))
        _relay_clarification(service, handle, Event(kind=Kind.TURN_END, payload={
            "stopped": "clarification_required",
            "clarification": {"decision": "d", "candidates": [], "evidence_consulted": [],
                              "reason": "behaviour", "outcome": "answered"}}))
        body = next(params for name, params in sent if name == "clarification.required")
        assert "outcome" not in body
    finally:
        service.close()


def test_the_relay_carries_prior_changes(config):
    """A negotiated protocol client is told what changed before the decision
    became known (contracts §C6)."""
    from comodor.application import _relay_clarification
    from comodor.events import Event, Kind

    service = CoreService(config)
    try:
        session = service.create_session()["id"]
        handle = service.session(session)
        sent = []
        service.on_event = lambda _s, name, params, _q: sent.append((name, params))
        _relay_clarification(service, handle, Event(kind=Kind.TURN_END, payload={
            "stopped": "clarification_required",
            "clarification": {"decision": "d", "candidates": [], "evidence_consulted": [],
                              "reason": "behaviour", "outcome": "cancelled",
                              "prior_changes": ["db.py"]}}))
        body = next(params for name, params in sent if name == "clarification.required")
        assert body["prior_changes"] == ["db.py"]
    finally:
        service.close()
