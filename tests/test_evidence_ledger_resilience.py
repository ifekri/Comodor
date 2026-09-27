"""A fault in the ledger never kills a turn (T027; FR-002, contract E5).

The ledger is bookkeeping. When it raises, the turn continues, what it could
not classify stays `UNKNOWN`, and nothing is ever resolved to a value by
default.
"""

from __future__ import annotations

import pytest

from comodor.agent import AgentLoop, Conversation
from comodor.agent import evidence as ev
from comodor.agent.evidence import EvidenceState as S
from comodor.agent.evidence import Ledger
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry


def make_agent(config, bus, scripts):
    gateway = Gateway(config, scripts=scripts)
    return AgentLoop(config, gateway, ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation())


class Broken(Ledger):
    def verified(self, *args, **kwargs):
        raise RuntimeError("the ledger exploded")

    def known(self, *args, **kwargs):
        raise RuntimeError("the ledger exploded")


def test_an_internal_ledger_error_does_not_kill_the_turn(config, bus, monkeypatch):
    monkeypatch.setattr(ev, "Ledger", Broken)
    (config.paths.project / "app.py").write_text("x = 1\n", encoding="utf-8")
    agent = make_agent(config, bus, [
        Script(text="Reading.", tool_calls=[
            ToolCall(id="r", name="read_file", arguments={"path": "app.py"})]),
        Script(text="It sets x."),
    ])
    result = agent.run("what does app.py do?")
    assert result.ok and result.text == "It sets x."
    assert result.error == ""


def test_what_the_ledger_could_not_record_reads_as_unknown(config, bus, monkeypatch):
    monkeypatch.setattr(ev, "Ledger", Broken)
    (config.paths.project / "app.py").write_text("x = 1\n", encoding="utf-8")
    agent = make_agent(config, bus, [
        Script(text="Reading.", tool_calls=[
            ToolCall(id="r", name="read_file", arguments={"path": "app.py"})]),
        Script(text="Done."),
    ])
    agent.run("read it")
    book = agent.tool_context.evidence
    assert book.state_of("read app.py") is S.UNKNOWN
    assert book.may_rely_on("read app.py") is False


def test_a_read_still_succeeds_when_the_ledger_raises(config, tool_context, monkeypatch):
    from comodor.tools.fs import ReadFile

    monkeypatch.setattr(ev, "Ledger", Broken)
    target = config.paths.project / "a.py"
    target.write_text("print(1)\n", encoding="utf-8")
    result = ReadFile().run(tool_context, path="a.py")
    assert result.ok and "print(1)" in result.content
    assert tool_context.was_read(target)


def test_an_unclassifiable_outcome_is_the_safe_side():
    """A lifecycle outcome the caller cannot name is treated as cancelled —
    never resolved to KNOWN by default."""
    ledger = Ledger()
    decision = ledger.open_decision("which database", affects=["architecture"])
    ledger.ended_without_answer(decision.id, "???")
    assert ledger.get(decision.entry_id).state is S.UNRESOLVED
    assert ledger.decision(decision.id).outcome == "cancelled"
    assert ledger.withheld() == [decision]


def test_an_empty_answer_resolves_nothing():
    ledger = Ledger()
    decision = ledger.open_decision("which database", affects=["architecture"])
    with pytest.raises(ev.IllegalEvidence):
        ledger.answered(decision.id, "   ")
    assert ledger.get(decision.entry_id).state is S.REQUIRES_CLARIFICATION


def test_a_ledger_error_inside_note_read_never_reaches_the_caller(config, tool_context):
    class Exploding:
        def verified(self, *a, **k):
            raise RuntimeError("boom")

    tool_context._evidence = Exploding()
    target = config.paths.project / "b.py"
    target.write_text("y = 2\n", encoding="utf-8")
    tool_context.note_read(target, material="y = 2\n")
    assert tool_context.was_read(target)
