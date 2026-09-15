"""The stable portion of the request never moves mid-task (T085, T093;
FR-050, FR-091, SC-015), and resume reuses the stored conversation (T086;
FR-054, FR-095), and recall stays within its cap (T089; FR-062, FR-092).

Project instructions are read once per turn and carried in the head at a
fixed position; a COMODOR.md saved while the agent works does not change
the head until the next turn. Mutation-checked.
"""

from __future__ import annotations

from comodor.agent import AgentLoop, Conversation
from comodor.agent.prompts import build_system_prompt
from comodor.providers.base import Role, ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry


def make_agent(config, bus, scripts):
    gateway = Gateway(config, scripts=scripts)
    return AgentLoop(config, gateway, ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation()), gateway


def heads_of(gateway):
    return [call[0].content for call in gateway.provider("fake").calls]


# --------------------------------------------------------------------------- #
# T085 / T093 — byte-identical across the steps of a task
# --------------------------------------------------------------------------- #


def test_project_instructions_are_carried_once_in_a_stable_position(config, bus):
    (config.paths.project / "COMODOR.md").write_text("Always use tabs.\n", encoding="utf-8")
    scripts = [Script(text="Reading.", tool_calls=[ToolCall(id=f"r{i}", name="list_dir",
                                                             arguments={"path": "."})])
               for i in range(3)] + [Script(text="Done.")]
    agent, gateway = make_agent(config, bus, scripts)
    agent.run("do it")
    heads = heads_of(gateway)
    assert len(heads) == 4
    assert len(set(heads)) == 1
    assert heads[0].count("Always use tabs.") == 1
    assert heads[0].index("Using tools:") < heads[0].index("Always use tabs.")


def test_an_instruction_change_mid_task_does_not_move_the_head_until_the_next_turn(config, bus):
    target = config.paths.project / "COMODOR.md"
    target.write_text("Always use tabs.\n", encoding="utf-8")

    class ChangesTheFile(Gateway):
        pass

    scripts = [Script(text="Reading.", tool_calls=[ToolCall(id="r1", name="list_dir",
                                                             arguments={"path": "."})]),
               Script(text="Reading.", tool_calls=[ToolCall(id="r2", name="list_dir",
                                                             arguments={"path": "."})]),
               Script(text="Done.")]
    agent, gateway = make_agent(config, bus, scripts)
    provider = gateway.provider("fake")
    real_stream = provider.stream

    def stream_and_edit(messages, **kwargs):
        # Somebody saves COMODOR.md while the first step is in flight.
        target.write_text("Always use spaces.\n", encoding="utf-8")
        return real_stream(messages, **kwargs)

    provider.stream = stream_and_edit
    agent.run("do it")
    heads = heads_of(gateway)
    assert len(set(heads)) == 1, "the head moved mid-task"
    assert "Always use tabs." in heads[0]

    # The next turn picks the change up.
    provider.stream = real_stream
    gateway.provider("fake").scripts = [Script(text="Done.")]
    agent.run("again")
    assert "Always use spaces." in heads_of(gateway)[-1]


def test_the_guard_is_reading_once_per_turn(config, bus, monkeypatch):
    """Mutation check: read the file on every step, and the head moves."""
    target = config.paths.project / "COMODOR.md"
    target.write_text("Always use tabs.\n", encoding="utf-8")
    scripts = [Script(text="Reading.", tool_calls=[ToolCall(id="r1", name="list_dir",
                                                             arguments={"path": "."})]),
               Script(text="Done.")]
    agent, gateway = make_agent(config, bus, scripts)
    provider = gateway.provider("fake")
    real_stream = provider.stream

    def stream_and_edit(messages, **kwargs):
        target.write_text("Always use spaces.\n", encoding="utf-8")
        return real_stream(messages, **kwargs)

    provider.stream = stream_and_edit
    # The mutation: every step reads the file afresh instead of using the
    # copy taken at the start of the turn.
    import comodor.agent.loop as loop_module

    real_build = loop_module.build_system_prompt
    monkeypatch.setattr(loop_module, "build_system_prompt",
                        lambda config, **kw: real_build(config, **{**kw, "instructions": None}))
    agent.run("do it")
    assert len(set(heads_of(gateway))) == 2, "the mutation lets the head move"
    monkeypatch.setattr(loop_module, "build_system_prompt", real_build)


def test_build_system_prompt_honours_the_instructions_it_is_handed(config):
    (config.paths.project / "COMODOR.md").write_text("From the file.\n", encoding="utf-8")
    assert "From the file." in build_system_prompt(config)
    assert "From the file." not in build_system_prompt(config, instructions="")
    assert "Handed in." in build_system_prompt(config, instructions="Handed in.")


# --------------------------------------------------------------------------- #
# T086 — resume reuses the stored conversation
# --------------------------------------------------------------------------- #


def test_resume_sends_the_stored_conversation_and_re_derives_nothing(config):
    from comodor.application import CoreService

    config.learning.enabled = True
    service = CoreService(config)
    try:
        session = service.create_session()["id"]
        handle = service.session(session)
        handle.assembly.agent.gateway = Gateway(config, scripts=[Script(text="First answer.")])
        service.send(session, "the first question")
        import threading
        ready = threading.Event()
        for _ in range(500):
            if not handle.busy:
                break
            ready.wait(0.01)
        stored_id = handle.store_id
        assert stored_id
        stored = service._store().load(stored_id)
        assert [m.content for m in stored][:2] == ["the first question", "First answer."]
        briefing = stored[0].briefing
        service.close()

        # A new service, the same store: the resumed conversation is the
        # stored one, briefing and all, with nothing recomputed.
        again = CoreService(config)
        try:
            reopened = again.open_session(stored_id)["session"]["id"]
            resumed = again.session(reopened).assembly.conversation.messages
            assert [m.content for m in resumed] == [m.content for m in stored]
            assert resumed[0].briefing == briefing
            again.session(reopened).assembly.agent.gateway = Gateway(
                config, scripts=[Script(text="Second answer.")])
            again.send(reopened, "and then?")
            for _ in range(500):
                if not again.session(reopened).busy:
                    break
                ready.wait(0.01)
            payload = again.session(reopened).assembly.agent.gateway.provider("fake").calls[0]
            sent = [m.content for m in payload if m.role is not Role.SYSTEM]
            assert sent[:2] == ["the first question", "First answer."]
            assert payload[1].briefing == briefing, "not re-derived"
        finally:
            again.close()
    finally:
        try:
            service.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# T089 — recall stays within its cap at ten times the store size
# --------------------------------------------------------------------------- #


def test_recall_stays_within_the_cap_at_ten_times_the_store_size(config, bus):
    from comodor.learning import LearningEngine
    from comodor.learning.store import Lesson

    config.learning.enabled = True
    engine = LearningEngine(config, bus)
    try:
        cap = config.learning.max_playbook_tokens
        sizes = []
        for round_number in range(1, 11):
            for index in range(20):
                engine.store.add_lesson(Lesson(
                    scope=engine.write_scope, trigger=f"situation {round_number}-{index} retry",
                    guidance="a fairly long piece of guidance about retries " * 6,
                    confidence=0.8))
            lessons = engine.recall("how should retries be handled")
            rendered = engine.render_playbook(lessons, rules=engine.active_rules())
            sizes.append(len(rendered) // 4)
        assert all(size <= cap for size in sizes), sizes
        assert len(engine.store.all_lessons()) >= 200
        assert max(sizes) - min(sizes) <= cap, "the budget does not grow with the store"
    finally:
        engine.close()
