"""The mutation preflight: a material decision cannot be skipped by not asking.

The clarification architecture registers a decision only when the model calls
`ask`. A model that forgets can change the project first — the benchmark's
`careful-unknowable` task found exactly that, an invented rate written without a
question. These pin the Core's own check: it sees the mutation's actual content
and the turn's actual evidence, requires each material choice to name its
source, withholds a missing one, and fails closed when it cannot decide.
"""

from __future__ import annotations

from comodor.agent import AgentLoop, Conversation, preflight
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry

MISSING = (
    '{"status": "requires_clarification", '
    '"decisions": [{"what": "What rate limit should the client use?", '
    '"affects": ["behaviour"], "resolution": "missing", "source_refs": []}], '
    '"reason": "the quota belongs to the account, not the repository"}'
)
ALLOW = '{"status": "allow", "decisions": [], "reason": "implementation detail"}'
REQUEST_GROUNDED = (
    '{"status": "allow", '
    '"decisions": [{"what": "Which rate to use", "affects": ["behaviour"], '
    '"resolution": "grounded", "source_refs": ["request"]}], '
    '"reason": "the user stated it"}'
)
REPO_GROUNDED = (
    '{"status": "allow", '
    '"decisions": [{"what": "Which rate to use", "affects": ["behaviour"], '
    '"resolution": "grounded", "source_refs": ["settings.py"]}], '
    '"reason": "the inspected config states it"}'
)
UNSOURCED = (
    '{"status": "allow", '
    '"decisions": [{"what": "Which rate to use", "affects": ["behaviour"], '
    '"resolution": "grounded", "source_refs": []}], "reason": "x"}'
)
DISCRETION_MATERIAL = (
    '{"status": "allow", '
    '"decisions": [{"what": "Which rate to use", "affects": ["behaviour"], '
    '"resolution": "agent_discretion", "source_refs": []}], "reason": "x"}'
)
ALLOW_WITH_MISSING = (
    '{"status": "allow", '
    '"decisions": [{"what": "Which rate to use", "affects": ["behaviour"], '
    '"resolution": "missing", "source_refs": []}], "reason": "x"}'
)
GARBAGE = "I think it is probably fine?"
REJECT = (
    '{"status": "reject", "decisions": [], '
    '"blockers": [{"what": "the request forbids inventing or substituting the '
    'coordinates", "kind": "request_constraint", '
    '"source_refs": ["request", "read_file:geocode.py"]}], '
    '"reason": "the authoritative dataset is unavailable and substitution is forbidden"}'
)
REJECT_UNGROUNDED = (
    '{"status": "reject", "decisions": [], '
    '"blockers": [{"what": "it is forbidden", "kind": "request_constraint", '
    '"source_refs": []}], "reason": "x"}'
)
ALLOW_WITH_BLOCKER = (
    '{"status": "allow", "decisions": [], '
    '"blockers": [{"what": "it is forbidden", "kind": "request_constraint", '
    '"source_refs": ["request"]}], "reason": "x"}'
)
CLARIFY_WITH_BLOCKER = (
    '{"status": "requires_clarification", '
    '"decisions": [{"what": "Which rate limit?", "affects": ["behaviour"], '
    '"resolution": "missing", "source_refs": []}], '
    '"blockers": [{"what": "it is forbidden", "kind": "request_constraint", '
    '"source_refs": ["request"]}], "reason": "x"}'
)
REJECT_WITH_MISSING = (
    '{"status": "reject", '
    '"decisions": [{"what": "Which rate limit?", "affects": ["behaviour"], '
    '"resolution": "missing", "source_refs": []}], '
    '"blockers": [{"what": "it is forbidden", "kind": "request_constraint", '
    '"source_refs": ["request"]}], "reason": "x"}'
)


def _agent(config, bus, scripts, *, answer=None):
    agent = AgentLoop(config, Gateway(config, scripts=scripts), ToolRegistry(),
                      bus, PermissionEngine(config, bus), Conversation())
    if answer is not None:
        agent.gateway.provider("fake").preflight = answer
    return agent


def _write_after_read(path: str, content: str) -> list[Script]:
    return [
        Script(text="Reading.", tool_calls=[ToolCall(
            id="r1", name="read_file", arguments={"path": path})]),
        Script(text="Writing.", tool_calls=[ToolCall(
            id="w1", name="write_file", arguments={"path": path, "content": content})]),
        Script(text="The task is complete."),
    ]


def _question(agent) -> str:
    return agent.gateway.provider("fake").preflight_questions[0]


# --------------------------------------------------------------------------- #
# the input the assessor is given
# --------------------------------------------------------------------------- #


def test_the_preflight_sees_the_value_the_mutation_introduces(config, bus, workspace):
    """A path alone cannot say whether the change invents a value."""
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus,
                   _write_after_read("client.py", "RATE_LIMIT_RPS = 5\n"),
                   answer=MISSING)

    agent.run("add rate limiting to the client")

    assert "RATE_LIMIT_RPS = 5" in _question(agent)


def test_the_preflight_sees_what_the_turn_observed(config, bus, workspace):
    """A source name alone cannot say what the file does or does not contain."""
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus, _write_after_read("client.py", "RATE = 5\n"),
                   answer=MISSING)

    agent.run("add rate limiting to the client")

    question = _question(agent)
    assert "client.py" in question and "BASE = 1" in question


def test_the_preflight_input_is_redacted(config, bus, workspace):
    config.providers["fake"].api_key = "sk-secret-value-123456"
    (workspace / "client.py").write_text("TOKEN = 'sk-secret-value-123456'\n",
                                         encoding="utf-8")
    agent = _agent(config, bus, _write_after_read("client.py", "X = 1\n"),
                   answer=ALLOW)

    agent.run("tidy client.py")

    assert "sk-secret-value-123456" not in _question(agent)


# --------------------------------------------------------------------------- #
# enforcement
# --------------------------------------------------------------------------- #


def test_an_invented_value_is_blocked_and_never_reaches_disk(config, bus, workspace):
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus,
                   _write_after_read("client.py", "RATE_LIMIT_RPS = 5\n"),
                   answer=MISSING)

    result = agent.run("add rate limiting to the client")

    assert (workspace / "client.py").read_text(encoding="utf-8") == "BASE = 1\n", \
        "the invented rate reached disk"
    assert result.stopped == "clarification_required"
    assert [d.what for d in agent.tool_context.evidence.decisions] == \
        ["What rate limit should the client use?"]
    assert agent._written_paths == []


def test_a_gate_fault_withholds_the_mutation(config, bus, workspace, monkeypatch):
    """Fails closed: a fault in the guard is not permission to change."""
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus, _write_after_read("client.py", "RATE = 5\n"),
                   answer=ALLOW)

    def explode(*args, **kwargs):
        raise RuntimeError("the preflight exploded")

    monkeypatch.setattr(agent, "_assess_batch", explode)
    agent.run("add rate limiting to the client")

    assert (workspace / "client.py").read_text(encoding="utf-8") == "BASE = 1\n"


def test_an_unreadable_assessment_does_not_become_allow(config, bus, workspace):
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus, _write_after_read("client.py", "RATE = 5\n"),
                   answer=GARBAGE)

    agent.run("add rate limiting to the client")

    assert (workspace / "client.py").read_text(encoding="utf-8") == "BASE = 1\n"


def test_a_settled_decision_is_not_reopened(config, bus, tool_context):
    """The user answered it: the same dependent mutation may now proceed."""
    tool_context.request_text = "add rate limiting to the client"
    tool_context.evidence.known("What rate limit should the client use?",
                                source="user", material="5 per second")
    agent = _agent(config, bus, [], answer=MISSING)
    call = ToolCall(id="w1", name="write_file",
                    arguments={"path": "client.py", "content": "RATE = 5\n"})

    assert agent._mutation_gate(tool_context, call) is None, \
        "a decision the ledger already settled blocked the write"
    assert not tool_context.evidence.withheld()


# --------------------------------------------------------------------------- #
# allow cases — over-asking is a failure too
# --------------------------------------------------------------------------- #


def test_an_implementation_detail_is_allowed(config, bus, workspace):
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus, _write_after_read("client.py", "RATE = 5\n"),
                   answer=ALLOW)

    result = agent.run("add rate limiting to the client")

    assert (workspace / "client.py").read_text(encoding="utf-8") == "RATE = 5\n"
    assert result.stopped == "done"
    assert agent.tool_context.evidence.decisions == []


def test_a_value_the_user_stated_is_allowed(config, bus, workspace):
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus, _write_after_read("client.py", "RATE = 5\n"),
                   answer=REQUEST_GROUNDED)

    agent.run("add rate limiting at 5 per second")

    assert (workspace / "client.py").read_text(encoding="utf-8") == "RATE = 5\n"


def test_a_value_the_configuration_states_is_allowed(config, bus, workspace):
    (workspace / "settings.py").write_text("RATE = 5\n", encoding="utf-8")
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    scripts = [
        Script(text="Reading settings.", tool_calls=[ToolCall(
            id="r1", name="read_file", arguments={"path": "settings.py"})]),
        Script(text="Writing.", tool_calls=[ToolCall(
            id="w1", name="write_file",
            arguments={"path": "client.py", "content": "RATE = 5\n"})]),
        Script(text="Done."),
    ]
    agent = _agent(config, bus, scripts, answer=REPO_GROUNDED)

    agent.run("add rate limiting from the config")

    assert (workspace / "client.py").read_text(encoding="utf-8") == "RATE = 5\n"


# --------------------------------------------------------------------------- #
# a grounded rejection runs nothing, asks nothing, and opens no decision
# --------------------------------------------------------------------------- #


def test_a_grounded_rejection_runs_nothing_and_asks_nothing(
        config, bus, workspace, monkeypatch):
    """A forbidden substitution is not a question: no form, no decision."""
    from comodor.tools import ask as ask_tool

    asked: list[int] = []
    resolved: list[int] = []
    real_present = ask_tool.present

    def spy_present(ctx, pending, **kwargs):
        asked.append(1)
        return real_present(ctx, pending, **kwargs)

    monkeypatch.setattr(ask_tool, "present", spy_present)
    monkeypatch.setattr(
        bus, "resolve",
        lambda request, timeout=None: (resolved.append(1), (None, False))[1])
    (workspace / "geocode.py").write_text("DATA = 'postcodes.csv'\n", encoding="utf-8")
    scripts = [
        Script(text="Reading.", tool_calls=[ToolCall(
            id="r1", name="read_file", arguments={"path": "geocode.py"})]),
        Script(text="Writing a stand-in.", tool_calls=[ToolCall(
            id="w1", name="write_file",
            arguments={"path": "postcodes.csv", "content": "lat,lon\n"})]),
        Script(text="The authoritative dataset is unavailable and I was told not "
                    "to substitute it, so the suite still does not pass."),
    ]
    agent = _agent(config, bus, scripts, answer=REJECT)

    result = agent.run(
        "The coordinates come only from the authoritative dataset; it is "
        "unavailable; do not fetch it elsewhere; do not invent coordinates; do "
        "not write a stand-in table.")

    assert not (workspace / "postcodes.csv").exists(), "the rejected mutation ran"
    assert result.stopped == "done", "a rejection is not a clarification"
    assert result.clarification is None
    assert asked == [], "a rejection presented a form"
    assert resolved == [], "a rejection resolved a request"
    assert agent.tool_context.evidence.decisions == [], \
        "a rejection opened a ledger decision"
    assert not agent.tool_context.evidence.withheld()
    assert len(agent.gateway.provider("fake").calls) == 3, "the loop did not continue"
    trace = agent._preflight_traces[0]
    assert trace["assessment"]["status"] == "reject"
    assert trace["withheld"] is True
    assert trace["assessment"]["blockers"][0]["source_refs"]


def test_a_missing_external_rate_still_clarifies(config, bus, workspace):
    """The reject outcome must not swallow a real missing decision."""
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus,
                   _write_after_read("client.py", "RATE_LIMIT_RPS = 5\n"),
                   answer=MISSING)

    result = agent.run("add rate limiting to the client")

    assert result.stopped == "clarification_required"
    assert agent.tool_context.evidence.decisions, "no decision was registered"
    assert (workspace / "client.py").read_text(encoding="utf-8") == "BASE = 1\n"
    assert agent._preflight_traces[0]["assessment"]["status"] == \
        "requires_clarification"


def test_a_supplied_authoritative_value_is_allowed(config, bus, workspace):
    """With the source supplied, the same mutation is grounded, not rejected."""
    (workspace / "geocode.py").write_text("DATA = 'postcodes.csv'\n", encoding="utf-8")
    scripts = [
        Script(text="Reading.", tool_calls=[ToolCall(
            id="r1", name="read_file", arguments={"path": "geocode.py"})]),
        Script(text="Writing.", tool_calls=[ToolCall(
            id="w1", name="write_file",
            arguments={"path": "postcodes.csv", "content": "lat,lon\n"})]),
        Script(text="Done."),
    ]
    agent = _agent(config, bus, scripts, answer=REQUEST_GROUNDED)

    result = agent.run("write postcodes.csv from the dataset I supplied")

    assert result.stopped == "done"
    assert (workspace / "postcodes.csv").read_text(encoding="utf-8") == "lat,lon\n"
    assert agent.tool_context.evidence.decisions == []


# --------------------------------------------------------------------------- #
# the grounding contract, mechanically
# --------------------------------------------------------------------------- #


def test_a_grounded_decision_must_name_a_source():
    assert preflight.parse(UNSOURCED).status == "blocked"


def test_discretion_may_not_stand_in_for_a_material_choice():
    assert preflight.parse(DISCRETION_MATERIAL).status == "blocked"


def test_an_allow_may_not_discard_a_missing_decision():
    assessment = preflight.parse(ALLOW_WITH_MISSING)
    assert assessment.status == "requires_clarification"
    assert assessment.missing_decisions


def test_a_malformed_answer_is_blocked():
    assert preflight.parse(GARBAGE).status == "blocked"
    assert preflight.parse("").status == "blocked"


# --------------------------------------------------------------------------- #
# reject is a distinct, grounded outcome — not a clarification
# --------------------------------------------------------------------------- #


def test_a_grounded_rejection_is_recognised():
    assessment = preflight.parse(REJECT)
    assert assessment.status == "reject"
    assert assessment.rejected
    assert assessment.blockers
    assert assessment.blockers[0].source_refs
    assert assessment.blockers[0].kind == "request_constraint"


def test_a_rejection_without_grounding_is_refused():
    """A reject with no grounded blocker must not be trusted (fail closed)."""
    assert preflight.parse(REJECT_UNGROUNDED).status == "blocked"


def test_an_allow_may_not_carry_a_blocker():
    assert preflight.parse(ALLOW_WITH_BLOCKER).status == "blocked"


def test_a_clarification_may_not_carry_a_blocker():
    assert preflight.parse(CLARIFY_WITH_BLOCKER).status == "blocked"


def test_a_rejection_may_not_also_claim_a_missing_decision():
    assert preflight.parse(REJECT_WITH_MISSING).status == "blocked"


def test_reject_and_clarify_do_not_collapse():
    """A missing external value clarifies; a forbidden substitution rejects."""
    clarify = preflight.parse(MISSING)
    reject = preflight.parse(REJECT)
    assert clarify.status == "requires_clarification"
    assert reject.status == "reject"
    assert clarify.status != reject.status


def test_the_rejection_trace_names_the_blocker():
    trace = preflight.parse(REJECT).as_trace()
    assert trace["status"] == "reject"
    assert trace["blockers"][0]["source_refs"]
    assert trace["blockers"][0]["kind"] == "request_constraint"


# --------------------------------------------------------------------------- #
# scope and cost
# --------------------------------------------------------------------------- #


def test_the_preflight_runs_once_per_mutation_batch(config, bus, workspace):
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    scripts = [
        Script(text="Writing.", tool_calls=[ToolCall(
            id="w1", name="write_file", arguments={"path": "client.py", "content": "A = 1\n"})]),
        Script(text="Writing again.", tool_calls=[ToolCall(
            id="w2", name="write_file", arguments={"path": "client.py", "content": "A = 2\n"})]),
        Script(text="Done."),
    ]
    agent = _agent(config, bus, scripts, answer=ALLOW)

    agent.run("set A")

    assert agent._measurement.preflight_calls == 2


def test_a_read_only_turn_pays_no_preflight(config, bus, workspace):
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    scripts = [Script(text="Reading.", tool_calls=[ToolCall(
        id="r1", name="read_file", arguments={"path": "client.py"})]),
        Script(text="It has a BASE constant.")]
    agent = _agent(config, bus, scripts)

    agent.run("what is in client.py?")

    assert agent._measurement.preflight_calls == 0


def test_the_preflight_trace_can_explain_an_allow(config, bus, workspace):
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus, _write_after_read("client.py", "RATE = 5\n"),
                   answer=MISSING)

    agent.run("add rate limiting to the client")

    traces = agent._preflight_traces
    assert len(traces) == 1
    trace = traces[0]
    assert trace["assessment"]["status"] == "requires_clarification"
    assert trace["assessment"]["decisions"][0]["resolution"] == "missing"
    assert trace["withheld"] is True
    assert trace["question_fingerprint"] and trace["mutation_fingerprint"]


# --------------------------------------------------------------------------- #
# the shared clarification lifecycle
# --------------------------------------------------------------------------- #


def test_the_preflight_uses_the_shared_clarification_service(config, bus, workspace,
                                                             monkeypatch):
    from comodor.tools import ask as ask_tool

    seen = {}
    real = ask_tool.present

    def spy(ctx, pending, *, origin="model_ask"):
        seen["origin"] = origin
        return real(ctx, pending, origin=origin)

    monkeypatch.setattr(ask_tool, "present", spy)
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus, _write_after_read("client.py", "RATE = 5\n"),
                   answer=MISSING)

    agent.run("add rate limiting to the client")

    assert seen.get("origin") == "mutation_preflight"


def test_a_non_interactive_preflight_is_unattended(config, bus, workspace):
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus, _write_after_read("client.py", "RATE = 5\n"),
                   answer=MISSING)

    result = agent.run("add rate limiting to the client")

    assert result.stopped == "clarification_required"
    assert (result.clarification or {}).get("outcome") == "unattended"
    assert (workspace / "client.py").read_text(encoding="utf-8") == "BASE = 1\n"


def test_the_preflight_origin_is_preserved_in_the_form(config, bus, workspace):
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus, _write_after_read("client.py", "RATE = 5\n"),
                   answer=MISSING)

    agent.run("add rate limiting to the client")

    forms = [message.meta.get("question") for message in agent.conversation.messages
             if isinstance(message.meta, dict) and message.meta.get("question")]
    assert any(form.get("origin") == "mutation_preflight" for form in forms)


def test_an_answered_preflight_resumes_the_dependent_mutation(config, bus, workspace):
    """Interactive: the preflight finds the missing rate, the real form is
    presented, the person answers, the *same* ledger decision becomes KNOWN,
    and the dependent write may run — with no false `cancelled`."""
    import json

    from comodor.events import Kind

    answered: list[str] = []

    def answer_the_form(event):
        if event.kind is not Kind.REQUEST:
            return
        request = event.payload["request"]
        headers = [question["header"] for question in request.meta["questions"]]
        request.answer(json.dumps([{"header": headers[0], "prompt": "",
                                    "chosen": [], "written": "5 per second"}]))
        answered.append(headers[0])

    bus.subscribe(answer_the_form)
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus,
                   _write_after_read("client.py", "RATE_LIMIT_RPS = 5\n"),
                   answer=MISSING)

    result = agent.run("add rate limiting to the client")

    assert answered, "the preflight did not present a real form"
    assert (workspace / "client.py").read_text(encoding="utf-8") == \
        "RATE_LIMIT_RPS = 5\n", "the dependent mutation did not resume after the answer"
    assert result.stopped == "done"
    decision = agent.tool_context.evidence.decisions[0]
    assert decision.state == "answered" and decision.answer == "5 per second"


# --------------------------------------------------------------------------- #
# delegate mutability is the contract's, not the model's opinion
# --------------------------------------------------------------------------- #


def test_delegate_mutability_is_deterministic(config, bus):
    agent = _agent(config, bus, [])

    def call(**args):
        return ToolCall(id="d", name="delegate", arguments={"task": "x", **args})

    assert not agent._is_mutating(call())
    assert not agent._is_mutating(call(write=False))
    assert not agent._is_mutating(call(background=True))
    assert not agent._is_mutating(call(write=True, background=True))
    assert agent._is_mutating(call(write=True))


def test_a_mutating_delegate_is_gated_before_it_starts(config, bus, workspace,
                                                       monkeypatch):
    scripts = [Script(text="Delegating.", tool_calls=[ToolCall(
        id="d1", name="delegate",
        arguments={"task": "write the limiter", "write": True})])]
    agent = _agent(config, bus, scripts, answer=MISSING)
    started = []
    real = agent.tools.invoke

    def spy(name, ctx, args):
        started.append(name)
        if name == "delegate":
            from comodor.tools.base import ToolResult
            return ToolResult.success("delegated")
        return real(name, ctx, args)

    monkeypatch.setattr(agent.tools, "invoke", spy)
    result = agent.run("add rate limiting")

    assert "delegate" not in started, "the child started under an unresolved decision"
    assert result.stopped == "clarification_required"


def test_a_read_only_delegate_pays_no_preflight(config, bus, workspace):
    scripts = [Script(text="Delegating.", tool_calls=[ToolCall(
        id="d1", name="delegate", arguments={"task": "explore the project"})]),
        Script(text="Done.")]
    agent = _agent(config, bus, scripts)

    agent.run("what is in this project?")

    assert agent._measurement.preflight_calls == 0
