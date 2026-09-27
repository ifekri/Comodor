"""No optimization weakens validation (T097; FR-044).

Nothing behind the funnel suppresses a clarification, skips a relevant
inspection, or truncates the evidence a decision rests on. Each is
mutation-checked: an optimization that did so would be caught here.
"""

from __future__ import annotations

from comodor import questions as forms
from comodor.agent import AgentLoop, Conversation
from comodor.agent.context import Optimizer
from comodor.events import Kind
from comodor.providers.base import Message, Role, ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry, overflow
from comodor.tools.base import ToolResult


def big(marker="x", lines=200):
    return "\n".join(f"line {n}: {marker} = {n}" for n in range(lines))


def a_question():
    return ToolCall(id="q1", name="ask", arguments={"questions": [{
        "question": "Which database?", "header": "Database", "affects": ["architecture"],
        "options": [{"label": "SQLite", "source": "request", "evidence": "SQLite"},
                    {"label": "PostgreSQL", "source": "request", "evidence": "PostgreSQL"}],
    }]})


def make_agent(config, bus, scripts):
    gateway = Gateway(config, scripts=scripts)
    return AgentLoop(config, gateway, ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation())


# --------------------------------------------------------------------------- #
# a clarification is never suppressed
# --------------------------------------------------------------------------- #


def test_a_clarification_is_raised_under_every_optimization_setting(config, bus):
    for off in ([], ["dedup"], ["budget"], ["delta", "ranking"], list(Optimizer().enabled)):
        config.agent.optimizations_off = off
        raised: list = []
        fresh_bus = type(bus)()

        def dismiss(event, seen=raised):
            if event.kind is Kind.REQUEST:
                seen.append(event)
                event.payload["request"].answer(forms.CANCELLED)

        fresh_bus.subscribe(dismiss)
        agent = make_agent(config, fresh_bus, [
            Script(text="Asking.", tool_calls=[a_question()]), Script(text="never")])
        result = agent.run("SQLite or PostgreSQL?")
        assert len(raised) == 1, off
        assert result.stopped == "clarification_required", off


def test_a_question_result_is_never_admitted_as_a_reference_or_withheld(config, bus):
    """The form and its outcome are the evidence a decision rests on; the
    funnel leaves them alone."""
    conversation = Conversation()
    conversation.add(Message.user("SQLite or PostgreSQL?"))
    body = ("The user closed the form without answering. These decisions remain "
            "unresolved:\n  - Which database?\n" + "Do not choose a default. " * 20)
    for index in range(2):
        conversation.admit(Message.tool(call_id=f"q{index}", name="ask", content=body))
    tools = [m for m in conversation.messages if m.role is Role.TOOL]
    assert all("reference" not in m.meta for m in tools), "a form is never deduplicated"
    for _ in range(8):
        conversation.add(Message.user("more"))
    conversation.withhold(1)
    assert all("withheld" not in m.meta for m in tools), "a form is never withheld"


# --------------------------------------------------------------------------- #
# relevant inspection is never skipped
# --------------------------------------------------------------------------- #


def test_a_reference_never_stops_the_agent_reading_a_file_that_changed(config, bus):
    target = config.paths.project / "a.py"
    target.write_text(big("x"), encoding="utf-8")
    agent = make_agent(config, bus, [
        Script(text="Reading.", tool_calls=[ToolCall(id="r1", name="read_file",
                                                     arguments={"path": "a.py"})]),
        Script(text="Reading again.", tool_calls=[ToolCall(id="r2", name="read_file",
                                                           arguments={"path": "a.py"})]),
        Script(text="Done."),
    ])
    provider = agent.gateway.provider("fake")
    real = provider.stream

    def change_between_reads(messages, **kwargs):
        if len(provider.calls) == 1:
            target.write_text(big("y"), encoding="utf-8")
        return real(messages, **kwargs)

    provider.stream = change_between_reads
    agent.run("read a.py twice")
    second = next(m for m in agent.conversation.messages if m.tool_call_id == "r2")
    assert "reference" not in second.meta
    assert "y = 7" in second.content or second.meta.get("delta")


# --------------------------------------------------------------------------- #
# critical evidence is never truncated away
# --------------------------------------------------------------------------- #


def test_a_failing_log_keeps_its_failure_under_every_setting(tool_context):
    log = "exit 1 in 2s\n" + "\n".join(f"case {n} PASSED" for n in range(300)) + \
          "\nFAILED tests/test_x.py::test_y - AssertionError: assert 1 == 2\n1 failed"
    for off in ([], ["log_summary"]):
        tool_context.config.agent.optimizations_off = off
        carried = overflow.contain(ToolResult.success(log, exit_code=1), tool_context,
                                   "run_shell")
        assert "AssertionError: assert 1 == 2" in carried.content, off
        assert "test_y" in carried.content, off


def test_the_guard_is_the_protected_set(monkeypatch):
    """Mutation check: unprotect the ask tool and a repeated form is admitted
    as a reference and can be withheld — which this catches."""
    from comodor.agent import context as context_module

    def build():
        conversation = Conversation()
        conversation.add(Message.user("SQLite or PostgreSQL?"))
        body = "The user closed the form without answering. " * 20
        for index in range(2):
            form = Message.tool(call_id=f"q{index}", name="ask", content=body)
            form.meta["path"] = "form"
            conversation.admit(form, path="form")
        return conversation

    monkeypatch.setattr(context_module, "PROTECTED_TOOLS", frozenset())
    mutated = build()
    assert mutated.messages[-1].meta.get("reference") == "q0", \
        "the mutation deduplicates a form"

    monkeypatch.undo()
    guarded = build()
    assert all("reference" not in m.meta for m in guarded.messages if m.role is Role.TOOL)
    for _ in range(8):
        guarded.add(Message.user("more"))
    guarded.withhold(1)
    assert all("withheld" not in m.meta for m in guarded.messages if m.role is Role.TOOL)
