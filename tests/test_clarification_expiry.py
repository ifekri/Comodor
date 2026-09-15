"""Expiry is observable, and it is not an answer (T045; FR-027).

When a form's wait runs out, `bus.resolve` publishes `REQUEST_EXPIRED`, the
application relays `question.resolved` so no client keeps showing a decision
already taken, the snapshot no longer carries the form — and the run reports
`clarification_required` with `outcome: expired`, with the decision still
open. No timing: the wait is set to zero.
"""

from __future__ import annotations

import threading

from comodor.agent.evidence import EvidenceState as S
from comodor.application import CoreService
from comodor.events import EventBus, Kind
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.tools import ask as ask_tool

REQUEST = "Which database, SQLite or PostgreSQL?"


def a_question():
    return ToolCall(id="q1", name="ask", arguments={"questions": [{
        "question": "Which database?", "header": "Database", "affects": ["architecture"],
        "options": [{"label": "SQLite", "source": "request", "evidence": "SQLite"},
                    {"label": "PostgreSQL", "source": "request", "evidence": "PostgreSQL"}],
    }]})


def test_expiry_publishes_its_event_and_the_decision_stays_open(config, monkeypatch):
    monkeypatch.setattr(ask_tool, "WAIT_FOR", 0.0)
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append(e.kind) if e.kind in (
        Kind.REQUEST, Kind.REQUEST_EXPIRED) else None)
    from comodor.agent import AgentLoop, Conversation
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry

    agent = AgentLoop(config, Gateway(config, scripts=[
        Script(text="Asking.", tool_calls=[a_question()]), Script(text="never")]),
        ToolRegistry(), bus, PermissionEngine(config, bus), Conversation())
    result = agent.run(REQUEST)

    assert seen == [Kind.REQUEST, Kind.REQUEST_EXPIRED]
    assert result.stopped == "clarification_required"
    assert result.clarification["outcome"] == "expired"
    decision = agent.tool_context.evidence.decisions[0]
    assert decision.state == "unresolved" and decision.answer == ""
    assert agent.tool_context.evidence.get(decision.entry_id).state is S.UNRESOLVED


def test_no_client_is_left_with_a_live_card_after_expiry(config, monkeypatch):
    monkeypatch.setattr(ask_tool, "WAIT_FOR", 0.0)
    service = CoreService(config)
    try:
        session = service.create_session()["id"]
        handle = service.session(session)
        handle.assembly.agent.gateway = Gateway(config, scripts=[
            Script(text="Asking.", tool_calls=[a_question()]), Script(text="never")])
        events = []
        service.on_event = lambda _s, name, params, _q: events.append((name, params))

        worker = threading.Thread(target=lambda: handle.assembly.agent.run(REQUEST),
                                  daemon=True)
        worker.start()
        worker.join(10.0)
        assert not worker.is_alive()

        names = [name for name, _ in events]
        assert "question.requested" in names
        assert "question.resolved" in names
        resolved = next(params for name, params in events if name == "question.resolved")
        assert resolved.get("cancelled") is True
        assert "answers" not in resolved
        assert "question" not in service.snapshot(session)
        assert "interactions" not in service.snapshot(session)
        assert not handle._pending
    finally:
        service.close()


def test_a_reply_after_expiry_is_refused(config, monkeypatch):
    from comodor.application import UnknownRequest

    monkeypatch.setattr(ask_tool, "WAIT_FOR", 0.0)
    service = CoreService(config)
    try:
        session = service.create_session()["id"]
        handle = service.session(session)
        handle.assembly.agent.gateway = Gateway(config, scripts=[
            Script(text="Asking.", tool_calls=[a_question()]), Script(text="never")])
        seen = []
        service.on_event = lambda _s, name, params, _q: (
            seen.append(params) if name == "question.requested" else None)
        worker = threading.Thread(target=lambda: handle.assembly.agent.run(REQUEST),
                                  daemon=True)
        worker.start()
        worker.join(10.0)
        assert seen
        try:
            service.answer_question(seen[0]["id"], answers=[
                {"header": "Database", "chosen": ["SQLite"]}])
        except UnknownRequest:
            pass
        else:
            raise AssertionError("a late reply was accepted")
    finally:
        service.close()
