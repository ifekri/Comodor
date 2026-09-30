"""Optimization neutrality (FR-044; the constitution's context-change gate).

Two things are asserted here.

*Every optimization can be switched off.* Each Phase 5 context optimization is
named in `OPTIMIZATIONS`, plus the log summariser, and a test can switch any of
them off for itself — through the `Optimizer` a conversation is given, or by
standing the summariser aside. No setting exists for this outside the tests
(D17).

*The outcome does not move.* Run the same fixed multi-turn task under every
setting and the delivered work is identical: the same turn result, the same
tool calls, the same bytes on disk. The optimization that is on is shown to be
load-bearing — with it off, the same work costs more context — so the parity
is a real measurement rather than a vacuous one.
"""

from __future__ import annotations

import pytest

from comodor.agent import AgentLoop, Conversation
from comodor.agent.context import OPTIMIZATIONS, Optimizer
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry, overflow
from comodor.tools.base import ToolResult

#: Every Phase 5 optimization, and the task that owns it. The log summariser
#: lives in `tools/overflow` rather than `context.py`, so it is listed here too.
PHASE_5_SWITCHES = {
    "T070": "budget",
    "T071": "ranking",
    "T072": "dedup",
    "T073": "dedup",
    "T074": "delta",
    "T076": "summary_provenance",
    "T080": "log_summary",
}

ALL_SWITCHES = tuple(OPTIMIZATIONS) + ("log_summary",)


def switch_off(agent, off, monkeypatch) -> None:
    """Switch `off` off for this test only: the seam that replaced the settings."""
    agent.conversation.optimizer = Optimizer(
        name for name in OPTIMIZATIONS if name not in off)
    if "log_summary" in off:
        monkeypatch.setattr(overflow, "_summarise_log", lambda *args, **kwargs: None)


def big(marker: str, lines: int = 300) -> str:
    return "\n".join(f"line {n}: {marker} = {n}" for n in range(lines))


def make_agent(config, bus, scripts):
    gateway = Gateway(config, scripts=scripts)
    return AgentLoop(config, gateway, ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation())


# --------------------------------------------------------------------------- #
# every optimization can be switched off, inside a test
# --------------------------------------------------------------------------- #


def test_every_switchable_optimization_is_a_named_switch():
    assert set(ALL_SWITCHES) == {"dedup", "delta", "budget", "ranking",
                                 "summary_provenance", "log_summary"}
    assert set(PHASE_5_SWITCHES.values()) == set(ALL_SWITCHES), (
        "every switchable optimization is owned by a task, and every task "
        "names a switch")


def test_the_log_summariser_is_switched_off_only_inside_a_test(tool_context, monkeypatch):
    log = ("exit 0 in 2s\n" + "\n".join(f"case {n} PASSED" for n in range(300))
           + "\n300 passed in 2.0s")
    collapsed = overflow.contain(ToolResult.success(log, exit_code=0), tool_context,
                                 "run_shell")
    assert collapsed.meta.get("log") == "passed", "on by default: no setting to turn it off"
    monkeypatch.setattr(overflow, "_summarise_log", lambda *args, **kwargs: None)
    kept = overflow.contain(ToolResult.success(log, exit_code=0), tool_context, "run_shell")
    assert "log" not in kept.meta


# --------------------------------------------------------------------------- #
# the outcome does not move, and the optimization is load-bearing
# --------------------------------------------------------------------------- #


def _delta_scenario(config, bus):
    """Read a file, have it edited by someone else, read it again.

    The edit happens between the two reads out of band — as a person's editor
    or a build would do — so the second read is a genuine changed-copy of the
    first, which is what the delta path is for.
    """
    original = big("first")
    changed = original.replace("line 7: first = 7", "line 7: edited = 7")
    target = config.paths.project / "a.py"
    target.write_text(original, encoding="utf-8")
    agent = make_agent(config, bus, [
        Script(text="Reading.", tool_calls=[ToolCall(id="r1", name="read_file",
                                                     arguments={"path": "a.py"})]),
        Script(text="Reading again.", tool_calls=[ToolCall(id="r2", name="read_file",
                                                           arguments={"path": "a.py"})]),
        Script(text="Done."),
    ])
    provider = agent.gateway.provider("fake")
    real = provider.stream

    def edit_between_reads(messages, **kwargs):
        if len(provider.calls) == 1:
            target.write_text(changed, encoding="utf-8")
        return real(messages, **kwargs)

    provider.stream = edit_between_reads
    return agent, target, changed


@pytest.mark.parametrize("off", [
    [],
    ["dedup"],
    ["delta"],
    ["budget"],
    ["ranking"],
    ["summary_provenance"],
    ["log_summary"],
    list(ALL_SWITCHES),
])
def test_the_same_task_delivers_the_same_work_under_every_setting(config, bus, off,
                                                                  monkeypatch):
    agent, target, changed = _delta_scenario(config, bus)
    switch_off(agent, off, monkeypatch)
    result = agent.run("read a.py, then read it again after it changes")

    assert result.ok, off
    assert result.stopped == "done", off
    assert result.tool_calls == 2, off
    assert target.read_text(encoding="utf-8") == changed, (
        f"the delivered state must not depend on the optimization setting ({off})")


def test_delta_is_load_bearing_so_the_parity_is_measured(config, bus, monkeypatch):
    agent, _, _ = _delta_scenario(config, bus)
    switch_off(agent, ALL_SWITCHES, monkeypatch)
    agent.run("read a.py, then read it again after it changes")
    without = agent.conversation.bytes_saved

    monkeypatch.undo()
    agent, _, _ = _delta_scenario(config, bus)
    agent.run("read a.py, then read it again after it changes")
    with_delta = agent.conversation.bytes_saved

    assert with_delta > without >= 0, (
        "the second, changed read must shrink with the delta on — otherwise "
        "the neutrality comparison would be measuring nothing")


def test_a_reference_is_never_offered_for_material_that_is_gone(config, bus):
    """A setting that withheld a base must not leave a live reference to it."""
    agent, _, _ = _delta_scenario(config, bus)
    result = agent.run("read a.py, then read it again after it changes")
    assert result.stopped == "done"
    by_id = {m.tool_call_id: m for m in agent.conversation.messages}
    for message in agent.conversation.messages:
        base = message.meta.get("delta_base") or message.meta.get("reference")
        if not base:
            continue
        holder = by_id.get(base)
        assert holder is not None, "a delta must point at a resident base"
        assert "withheld" not in holder.meta and "reference" not in holder.meta, (
            "the base a delta names must itself be resident in full")
