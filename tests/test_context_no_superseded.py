"""Zero superseded file copies in any assembled request (T081, T091; FR-045,
FR-088, SC-013).

Across a scripted multi-step run that reads, edits and re-reads, no request
the model receives carries the pre-edit copy of a file in full once the
sweep has run; an edit is represented by its change, not the whole file;
and the guard is the sweep itself — remove it and the stale copy reappears.
"""

from __future__ import annotations

from comodor.agent import AgentLoop, Conversation, staleness
from comodor.providers.base import Role, ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry


def big(marker="x", lines=900):
    return "\n".join(f"{n:6d}\t{marker} = {n}" for n in range(1, lines))


def scripts():
    return [
        Script(text="Reading.", tool_calls=[ToolCall(id="r1", name="read_file",
                                                     arguments={"path": "a.py"})]),
        Script(text="Editing.", tool_calls=[ToolCall(id="e1", name="edit_file",
                                                     arguments={"path": "a.py",
                                                                "old_string": "     1\tx = 1",
                                                                "new_string": "     1\tx = 100"})]),
        Script(text="Reading again.", tool_calls=[ToolCall(id="r2", name="read_file",
                                                           arguments={"path": "a.py"})]),
        Script(text="Looking.", tool_calls=[ToolCall(id="l1", name="list_dir",
                                                     arguments={"path": "."})]),
        Script(text="Done."),
    ]


def _run(config, bus):
    (config.paths.project / "a.py").write_text(big(), encoding="utf-8")
    config.agent.compact_at = 0.0001            # pressure on every step
    gateway = Gateway(config, scripts=scripts())
    agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation())
    agent._window = lambda: 50_000_000
    agent._summarise = lambda middle: "brief"
    agent.run("read, edit, read again")
    return agent, gateway


def _stale_copies(gateway):
    """Requests that carry the pre-edit copy of a.py in full."""
    stale = []
    for index, payload in enumerate(gateway.provider("fake").calls):
        for message in payload:
            if message.role is Role.TOOL and message.name == "read_file" \
                    and "x = 1\n" in message.content and "superseded" not in message.content:
                stale.append(index)
    return stale


def test_no_request_after_the_sweep_carries_the_superseded_copy(config, bus):
    agent, gateway = _run(config, bus)
    calls = gateway.provider("fake").calls
    assert len(calls) == 5
    # The first two requests predate the edit; from the re-read onward the
    # pre-edit copy must be gone from every request the model receives.
    assert [i for i in _stale_copies(gateway) if i >= 3] == []
    first = next(m for m in agent.conversation.messages if m.tool_call_id == "r1")
    assert first.meta.get("superseded") is True
    assert "read the file again" in first.content


def test_the_edit_is_represented_by_its_change_not_the_file(config, bus):
    agent, _ = _run(config, bus)
    edit = next(m for m in agent.conversation.messages if m.tool_call_id == "e1")
    assert edit.content.startswith("Edited a.py (+1/-1")
    assert len(edit.content) < 400
    assert "x = 2\n" not in edit.content


def test_the_guard_is_the_sweep(config, bus, monkeypatch):
    """Mutation check: with the sweep disabled, the stale copy stays.

    The budget manager would move the stale copy aside as well — it is
    retrievable — so it is switched off here to show the sweep alone is a
    sufficient guard, and that removing it is caught.
    """
    monkeypatch.setattr(staleness, "forget_superseded_reads",
                        lambda messages, estimate, worth_it=0: (0, 0))
    config.agent.optimizations_off = ["budget"]
    agent, gateway = _run(config, bus)
    assert [i for i in _stale_copies(gateway) if i >= 3], \
        "the mutation leaves the stale copy in the request"
    monkeypatch.undo()
    agent, gateway = _run(config, bus)
    assert [i for i in _stale_copies(gateway) if i >= 3] == []
