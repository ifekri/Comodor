"""End-to-end token accounting: every provider call a task makes is counted.

Spec 002 SC-011 asks whether the same tasks complete with fewer total tokens.
A total that omits a provider call is not a total. The compaction summary is a
real provider call — it used to be spent and not counted, so a task that
compacted reported less than it cost. These prove the runtime counts it
exactly once, that a run which does not compact has no phantom summary usage,
that a failed summary adds nothing, and that repeated compactions each count
their own call.
"""

from __future__ import annotations

from comodor.agent import AgentLoop, Conversation
from comodor.agent.context import KEEP_RECENT_RESULTS
from comodor.events import EventBus
from comodor.providers.base import Message, ToolCall, Usage
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry


def big(marker="x", lines=200):
    return "\n".join(f"line {n}: {marker} = {n}" for n in range(lines))


def a_history():
    """A settled history big enough that compaction has something to cut."""
    conversation = Conversation()
    conversation.add(Message.user("Fix the pricing bug in pricing.py"))
    for index, path in enumerate(("database.py", "pricing.py", "auth.py", "cache.py")):
        call = ToolCall(id=f"c{index}", name="read_file", arguments={"path": path})
        conversation.add(Message.assistant(f"Reading {path}.", [call]))
        result = Message.tool(call_id=call.id, name="read_file", content=big(path[:3]))
        result.meta["path"] = path
        conversation.add(result)
    conversation.add(Message.user("Now fix it."))
    for index in range(KEEP_RECENT_RESULTS + 1):
        call = ToolCall(id=f"n{index}", name="read_file", arguments={"path": "notes.md"})
        conversation.add(Message.assistant("Reading notes.", [call]))
        result = Message.tool(call_id=call.id, name="read_file", content="short")
        result.meta["path"] = "notes.md"
        conversation.add(result)
    return conversation


def an_agent(config, scripts, history=None):
    bus = EventBus()
    gateway = Gateway(config, scripts=scripts)
    return AgentLoop(config, gateway, ToolRegistry(), bus,
                     PermissionEngine(config, bus), history or a_history())


def test_the_compaction_summary_usage_is_counted(config):
    summary = Usage(input_tokens=111, output_tokens=22, cached_tokens=333,
                    written_tokens=44)
    agent = an_agent(config, [Script(text="the brief", usage=summary)])
    assert agent.conversation.usage.total == 0

    removed = agent.conversation.compact(agent._summarise, keep_recent=4)

    assert removed > 0
    assert agent.conversation.compactions == 1
    assert agent.conversation.usage.total == summary.total
    assert agent.conversation.usage.input_tokens == 111
    assert agent.conversation.usage.output_tokens == 22
    assert agent.conversation.usage.cached_tokens == 333
    assert agent.conversation.usage.written_tokens == 44


def test_a_turn_that_compacts_counts_both_provider_calls(config):
    """main usage = A, summary usage = B, reported end-to-end usage = A + B."""
    config.agent.compact_at = 0.002                 # pressure at once
    summary = Usage(input_tokens=100, output_tokens=10)
    main = Usage(input_tokens=7, output_tokens=3)
    agent = an_agent(config, [Script(text="brief", usage=summary),
                              Script(text="done", usage=main)])
    agent._window = lambda: 1_000_000

    agent.run("Fix the pricing bug")

    assert agent.conversation.compactions >= 1
    assert agent.conversation.usage.total == summary.total + main.total
    assert agent.conversation.usage.input_tokens == 100 + 7
    assert agent.conversation.usage.output_tokens == 10 + 3


def test_a_run_without_compaction_has_no_summary_usage(config):
    """No pressure, no summary: the total is the main call's alone."""
    main = Usage(input_tokens=7, output_tokens=3)
    agent = an_agent(config, [Script(text="done", usage=main)])
    agent._window = lambda: 10_000_000

    agent.run("Fix the pricing bug")

    assert agent.conversation.compactions == 0
    assert agent.conversation.usage.total == main.total


def test_every_compaction_counts_its_own_summary(config):
    """Two real summaries are two provider calls, each counted once."""
    one = Usage(input_tokens=100, output_tokens=10)
    two = Usage(input_tokens=200, output_tokens=20)
    agent = an_agent(config, [Script(text="first brief", usage=one),
                              Script(text="second brief", usage=two)])

    first = agent.conversation.compact(agent._summarise, keep_recent=4)
    assert first > 0
    # A settled seam and enough history for a second cut.
    for index in range(6):
        call = ToolCall(id=f"m{index}", name="read_file", arguments={"path": "more.md"})
        agent.conversation.add(Message.assistant("Reading more.", [call]))
        result = Message.tool(call_id=call.id, name="read_file", content=big("m"))
        result.meta["path"] = "more.md"
        agent.conversation.add(result)
    agent.conversation.add(Message.user("And again."))
    second = agent.conversation.compact(agent._summarise, keep_recent=2)

    assert second > 0
    assert agent.conversation.compactions == 2
    assert agent.conversation.usage.total == one.total + two.total


def test_a_failed_summary_adds_no_usage(config):
    """A summary that raises is not a call that was made: no phantom usage."""
    agent = an_agent(config, [Script(text="", error="summary provider failed")])

    removed = agent.conversation.compact(agent._summarise, keep_recent=4)

    assert removed == 0
    assert agent.conversation.compactions == 0
    assert agent.conversation.usage.total == 0


def test_the_report_documents_name_their_accounting_version():
    """A result is only comparable with one counted the same way, and the
    counting changed; the version is how a reader tells a corrected total
    from a historical one."""
    from bench import report

    assert report.TOKEN_ACCOUNTING_VERSION == 2
    plain = report.as_json([], provider="fake", model="fake-1", tries=3)
    paired = report.as_paired_json([], [], provider="fake", model="fake-1", tries=3)
    assert plain["token_accounting_version"] == 2
    assert paired["token_accounting_version"] == 2
