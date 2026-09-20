"""The mutation preflight: a material decision cannot be skipped by not asking.

The clarification architecture registers a decision only when the model calls
`ask`. A model that forgets can change the project first — the benchmark's
`careful-unknowable` task found exactly that, an invented rate limit written
without a question. These pin the Core's own check, run before the first call
that can change anything: a missing material decision is registered and the
mutation does not run; an implementation choice the request leaves to the agent
is not a decision and the mutation runs.
"""

from __future__ import annotations

from comodor.agent import AgentLoop, Conversation
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry

REQUIRES = (
    '{"status": "requires_clarification", '
    '"decisions": [{"what": "What rate limit should the client use?", '
    '"affects": ["behaviour"]}], '
    '"reason": "the quota belongs to the account, not the repository"}'
)
ALLOW = '{"status": "allow", "decisions": [], "reason": "implementation detail"}'
GARBAGE = "I think it is probably fine?"


def _agent(config, bus, scripts, *, preflight=None):
    agent = AgentLoop(config, Gateway(config, scripts=scripts), ToolRegistry(),
                      bus, PermissionEngine(config, bus), Conversation())
    if preflight is not None:
        agent.gateway.provider("fake").preflight = preflight
    return agent


def _write_after_read(path: str, content: str) -> list[Script]:
    return [
        Script(text="Reading.", tool_calls=[ToolCall(
            id="r1", name="read_file", arguments={"path": path})]),
        Script(text="Writing.", tool_calls=[ToolCall(
            id="w1", name="write_file", arguments={"path": path, "content": content})]),
        Script(text="The task is complete."),
    ]


def test_a_missing_material_fact_blocks_the_dependent_write(config, bus, workspace):
    """The careful-unknowable shape: the rate is nowhere in the repository."""
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus, _write_after_read("client.py", "RATE = 5\n"),
                   preflight=REQUIRES)

    result = agent.run("add rate limiting to the client so we stop hitting 429s")

    assert (workspace / "client.py").read_text(encoding="utf-8") == "BASE = 1\n", \
        "the invented rate reached disk"
    assert result.stopped == "clarification_required"
    decisions = [d.what for d in agent.tool_context.evidence.decisions]
    assert decisions == ["What rate limit should the client use?"]
    assert "RATE" not in (workspace / "client.py").read_text(encoding="utf-8")


def test_the_blocked_call_is_reported_as_withheld(config, bus, workspace):
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus, _write_after_read("client.py", "RATE = 5\n"),
                   preflight=REQUIRES)

    agent.run("add rate limiting")

    # The write never became a mutation the completion gate could count.
    assert agent._written_paths == []
    assert agent.tool_context.evidence.entries, "the ledger recorded the turn"


def test_an_implementation_detail_is_not_a_material_decision(config, bus, workspace):
    """FR-011/FR-012: a choice the request leaves to the agent may proceed."""
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus, _write_after_read("client.py", "RATE = 5\n"),
                   preflight=ALLOW)

    result = agent.run("add rate limiting to the client")

    assert (workspace / "client.py").read_text(encoding="utf-8") == "RATE = 5\n", \
        "an allowed mutation was blocked"
    assert result.stopped == "done"
    assert agent.tool_context.evidence.decisions == []


def test_a_settled_decision_is_not_reopened(config, bus, tool_context):
    """The user answered it: the same dependent mutation may now proceed."""
    tool_context.request_text = "add rate limiting to the client"
    tool_context.evidence.known("What rate limit should the client use?",
                                source="user", material="5 per second")
    agent = _agent(config, bus, [], preflight=REQUIRES)
    call = ToolCall(id="w1", name="write_file",
                    arguments={"path": "client.py", "content": "RATE = 5\n"})

    assert agent._mutation_gate(tool_context, call) is None, \
        "a decision the ledger already settled blocked the write"
    assert not tool_context.evidence.withheld()


def test_a_malformed_assessment_does_not_become_allow(config, bus, workspace):
    """An unreadable guard is not permission: the mutation is withheld."""
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus, _write_after_read("client.py", "RATE = 5\n"),
                   preflight=GARBAGE)

    result = agent.run("add rate limiting to the client")

    assert (workspace / "client.py").read_text(encoding="utf-8") == "BASE = 1\n"
    assert result.stopped != "done" or agent._written_paths == []


def test_the_preflight_runs_once_per_turn(config, bus, workspace):
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    agent = _agent(config, bus, _write_after_read("client.py", "RATE = 5\n"),
                   preflight=ALLOW)

    agent.run("add rate limiting to the client")

    assert agent._measurement.preflight_calls == 1
    assert agent._measurement.preflight_tokens > 0


def test_a_read_only_turn_pays_no_preflight(config, bus, workspace):
    (workspace / "client.py").write_text("BASE = 1\n", encoding="utf-8")
    scripts = [Script(text="Reading.", tool_calls=[ToolCall(
        id="r1", name="read_file", arguments={"path": "client.py"})]),
        Script(text="It has a BASE constant.")]
    agent = _agent(config, bus, scripts)

    agent.run("what is in client.py?")

    assert agent._measurement.preflight_calls == 0
