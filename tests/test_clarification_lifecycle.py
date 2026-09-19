"""The full clarification lifecycle at the transport layer (T042; FR-018,
FR-019, FR-022, FR-024, FR-025, FR-026, SC-010).

Eight cases, each asserted on what the turn reports: answered, unanswered,
explicit cancellation, explicit decline, expiry, unattended, a stale answer
and a duplicate answer. The three non-answer endings all yield
`stopped == "clarification_required"` told apart by `clarification.outcome`;
turn cancellation alone yields `stopped == "cancelled"`; and none of the
seven non-answer cases resolves a material decision. No timing anywhere:
every wait is a controlled event, and duplicates resolve through the claim.
"""

from __future__ import annotations

import json
import threading

import pytest

from comodor import questions as forms
from comodor.agent import AgentLoop, Conversation
from comodor.agent.evidence import EvidenceState as S
from comodor.events import EventBus, Kind
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry
from comodor.tools import ask as ask_tool

REQUEST = "Which database should this use: SQLite or PostgreSQL? Then write db.py."


def a_question(call_id="q1"):
    return ToolCall(id=call_id, name="ask", arguments={"questions": [{
        "question": "Which database should this use?", "header": "Database",
        "affects": ["architecture"],
        "options": [{"label": "SQLite", "source": "request", "evidence": "SQLite"},
                    {"label": "PostgreSQL", "source": "request", "evidence": "PostgreSQL"}],
    }]})


def a_write():
    return ToolCall(id="w1", name="write_file",
                    arguments={"path": "db.py", "content": "ENGINE = 'sqlite'\n"})


def make_agent(config, bus, scripts):
    gateway = Gateway(config, scripts=scripts)
    return AgentLoop(config, gateway, ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation())


def scripts_that_ask_then_write():
    return [Script(text="One question first.", tool_calls=[a_question()]),
            Script(text="Writing.", tool_calls=[a_write()]),
            Script(text="Done: db.py uses SQLite.")]


def answered_with(chosen=None, written=""):
    return json.dumps([{"header": "Database", "prompt": "", "chosen": chosen or [],
                        "written": written}])


class Answerer:
    """Replies to the form the way the case needs, on the emitting thread."""

    def __init__(self, bus, reply):
        self.reply = reply
        self.requests = []
        bus.subscribe(self)

    def __call__(self, event):
        if event.kind is Kind.REQUEST:
            request = event.payload["request"]
            self.requests.append(request)
            if self.reply is not None:
                request.answer(self.reply)


# --------------------------------------------------------------------------- #
# the eight cases
# --------------------------------------------------------------------------- #


def test_1_answered_resolves_the_decision_and_dependent_work_runs(config, bus):
    Answerer(bus, answered_with(["SQLite"]))
    agent = make_agent(config, bus, scripts_that_ask_then_write())
    result = agent.run(REQUEST)

    assert result.stopped == "done" and result.ok
    assert result.clarification is None
    assert (config.paths.project / "db.py").exists()
    decision = agent.tool_context.evidence.decisions[0]
    assert decision.state == "answered" and decision.answer == "SQLite"
    assert agent.tool_context.evidence.get(decision.entry_id).state is S.KNOWN


def test_2_unanswered_form_sent_blank_leaves_the_decision_open(config, bus):
    Answerer(bus, answered_with([]))
    agent = make_agent(config, bus, scripts_that_ask_then_write())
    result = agent.run(REQUEST)

    assert result.stopped == "clarification_required" and not result.ok
    assert result.clarification["outcome"] == "cancelled"
    assert not (config.paths.project / "db.py").exists()
    assert agent.tool_context.evidence.get(
        agent.tool_context.evidence.decisions[0].entry_id).state is S.UNRESOLVED


def test_3_explicit_cancellation_is_clarification_required_not_a_cancelled_turn(config, bus):
    Answerer(bus, forms.CANCELLED)
    agent = make_agent(config, bus, scripts_that_ask_then_write())
    result = agent.run(REQUEST)

    assert result.stopped == "clarification_required"
    assert result.stopped != "cancelled"
    assert result.cancel_reason == ""
    assert result.clarification["outcome"] == "cancelled"
    assert result.clarification["decision"] == "Which database should this use?"
    assert not (config.paths.project / "db.py").exists()
    assert result.steps == 1 and result.tool_calls == 1, "partial work still reported"


def test_4_explicit_decline_is_the_same_lifecycle_outcome_as_cancellation(config, bus):
    Answerer(bus, "deny")
    agent = make_agent(config, bus, scripts_that_ask_then_write())
    result = agent.run(REQUEST)
    assert result.stopped == "clarification_required"
    assert result.clarification["outcome"] == "cancelled"
    assert not (config.paths.project / "db.py").exists()


def test_5_expiry_is_told_apart_from_cancellation(config, bus, monkeypatch):
    monkeypatch.setattr(ask_tool, "WAIT_FOR", 0.0)
    expired = []
    bus.subscribe(lambda e: expired.append(e) if e.kind is Kind.REQUEST_EXPIRED else None)
    Answerer(bus, None)                       # listening, never answering
    agent = make_agent(config, bus, scripts_that_ask_then_write())
    result = agent.run(REQUEST)

    assert result.stopped == "clarification_required"
    assert result.clarification["outcome"] == "expired"
    assert expired, "expiry was published"
    assert not (config.paths.project / "db.py").exists()
    assert agent.tool_context.evidence.get(
        agent.tool_context.evidence.decisions[0].entry_id).state is S.UNRESOLVED


def test_6_unattended_is_blocked_and_reported_as_such(config):
    bus = EventBus()                          # nobody listening at all
    agent = make_agent(config, bus, scripts_that_ask_then_write())
    result = agent.run(REQUEST)

    assert result.stopped == "clarification_required"
    assert result.clarification["outcome"] == "unattended"
    assert not (config.paths.project / "db.py").exists()
    assert agent.tool_context.evidence.get(
        agent.tool_context.evidence.decisions[0].entry_id).state is S.BLOCKED


def test_7_a_stale_answer_is_ignored_and_applied_to_nothing(config, bus):
    answerer = Answerer(bus, forms.CANCELLED)
    agent = make_agent(config, bus, scripts_that_ask_then_write())
    result = agent.run(REQUEST)
    assert result.stopped == "clarification_required"

    late = answerer.requests[0].answer(answered_with(["SQLite"]))
    assert late is False, "the claim was already taken"
    decision = agent.tool_context.evidence.decisions[0]
    assert decision.state == "unresolved" and decision.answer == ""
    assert not (config.paths.project / "db.py").exists()


def test_8_duplicate_answers_resolve_to_exactly_one_through_the_claim(config, bus):
    """Two replies race on the same request; the claim admits one. No
    timing: both are made before anything reads the result."""
    from comodor.events import Request

    request = Request(id="ask-x", prompt="q", options=[], kind="questions")
    first = request.answer(answered_with(["SQLite"]))
    second = request.answer(answered_with(["PostgreSQL"]))
    assert (first, second) == (True, False)
    assert forms.decode_answers(request.choice)[0].chosen == ["SQLite"]

    # And through the tool: the winner is what the model reads.
    def race(event):
        if event.kind is Kind.REQUEST:
            held = event.payload["request"]
            outcomes = [held.answer(answered_with(["SQLite"])),
                        held.answer(answered_with(["PostgreSQL"]))]
            assert outcomes == [True, False]

    bus.subscribe(race)
    agent = make_agent(config, bus, scripts_that_ask_then_write())
    result = agent.run(REQUEST)
    assert result.ok
    assert agent.tool_context.evidence.decisions[0].answer == "SQLite"


# --------------------------------------------------------------------------- #
# one question is one decision — a native `ask` payload is not imported twice
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("reply", [forms.CANCELLED, "deny", forms.UNATTENDED])
def test_a_native_ask_ending_without_an_answer_records_exactly_one_decision(
        config, bus, reply):
    """`ask` records its decision in this turn's own ledger. The loop must not
    import that same payload again and open a second decision for one
    question (review fix; FR-014, contracts §C2)."""
    Answerer(bus, reply)
    agent = make_agent(config, bus, scripts_that_ask_then_write())
    result = agent.run(REQUEST)

    assert result.stopped == "clarification_required"
    decisions = result.clarification["decisions"]
    assert len(decisions) == 1, "one question is one decision"
    assert decisions[0]["decision"] == "Which database should this use?"
    ledger = agent.tool_context.evidence
    assert [d.what for d in ledger.decisions] == ["Which database should this use?"]


def test_an_unattended_native_ask_records_exactly_one_decision(config):
    """The same cardinality with nobody listening at all (unattended)."""
    bus = EventBus()
    agent = make_agent(config, bus, scripts_that_ask_then_write())
    result = agent.run(REQUEST)

    assert result.stopped == "clarification_required"
    assert result.clarification["outcome"] == "unattended"
    assert len(result.clarification["decisions"]) == 1
    assert [d.what for d in agent.tool_context.evidence.decisions] \
        == ["Which database should this use?"]


def a_two_question_form():
    return ToolCall(id="q1", name="ask", arguments={"questions": [
        {"question": "Which database should this use?", "header": "Database",
         "affects": ["architecture"],
         "options": [{"label": "SQLite", "source": "request", "evidence": "SQLite"},
                     {"label": "PostgreSQL", "source": "request", "evidence": "PostgreSQL"}]},
        {"question": "Should the pool be shared?", "header": "Pool",
         "affects": ["behaviour"],
         "options": [{"label": "Shared", "source": "request", "evidence": "shared"},
                     {"label": "Per-request", "source": "request",
                      "evidence": "per request"}]},
    ]})


def test_a_partially_answered_form_reports_the_open_question_once(config, bus):
    """One material question answered, one left blank: the blank one stays
    open and is reported exactly once (review fix; FR-014, FR-022)."""
    Answerer(bus, json.dumps([
        {"header": "Database", "prompt": "", "chosen": ["SQLite"], "written": ""},
        {"header": "Pool", "prompt": "", "chosen": [], "written": ""},
    ]))
    agent = make_agent(config, bus, [
        Script(text="Two questions.", tool_calls=[a_two_question_form()]),
        Script(text="never")])
    result = agent.run(REQUEST)

    assert result.stopped == "clarification_required"
    assert [d["decision"] for d in result.clarification["decisions"]] \
        == ["Should the pool be shared?"]
    ledger = agent.tool_context.evidence
    assert [d.what for d in ledger.decisions
            if d.material and d.state in ("unresolved", "blocked")] \
        == ["Should the pool be shared?"]


# --------------------------------------------------------------------------- #
# turn cancellation stays what it was
# --------------------------------------------------------------------------- #


def test_turn_cancellation_yields_cancelled_and_never_clarification_required(config, bus):
    agent = make_agent(config, bus, [Script(text="Working.", tool_calls=[a_write()]),
                                     Script(text="never")])

    def stop_on_tool(event):
        if event.kind is Kind.TOOL_START:
            agent.interrupt("stop")

    bus.subscribe(stop_on_tool)
    result = agent.run("write db.py")
    assert result.stopped == "cancelled"
    assert result.cancel_reason == "stop"
    assert result.clarification is None


def test_the_two_cancellations_are_told_apart_by_the_loop_not_by_wording(config, bus, monkeypatch):
    """Mutation check: if the loop reported a dismissed question as a
    cancelled turn, this fails."""
    Answerer(bus, forms.CANCELLED)
    agent = make_agent(config, bus, scripts_that_ask_then_write())
    real = AgentLoop._clarification_outcome

    def mutated(self):
        payload = real(self)
        if payload is not None:
            # The mutation: report it through the turn-level channel.
            raise __import__("comodor.events", fromlist=["Cancelled"]).Cancelled()
        return payload

    monkeypatch.setattr(AgentLoop, "_clarification_outcome", mutated)
    result = agent.run(REQUEST)
    assert result.stopped == "cancelled", "the mutation conflates the two"

    monkeypatch.setattr(AgentLoop, "_clarification_outcome", real)
    Answerer(bus, forms.CANCELLED)
    fresh = make_agent(config, EventBus(), scripts_that_ask_then_write())
    Answerer(fresh.bus, forms.CANCELLED)
    result = fresh.run(REQUEST)
    assert result.stopped == "clarification_required"


# --------------------------------------------------------------------------- #
# invalid answers are rejected, never coerced (FR-026)
# --------------------------------------------------------------------------- #


def test_an_answer_naming_an_unknown_option_is_rejected_at_the_transport(config):
    from comodor.application import CoreService, Refused

    service = CoreService(config)
    try:
        session = service.create_session()["id"]
        handle = service.session(session)
        handle.assembly.agent.gateway = Gateway(config, scripts=scripts_that_ask_then_write())
        seen = []
        service.on_event = lambda _s, name, params, _q: (
            seen.append(params) if name == "question.requested" else None)
        worker = threading.Thread(target=lambda: handle.assembly.agent.run(REQUEST),
                                  daemon=True)
        worker.start()
        ready = threading.Event()
        for _ in range(500):
            if seen:
                break
            ready.wait(0.01)
        assert seen
        with pytest.raises(Refused):
            service.answer_question(seen[0]["id"], answers=[
                {"header": "Database", "chosen": ["MongoDB"]}])
        assert handle._pending, "the form is still waiting"
        service.answer_question(seen[0]["id"], answers=[
            {"header": "Database", "chosen": ["SQLite"]}])
        worker.join(10.0)
        assert not worker.is_alive()
        assert (config.paths.project / "db.py").exists()
    finally:
        service.close()
