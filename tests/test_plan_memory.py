"""The plan outliving the context that held it.

`todo_write` was already there and the agent already used it. What was missing
is that the list only ever reached the sidebar: compaction summarised away the
tool results carrying it, and `--resume` restored the transcript without it. On
a long job — the only kind that has a plan — the model stopped being able to
see the plan at exactly the point it needed one.
"""

from __future__ import annotations

import json

import pytest

from comodor.agent import plan
from comodor.session import SessionMeta, SessionStore
from comodor.tools.base import TodoItem


def a_plan(*states: str) -> list[TodoItem]:
    return [TodoItem(text=f"step {i}", state=state)
            for i, state in enumerate(states, start=1)]


# --------------------------------------------------------------------------- #
# what gets said
# --------------------------------------------------------------------------- #


def test_the_block_carries_every_item_and_its_state():
    block = plan.render(a_plan("done", "active", "pending"))

    assert "[x] step 1" in block
    assert "[>] step 2" in block
    assert "[ ] step 3" in block
    assert "1/3 done." in block


def test_a_blocked_item_is_not_reported_as_pending():
    """The two mean opposite things: one is waiting its turn, the other has
    stopped and needs a decision."""
    assert "[!] step 1" in plan.render(a_plan("blocked", "pending", "pending"))


def test_a_short_list_says_nothing():
    """Two items is not a plan, and a reminder about it costs more than it
    carries."""
    assert plan.render(a_plan("done", "pending")) == ""
    assert plan.render([]) == ""


def test_a_long_list_is_not_repeated_whole():
    """This arrives when the context is already under pressure. A fifty-item
    list re-injected in full is the opposite of the point."""
    block = plan.render(a_plan(*(["pending"] * 60)))

    assert block.count("[ ] step") == plan.MOST
    assert "and 35 more" in block


def test_items_without_text_are_dropped_not_rendered_blank():
    block = plan.render([TodoItem(text="real"), TodoItem(text="  "),
                         TodoItem(text="also real"), TodoItem(text="third")])

    assert "0/3 done." in block, "the blank item is still being counted"
    assert block.count("[ ]") == 3


def test_an_unknown_state_reads_as_pending_rather_than_breaking():
    block = plan.render([{"text": "a", "state": "nonsense"},
                         {"text": "b", "state": "done"},
                         {"text": "c"}])

    assert "[ ] a" in block
    assert "[x] b" in block


def test_plain_dictionaries_work_as_well_as_items():
    """The live list holds `TodoItem`s; the session file holds dictionaries.
    Both reach this."""
    from_items = plan.render(a_plan("done", "active", "pending"))
    from_records = plan.render([{"text": f"step {i}", "state": s}
                                for i, s in enumerate(
                                    ("done", "active", "pending"), start=1)])

    assert from_items == from_records


def test_the_block_says_what_to_do_with_it():
    """A list with no instruction is a list the model may read as a report on
    somebody else's work."""
    block = plan.render(a_plan("done", "active", "pending"))

    assert "todo_write" in block, "it never says how to correct a wrong plan"
    assert "[>]" in plan.FOOTING


# --------------------------------------------------------------------------- #
# when it gets said
# --------------------------------------------------------------------------- #


class Loop:
    """The two attributes `_repeat_the_plan` touches."""

    def __init__(self, todos, conversation):
        from comodor.agent.loop import AgentLoop

        self.tool_context = type("Ctx", (), {"todos": todos})()
        self.conversation = conversation
        self._repeat_the_plan = AgentLoop._repeat_the_plan.__get__(self)


class Recorder:
    def __init__(self):
        self.messages = []

    def add(self, message):
        self.messages.append(message)


def test_compaction_puts_the_plan_back():
    recorder = Recorder()
    Loop(a_plan("done", "active", "pending"), recorder)._repeat_the_plan()

    assert len(recorder.messages) == 1
    assert "[>] step 2" in recorder.messages[0].content


def test_it_is_appended_never_folded_into_the_prefix():
    """The system prompt is what the provider's cache matches on. A plan that
    changed it would miss the cache on every request of every turn."""
    recorder = Recorder()
    Loop(a_plan("done", "active", "pending"), recorder)._repeat_the_plan()

    assert recorder.messages[0].role.value == "user"


def test_nothing_is_said_when_there_is_no_plan():
    recorder = Recorder()
    Loop([], recorder)._repeat_the_plan()

    assert recorder.messages == []


def test_a_turn_does_not_fail_because_of_a_reminder_about_itself():
    """A bug in here must cost the reminder, not the turn."""
    class Exploding:
        @property
        def todos(self):
            raise RuntimeError("boom")

    from comodor.agent.loop import AgentLoop

    loop = type("L", (), {})()
    loop.tool_context = Exploding()
    loop.conversation = Recorder()
    AgentLoop._repeat_the_plan(loop)

    assert loop.conversation.messages == []


def test_a_loop_that_has_run_no_tools_yet_says_nothing():
    from comodor.agent.loop import AgentLoop

    loop = type("L", (), {})()
    loop.tool_context = None
    loop.conversation = Recorder()
    AgentLoop._repeat_the_plan(loop)

    assert loop.conversation.messages == []


def test_a_real_compaction_leaves_the_plan_in_the_history(config, bus):
    """The whole feature, driven through `_maybe_compact` rather than asserted
    against its source: a history long enough to compact, compacted, and the
    plan readable in what is left.
    """
    from comodor.agent.context import Conversation
    from comodor.agent.loop import AgentLoop
    from comodor.providers.base import Message
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry

    conversation = Conversation()
    for i in range(40):
        conversation.add(Message.user(f"message {i} " + "padding " * 200))

    loop = AgentLoop(config, gateway=None, tools=ToolRegistry(), bus=bus,
                     permissions=PermissionEngine(config, bus),
                     conversation=conversation)
    loop._summarise = lambda messages: "a summary that mentions no checklist"
    loop._tool_context().todos[:] = a_plan("done", "active", "pending")

    config.agent.context_limit = 4_000
    config.agent.compact_at = 0.5
    loop._maybe_compact("", [])

    assert conversation.compactions == 1, "the history never compacted"
    history = "\n".join(message.content for message in conversation.messages)
    assert "[>] step 2" in history, \
        "the plan did not survive the compaction that removed it"


def test_the_plan_is_repeated_after_compaction_not_before():
    """Before, the plan is still in the history and the reminder is waste; the
    order is what makes it a fix rather than a duplicate."""
    import inspect

    from comodor.agent.loop import AgentLoop

    source = inspect.getsource(AgentLoop._maybe_compact)

    assert source.index("self.conversation.compact(") \
        < source.index("_repeat_the_plan()")


# --------------------------------------------------------------------------- #
# surviving the process
# --------------------------------------------------------------------------- #


def test_the_plan_is_written_with_the_session(tmp_path):
    store = SessionStore(tmp_path)
    meta = SessionMeta(id="s1", todos=plan.as_records(
        a_plan("done", "active", "pending")))
    store.save_meta(meta)

    assert store.load_meta("s1").todos == [
        {"text": "step 1", "state": "done"},
        {"text": "step 2", "state": "active"},
        {"text": "step 3", "state": "pending"},
    ]


def test_a_session_saved_before_this_existed_still_loads(tmp_path):
    """Every session file already on disk lacks the field."""
    store = SessionStore(tmp_path)
    store.meta_path("old").write_text(json.dumps(
        {"id": "old", "title": "before", "messages": 4}), encoding="utf-8")

    meta = store.load_meta("old")

    assert meta is not None and meta.title == "before"
    assert meta.todos == []


def test_as_records_drops_what_cannot_be_restored():
    assert plan.as_records([TodoItem(text=""), TodoItem(text="real")]) == [
        {"text": "real", "state": "pending"}]


def test_as_records_survives_a_round_trip_through_json():
    records = plan.as_records(a_plan("done", "blocked"))

    assert json.loads(json.dumps(records)) == records


@pytest.mark.parametrize("method", ["_restore_plan"])
def test_resume_restores_the_plan_for_the_agent_not_only_the_sidebar(method):
    """A resumed session whose plan reaches only `state.history` gives the
    person a list they can see and the agent cannot."""
    import inspect

    from comodor.ui.app import App

    source = inspect.getsource(getattr(App, method))

    assert "state.history.todos" in source, "the sidebar is not restored"
    assert "context.todos" in source, "the agent's own list is not restored"
    assert inspect.getsource(App._resume).count(method) == 1, \
        "resume never restores the plan"
