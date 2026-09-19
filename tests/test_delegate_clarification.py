"""Clarification raised by background work (T054–T058; FR-029, FR-018,
FR-019, FR-022, FR-023).

A delegate asks through the same mechanism as the session's own turn — the
scoped bus, the same form — and the form is attributed to the delegate that
raised it. Its question is never injected into another turn; only the
delegate that asked pauses; and the anti-assumption rules are exactly the
parent's: cancelled, expired or unattended, no value is invented, and the
decision reaches the parent as an open one.
"""

from __future__ import annotations

import threading

import pytest

from comodor import questions as forms
from comodor.agent.background import BackgroundDelegates, completion_turn
from comodor.agent.spawn import DELEGATE_ORIGIN, spawner
from comodor.events import EventBus, Kind
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.tools import ask as ask_tool

BRIEF = "Decide which database, SQLite or PostgreSQL, and write db.py."


def a_question():
    return ToolCall(id="q1", name="ask", arguments={"questions": [{
        "question": "Which database?", "header": "Database", "affects": ["architecture"],
        "options": [{"label": "SQLite", "source": "request", "evidence": "SQLite"},
                    {"label": "PostgreSQL", "source": "request", "evidence": "PostgreSQL"}],
    }]})


def asking_scripts():
    return [Script(text="Asking.", tool_calls=[a_question()]),
            Script(text="Done with SQLite.")]


def _until(condition, tries=800):
    ready = threading.Event()
    for _ in range(tries):
        if condition():
            return
        ready.wait(0.01)
    raise AssertionError("condition never held")


@pytest.fixture
def manager(config):
    config.delegation.max_background = 3
    made = BackgroundDelegates(config)
    yield made
    made.stop_all()
    made.wait(5.0)


def _launch(config, manager, bus, scripts, brief=BRIEF):
    gateway = Gateway(config, scripts=scripts)
    spawn = spawner(config, gateway, bus)
    accepted, identifier, why = manager.start(brief, label="db", write=True,
                                              cwd=config.paths.project, owner="s1",
                                              bus=bus, spawner=spawn)
    assert accepted, why
    return identifier


# --------------------------------------------------------------------------- #
# T054 — the same mechanism, attributed
# --------------------------------------------------------------------------- #


def test_a_delegates_question_reaches_the_bus_through_the_same_form_with_its_origin(
        config, manager):
    bus = EventBus()
    seen = []

    def watch(event):
        if event.kind is Kind.REQUEST and event.payload["request"].kind == "questions":
            seen.append(event)
            event.payload["request"].answer(forms.encode_answers([
                forms.Answer(header="Database", prompt="", chosen=["SQLite"])]))

    bus.subscribe(watch)
    identifier = _launch(config, manager, bus, asking_scripts())
    _until(lambda: manager.take_pending("s1") or manager.listing("s1")[0]["state"] != "running")

    assert len(seen) == 1
    assert seen[0].get("origin") == f"{DELEGATE_ORIGIN}:{identifier}"
    request = seen[0].payload["request"]
    assert request.kind == "questions"
    assert request.meta["questions"][0]["options"][-1]["free"] is True
    record = manager.listing("s1")[0]
    assert record["state"] == "done"


def test_the_origin_is_carried_to_the_client_on_the_question(config):
    from comodor.application import CoreService

    service = CoreService(config)
    try:
        session = service.create_session()["id"]
        seen = []
        service.on_event = lambda _s, name, params, _q: (
            seen.append(params) if name == "question.requested" else None)
        bus = service.session(session).assembly.bus
        from comodor.events import Request

        bus.emit(Kind.REQUEST, origin=f"{DELEGATE_ORIGIN}:d1",
                 request=Request(id="ask-d", prompt="Which?", options=[],
                                 kind="questions", meta={"questions": [
                                     {"header": "h", "prompt": "Which?",
                                      "options": [{"label": "a"}, {"label": "b"}]}]}))
        assert seen and seen[0]["origin"] == "delegate:d1"
    finally:
        service.close()


# --------------------------------------------------------------------------- #
# T055 — never injected into another turn
# --------------------------------------------------------------------------- #


def test_a_delegates_stop_for_a_decision_lands_at_the_turn_boundary_only(config, manager):
    bus = EventBus()                          # nobody answering: unattended
    identifier = _launch(config, manager, bus, asking_scripts())
    _until(lambda: manager.listing("s1")[0]["state"] != "running")

    # Nothing was delivered on its own; the record waits for take_pending.
    record = manager.listing("s1")[0]
    assert record["state"] == "done"
    assert record["clarification"]["outcome"] == "unattended"
    pending = manager.take_pending("s1")
    assert [entry["id"] for entry in pending] == [identifier]
    text = completion_turn(pending[0])
    assert "needs a decision that nobody answered" in text
    assert "Do not decide it yourself" in text
    assert manager.take_pending("s1") == [], "delivered once, at a boundary"


def test_the_parents_turn_carries_the_delegates_decision_as_open(config):
    from comodor.agent import AgentLoop, Conversation
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry

    bus = EventBus()
    agent = AgentLoop(config, Gateway(config, scripts=[
        Script(text="Writing anyway.", tool_calls=[ToolCall(
            id="w", name="write_file", arguments={"path": "db.py", "content": "x"})]),
        Script(text="never")]),
        ToolRegistry(), bus, PermissionEngine(config, bus), Conversation())
    carried = {"kind": "clarification_required", "decision": "Which database?",
               "candidates": [{"label": "SQLite"}], "evidence_consulted": [],
               "reason": "architecture", "outcome": "unattended"}
    result = agent.run(completion_turn({"id": "d1", "state": "done",
                                        "answer": "Stopped: needs a decision",
                                        "clarification": carried}),
                       decisions=[carried])
    assert result.stopped == "clarification_required"
    assert not (config.paths.project / "db.py").exists()
    decision = agent.tool_context.evidence.decisions[0]
    assert decision.what == "Which database?" and decision.state == "blocked"


def test_every_unresolved_delegate_decision_is_carried(config):
    """A delegate can leave several decisions open at once.

    The payload lists them; importing only the top-level first one would drop
    the rest, so the parent would report a single decision where the delegate
    raised two — and the regenerated form would ask one of them.
    """
    from comodor.agent import AgentLoop, Conversation
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry

    bus = EventBus()
    agent = AgentLoop(config, Gateway(config, scripts=[
        Script(text="Writing anyway.", tool_calls=[ToolCall(
            id="w", name="write_file", arguments={"path": "db.py", "content": "x"})]),
        Script(text="never")]),
        ToolRegistry(), bus, PermissionEngine(config, bus), Conversation())
    carried = {
        "kind": "clarification_required", "decision": "Which database?",
        "candidates": [{"label": "SQLite"}], "evidence_consulted": [],
        "reason": "architecture", "outcome": "unattended",
        "decisions": [
            {"id": "d1", "decision": "Which database?",
             "candidates": ["SQLite", "PostgreSQL"], "evidence_consulted": [],
             "reason": "architecture"},
            {"id": "d2", "decision": "Which cache?",
             "candidates": ["Redis"], "evidence_consulted": ["README.md"],
             "reason": "interface_behaviour"},
        ],
    }
    result = agent.run(completion_turn({"id": "d2", "state": "done",
                                        "answer": "Stopped: needs a decision",
                                        "clarification": carried}),
                       decisions=[carried])

    assert result.stopped == "clarification_required"
    whats = [decision.what for decision in agent.tool_context.evidence.decisions]
    assert whats == ["Which database?", "Which cache?"]
    assert [item["decision"] for item in result.clarification["decisions"]] \
        == ["Which database?", "Which cache?"], "the complete set, in stable order"
    assert not (config.paths.project / "db.py").exists()


# --------------------------------------------------------------------------- #
# T056 — only the dependent delegate pauses
# --------------------------------------------------------------------------- #


def test_a_sibling_delegate_continues_while_one_waits_for_an_answer(config, manager):
    bus = EventBus()
    held = []
    bus.subscribe(lambda e: held.append(e.payload["request"])
                  if e.kind is Kind.REQUEST and e.payload["request"].kind == "questions"
                  else None)
    asking = _launch(config, manager, bus, asking_scripts())
    plain = _launch(config, manager, bus, [Script(text="Listed the files.")],
                    brief="list the files")
    _until(lambda: held)
    _until(lambda: any(r["id"] == plain and r["state"] == "done"
                       for r in manager.listing("s1")))

    states = {r["id"]: r["state"] for r in manager.listing("s1")}
    assert states[plain] == "done"
    assert states[asking] == "running", "the asker is paused on its question"
    held[0].answer(forms.CANCELLED)
    _until(lambda: manager.listing("s1")[0]["state"] != "running"
           and all(r["state"] != "running" for r in manager.listing("s1")))


# --------------------------------------------------------------------------- #
# T057 — the anti-assumption rules, for a delegate
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("ending", ["cancelled", "expired", "unattended"])
def test_no_value_is_invented_for_a_delegate_raised_question(config, manager, monkeypatch, ending):
    bus = EventBus()
    if ending == "cancelled":
        bus.subscribe(lambda e: e.payload["request"].answer(forms.CANCELLED)
                      if e.kind is Kind.REQUEST and e.payload["request"].kind == "questions"
                      else None)
    elif ending == "expired":
        monkeypatch.setattr(ask_tool, "WAIT_FOR", 0.0)
        bus.subscribe(lambda e: None)
    _launch(config, manager, bus, asking_scripts())
    _until(lambda: manager.listing("s1")[0]["state"] != "running")

    record = manager.listing("s1")[0]
    assert record["state"] == "done"
    assert record["clarification"]["outcome"] == ending
    assert "no default was chosen" in record["answer"] if "answer" in record else True
    assert not (config.paths.project / "db.py").exists()
    pending = manager.take_pending("s1")
    assert "SQLite it is" not in pending[0]["answer"]
    assert "Done with SQLite" not in pending[0]["answer"]


# --------------------------------------------------------------------------- #
# T058 — cancellation, reconnect, and a crashed delegate
# --------------------------------------------------------------------------- #


def test_cancelling_a_delegates_question_leaves_its_decision_unresolved(config, manager):
    bus = EventBus()
    bus.subscribe(lambda e: e.payload["request"].answer(forms.CANCELLED)
                  if e.kind is Kind.REQUEST and e.payload["request"].kind == "questions"
                  else None)
    _launch(config, manager, bus, asking_scripts())
    _until(lambda: manager.listing("s1")[0]["state"] != "running")
    record = manager.take_pending("s1")[0]
    assert record["clarification"]["outcome"] == "cancelled"
    assert record["clarification"]["decision"] == "Which database?"


def test_a_reconnect_restores_the_delegates_form_with_its_origin(config):
    from comodor.application import CoreService
    from comodor.events import Request

    service = CoreService(config)
    try:
        session = service.create_session()["id"]
        bus = service.session(session).assembly.bus
        bus.emit(Kind.REQUEST, origin=f"{DELEGATE_ORIGIN}:d7",
                 request=Request(id="ask-d7", prompt="Which?", options=[],
                                 kind="questions", meta={"questions": [
                                     {"header": "h", "prompt": "Which?",
                                      "options": [{"label": "a"}, {"label": "b"}]}]}))
        snapshot = service.snapshot(session)
        assert snapshot["question"]["id"] == "ask-d7"
        assert snapshot["question"]["origin"] == "delegate:d7"
    finally:
        service.close()


def test_a_crashed_delegate_is_reported_lost_never_alive(config, tmp_path):
    """The record of a run that was mid-flight when the process died."""
    record_file = tmp_path / "delegates.json"
    manager = BackgroundDelegates(config, persist_path=record_file)
    try:
        bus = EventBus()
        gate = threading.Event()

        def stuck_spawn(**kwargs):
            class Loop:
                def run(self, brief):
                    gate.wait(5.0)
                    from comodor.agent.loop import TurnResult
                    return TurnResult(text="late")
            return Loop()

        accepted, identifier, _ = manager.start("x", owner="s1", bus=bus, spawner=stuck_spawn)
        assert accepted
        _until(lambda: manager.listing("s1")[0]["state"] == "running")
        # A second manager over the same record is the next process.
        reloaded = BackgroundDelegates(config, persist_path=record_file)
        record = next(r for r in reloaded.listing() if r["id"] == identifier)
        assert record["state"] == "lost"
        assert "lost" in completion_turn(record)
        gate.set()
    finally:
        manager.stop_all()
        manager.wait(5.0)


def test_a_carried_decision_the_project_settled_does_not_stop_the_turn(config, monkeypatch):
    """A carried question the ledger can already answer settles: the known
    evidence is applied before the imported decision is opened (FR-008)."""
    from comodor.agent import AgentLoop, Conversation
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry

    bus = EventBus()
    agent = AgentLoop(config, Gateway(config, scripts=[Script(text="Done.")]),
                      ToolRegistry(), bus, PermissionEngine(config, bus), Conversation())

    class Settled:
        id = "lesson-1"
        trigger = "Which database?"
        guidance = "SQLite"

    monkeypatch.setattr(agent, "_settled_decisions", lambda: [Settled()])
    carried = {"kind": "clarification_required", "decision": "Which database?",
               "candidates": [], "evidence_consulted": [],
               "reason": "architecture", "outcome": "unattended"}

    result = agent.run("carry on", decisions=[carried])

    assert result.stopped == "done"
    assert not [d for d in agent.tool_context.evidence.decisions if d.withholds]
    assert all(d.state != "unresolved"
               for d in agent.tool_context.evidence.decisions), \
        "a settled carried decision is not reopened as unresolved"


def test_the_delegate_tool_hands_a_clarification_back(config, bus, tool_context):
    """A synchronous delegate that stops for a decision returns the structured
    payload, so the parent can import it (FR-018, FR-029)."""
    from comodor.agent.loop import TurnResult
    from comodor.tools.delegate import Delegate

    class FakeLoop:
        def run(self, brief):
            result = TurnResult()
            result.stopped = "clarification_required"
            result.text = "Stopped: a decision is needed."
            result.clarification = {"kind": "clarification_required",
                                    "decision": "Which database?",
                                    "candidates": [], "evidence_consulted": [],
                                    "reason": "architecture", "outcome": "unattended"}
            return result

    tool = Delegate(lambda **_: FakeLoop())
    result = tool.run(tool_context, task="look into the schema")

    assert result.ok
    assert result.meta["clarification"]["decision"] == "Which database?"
    assert result.meta["outcome"] == "unattended"


def test_a_delegate_clarification_in_a_tool_result_ends_the_parent_turn(config, bus, monkeypatch):
    from comodor.agent import AgentLoop, Conversation
    from comodor.providers.base import ToolCall
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry
    from comodor.tools.base import ToolResult

    agent = AgentLoop(config, Gateway(config, scripts=[Script(text="done")]),
                      ToolRegistry(), bus, PermissionEngine(config, bus), Conversation())
    context = agent._tool_context()
    call = ToolCall(id="d1", name="delegate", arguments={"task": "x"})
    result = ToolResult.success(
        "Stopped: a decision is needed.",
        clarification={"kind": "clarification_required", "decision": "Which database?",
                       "candidates": [], "evidence_consulted": [],
                       "reason": "architecture", "outcome": "unattended"})
    monkeypatch.setattr(agent, "_run_one", lambda c, ctx: result)

    agent._execute([call])

    assert [d.what for d in context.evidence.decisions] == ["Which database?"]
    assert context.evidence.withheld(), "dependent work is withheld"


def test_applied_delegate_files_are_mutation_evidence(config, bus, monkeypatch):
    from comodor.agent import AgentLoop, Conversation
    from comodor.providers.base import ToolCall
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry
    from comodor.tools.base import ToolResult

    agent = AgentLoop(config, Gateway(config, scripts=[Script(text="done")]),
                      ToolRegistry(), bus, PermissionEngine(config, bus), Conversation())
    call = ToolCall(id="d1", name="delegate", arguments={"task": "x"})
    result = ToolResult.success("applied", applied=True, files=["foo.py"])
    monkeypatch.setattr(agent, "_run_one", lambda c, ctx: result)

    agent._execute([call])

    assert "foo.py" in agent._written_paths


def test_a_delegate_clarification_is_imported_exactly_once(config, bus, monkeypatch):
    """A child's decision enters the parent ledger once. The native-`ask`
    guard added for the duplicate-decision fix must not suppress a genuine
    child import, and the child's payload must not be imported twice."""
    from comodor.agent import AgentLoop, Conversation
    from comodor.providers.base import ToolCall
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry
    from comodor.tools.base import ToolResult

    agent = AgentLoop(config, Gateway(config, scripts=[Script(text="done")]),
                      ToolRegistry(), bus, PermissionEngine(config, bus), Conversation())
    real_invoke = agent.tools.invoke

    def invoke(name, context, arguments):
        if name == "delegate":
            return ToolResult.success(
                "Stopped: a decision is needed.",
                clarification={"kind": "clarification_required",
                               "decision": "Which database?", "candidates": [],
                               "evidence_consulted": [], "reason": "architecture",
                               "outcome": "unattended"})
        return real_invoke(name, context, arguments)

    monkeypatch.setattr(agent.tools, "invoke", invoke)
    agent._execute([ToolCall(id="d1", name="delegate", arguments={"task": "x"})])

    ledger = agent._tool_context().evidence
    assert [d.what for d in ledger.decisions] == ["Which database?"]


def test_a_sibling_write_after_a_delegates_decision_is_withheld_in_the_same_batch(
        config, bus, monkeypatch):
    """A foreground delegate that stops for a decision and a write in the
    same model response: the decision is imported before the write starts,
    so the write is withheld rather than run without the answer (FR-018;
    review 4045928900)."""
    from comodor.agent import AgentLoop, Conversation
    from comodor.providers.base import ToolCall
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry
    from comodor.tools.base import ToolResult

    agent = AgentLoop(config, Gateway(config, scripts=[Script(text="done")]),
                      ToolRegistry(), bus, PermissionEngine(config, bus), Conversation())
    real_invoke = agent.tools.invoke

    def invoke(name, context, arguments):
        if name == "delegate":
            return ToolResult.success(
                "Stopped: a decision is needed.",
                clarification={"kind": "clarification_required",
                               "decision": "Which database?", "candidates": [],
                               "evidence_consulted": [], "reason": "architecture",
                               "outcome": "unattended"})
        return real_invoke(name, context, arguments)

    monkeypatch.setattr(agent.tools, "invoke", invoke)
    seen = []
    bus.subscribe(lambda event: seen.append(event.payload)
                  if event.kind is Kind.TOOL_END else None)

    agent._execute([
        ToolCall(id="d1", name="delegate", arguments={"task": "x"}),
        ToolCall(id="w1", name="write_file",
                 arguments={"path": "db.py", "content": "ENGINE = 'sqlite'\n"}),
    ])

    write = next(payload for payload in seen if payload["name"] == "write_file")
    assert write["ok"] is False and write["meta"].get("withheld") is True
    assert not (config.paths.project / "db.py").exists(), "the write did not run"
    assert [d.what for d in agent._tool_context().evidence.decisions] == ["Which database?"]


def test_mutation_importing_after_the_batch_lets_the_sibling_write_run(
        config, bus, monkeypatch):
    from comodor.agent import AgentLoop, Conversation
    from comodor.providers.base import ToolCall
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry
    from comodor.tools.base import ToolResult

    agent = AgentLoop(config, Gateway(config, scripts=[Script(text="done")]),
                      ToolRegistry(), bus, PermissionEngine(config, bus), Conversation())
    real_invoke = agent.tools.invoke

    def invoke(name, context, arguments):
        if name == "delegate":
            return ToolResult.success(
                "Stopped.", clarification={"kind": "clarification_required",
                                           "decision": "Which database?", "candidates": [],
                                           "evidence_consulted": [], "reason": "architecture",
                                           "outcome": "unattended"})
        return real_invoke(name, context, arguments)

    monkeypatch.setattr(agent.tools, "invoke", invoke)
    real_import = agent._import_clarification
    deferred = []
    monkeypatch.setattr(agent, "_import_clarification",
                        lambda context, result, **_: deferred.append((context, result)))
    calls = [ToolCall(id="d1", name="delegate", arguments={"task": "x"}),
             ToolCall(id="w1", name="write_file",
                      arguments={"path": "db.py", "content": "ENGINE = 'sqlite'\n"})]

    agent._execute(calls)
    assert (config.paths.project / "db.py").exists(), "the mutation: the write ran"

    (config.paths.project / "db.py").unlink()
    monkeypatch.setattr(agent, "_import_clarification", real_import)
    agent.run("start over")                     # a fresh ledger
    monkeypatch.setattr(agent.tools, "invoke", invoke)
    agent._execute(calls)
    assert not (config.paths.project / "db.py").exists()
