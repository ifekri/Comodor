"""Reflex: learning from corrections, and the house rules it produces.

The claim being tested is specific — *fix something the agent wrote, and the
next answer already obeys* — so these tests exercise the real path: a scripted
provider writes a file, the test rewrites it the way a user would, and the next
turn's system prompt is inspected for the rule that should have appeared.
"""

from __future__ import annotations

import time

import pytest

from comodor.agent import AgentLoop, Conversation
from comodor.events import Kind
from comodor.learning import LearningEngine
from comodor.learning.rules import analyse_correction, analyse_text, scan_project
from comodor.learning.store import Rule
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import CheckpointStore, PermissionEngine
from comodor.tools import ToolRegistry


@pytest.fixture
def engine(config, bus, workspace):
    config.learning.reflect = False          # isolate Reflex from the LLM lane
    checkpoints = CheckpointStore(config.paths.checkpoints)
    return LearningEngine(config, bus, gateway=None, checkpoints=checkpoints)


# --------------------------------------------------------------------------- #
# style detection
# --------------------------------------------------------------------------- #


def test_quote_style_is_detected_from_code():
    text = "\n".join(f"value{i} = 'text {i}'" for i in range(10))
    keys = {o.key: o for o in analyse_text("a.py", text)}
    assert "quotes.style" in keys
    assert "single" in keys["quotes.style"].statement


def test_indentation_is_detected():
    spaces = "def f():\n    return 1\n\ndef g():\n    return 2\n"
    tabs = "def f():\n\treturn 1\n\ndef g():\n\treturn 2\n"
    assert "spaces" in _statement(analyse_text("a.py", spaces), "indent.style")
    assert "tabs" in _statement(analyse_text("a.py", tabs), "indent.style")


def test_annotation_convention_is_read_both_ways():
    annotated = "\n".join(f"def f{i}(x: int) -> int:\n    return x" for i in range(6))
    plain = "\n".join(f"def f{i}(x):\n    return x" for i in range(6))
    assert "Annotate" in _statement(analyse_text("a.py", annotated), "python.annotations")
    assert "not use type annotations" in _statement(
        analyse_text("a.py", plain), "python.annotations")


def test_a_file_with_nothing_to_say_produces_nothing():
    assert analyse_text("a.py", "") == []
    assert analyse_text("a.py", "x = 1\n") == []


def test_project_config_yields_workflow_rules(workspace):
    (workspace / "pyproject.toml").write_text(
        "[project]\nname='x'\n[tool.pytest.ini_options]\ntestpaths=['tests']\n"
        "[tool.ruff]\nline-length=88\n", encoding="utf-8")
    keys = {o.key for o in scan_project(workspace)}
    assert "python.tests" in keys
    assert "python.lint" in keys


def _statement(observations, key: str) -> str:
    return next((o.statement for o in observations if o.key == key), "")


# --------------------------------------------------------------------------- #
# corrections
# --------------------------------------------------------------------------- #


def test_a_quote_rewrite_is_understood():
    before = "\n".join(f'a{i} = "text"' for i in range(6))
    after = "\n".join(f"a{i} = 'text'" for i in range(6))
    observations = analyse_correction(before, after, "a.py")

    assert any(o.key == "quotes.style" and "single" in o.statement
               for o in observations)
    assert all(o.weight >= 2 for o in observations), "a correction outweighs a look"


def test_added_annotations_are_understood():
    before = "def f(x):\n    return x\n"
    after = "def f(x: int) -> int:\n    return x\n"
    assert any(o.key == "python.annotations"
               for o in analyse_correction(before, after, "a.py"))


def test_heavy_trimming_reads_as_a_verbosity_preference():
    before = "\n".join(f"line {i}" for i in range(30))
    after = "\n".join(f"line {i}" for i in range(8))
    assert any(o.key == "output.verbosity"
               for o in analyse_correction(before, after, "a.py"))


def test_an_unrelated_rewrite_teaches_nothing():
    """Guessing intent from an arbitrary diff would fill the brain with noise."""
    before = "def add(a, b):\n    return a + b\n"
    after = "def multiply(x, y):\n    return x * y\n"
    assert analyse_correction(before, after, "a.py") == []


# --------------------------------------------------------------------------- #
# the detector
# --------------------------------------------------------------------------- #


def test_a_hand_edit_after_an_agent_write_is_detected(engine, workspace):
    target = workspace / "sample.py"
    agent_wrote = "\n".join(f'value{i} = "text"' for i in range(8)) + "\n"
    engine.detector.checkpoints.snapshot(target, action="create", tool="write_file",
                                         after=agent_wrote)
    target.write_text(agent_wrote, encoding="utf-8")

    # The user rewrites it in their own style.
    target.write_text("\n".join(f"value{i} = 'text'" for i in range(8)) + "\n",
                      encoding="utf-8")

    outcome = engine.detector.scan_corrections()
    assert outcome.corrections, "the hand edit should have been noticed"
    assert outcome.corrections[0].understood
    assert any("single" in rule.statement for rule in outcome.new_rules)


def test_a_correction_is_reported_once_not_every_turn(engine, workspace):
    target = workspace / "sample.py"
    written = "\n".join(f'v{i} = "t"' for i in range(8)) + "\n"
    engine.detector.checkpoints.snapshot(target, action="create", after=written)
    target.write_text("\n".join(f"v{i} = 't'" for i in range(8)) + "\n", encoding="utf-8")

    assert engine.detector.scan_corrections().corrections
    assert not engine.detector.scan_corrections().corrections


def test_a_file_the_agent_wrote_and_nobody_touched_is_not_a_correction(engine, workspace):
    target = workspace / "sample.py"
    written = "x = 1\n"
    engine.detector.checkpoints.snapshot(target, action="create", after=written)
    target.write_text(written, encoding="utf-8")

    assert not engine.detector.scan_corrections().corrections


def test_an_old_edit_is_not_attributed_to_the_agent(engine, workspace):
    """Beyond the window the user is just working on their code."""
    from comodor.learning import signals

    target = workspace / "sample.py"
    engine.detector.checkpoints.snapshot(target, action="create", after="x = 1\n")
    target.write_text("x = 2\n", encoding="utf-8")

    entries = engine.detector.checkpoints.entries()
    assert entries
    ancient = time.time() - signals.CORRECTION_WINDOW - 60
    for entry in entries:
        entry.at = ancient
    engine.detector.checkpoints._rewrite(entries, set())

    assert not engine.detector.scan_corrections().corrections


def test_a_refused_command_becomes_a_rule(engine):
    outcome = engine.detector.record_denial("run_shell", "run: rm -rf build")
    assert outcome.new_rules
    rule = outcome.new_rules[0]
    assert rule.category == "avoid"
    assert "rm" in rule.statement
    assert rule.confident, "an explicit refusal should count immediately"


def test_a_repeated_tool_failure_becomes_a_pitfall(engine):
    from comodor.providers.base import Message

    messages = [
        Message.tool("c1", "run_shell", "Error: command not found: pnpm", is_error=True),
        Message.tool("c2", "run_shell", "Error: command not found: pnpm", is_error=True),
    ]
    outcome = engine.detector.record_retries(messages)
    assert any("run_shell" in rule.statement for rule in outcome.new_rules)


def test_one_failure_is_bad_luck_not_a_pitfall(engine):
    from comodor.providers.base import Message

    outcome = engine.detector.record_retries(
        [Message.tool("c1", "run_shell", "Error: nope", is_error=True)])
    assert not outcome.new_rules


def test_asking_the_same_thing_twice_is_recorded(engine):
    engine.detector.record_user_message("add a health endpoint to the api")
    engine.detector.record_user_message("add the health endpoint to the api please")
    engine.store.flush()

    assert any(signal.kind == "rephrase" for signal in engine.store.recent_signals())


# --------------------------------------------------------------------------- #
# rule confidence and the prompt
# --------------------------------------------------------------------------- #


def test_observations_need_repetition_but_corrections_do_not():
    observed = Rule(source="observation", support=3)
    corrected = Rule(source="correction", support=2)
    stated = Rule(source="user", support=1)

    assert not observed.confident, "three passive looks is not yet a convention"
    assert corrected.confident, "two corrections is a clear preference"
    assert stated.confident


def test_a_contested_rule_stops_being_applied():
    contested = Rule(source="observation", support=5, against=5)
    assert not contested.confident


def test_repeat_observations_accumulate_on_one_rule(engine):
    for _ in range(4):
        engine.store.observe_rule(key="quotes.style", scope=engine.write_scope,
                                  statement="Use single quotes.", detail="counted")
    rules = engine.store.all_rules()

    assert len(rules) == 1, "the same convention must not create duplicate rows"
    assert rules[0].support == 4
    assert rules[0].confident


def test_confident_rules_reach_the_system_prompt(engine):
    for _ in range(4):
        engine.store.observe_rule(key="quotes.style", scope=engine.write_scope,
                                  statement="Use single quotes for string literals.",
                                  detail="31 of 34 literals")
    playbook = engine.render_playbook([], rules=engine.active_rules())

    assert "House rules" in playbook
    assert "single quotes" in playbook


def test_an_unproven_rule_stays_out_of_the_prompt(engine):
    engine.store.observe_rule(key="quotes.style", scope=engine.write_scope,
                              statement="Use single quotes.", detail="seen once")
    assert engine.render_playbook([], rules=engine.active_rules()) == ""


def test_rules_survive_a_tight_budget_that_truncates_lessons(engine):
    """Counted facts are cheaper and more reliable than distilled prose."""
    from comodor.learning.store import Lesson

    for _ in range(4):
        engine.store.observe_rule(key="quotes.style", scope=engine.write_scope,
                                  statement="Use single quotes.", detail="counted")
    lessons = [engine.store.add_lesson(Lesson(
        scope=engine.write_scope, trigger=f"case {i}",
        guidance="a long piece of distilled guidance " * 10)) for i in range(5)]

    playbook = engine.render_playbook(lessons, max_tokens=120,
                                      rules=engine.active_rules())
    assert "single quotes" in playbook


def test_a_user_stated_rule_applies_immediately(engine):
    engine.teach_rule("Never add comments unless asked.")
    assert any("comments" in rule.statement for rule in engine.active_rules())


def test_rules_export_is_readable_and_committable(engine, workspace):
    for _ in range(4):
        engine.store.observe_rule(key="quotes.style", scope=engine.write_scope,
                                  statement="Use single quotes.",
                                  detail="31 of 34 literals")
    path = engine.export_rules()

    text = path.read_text(encoding="utf-8")
    assert path.name == "house-rules.md"
    assert "Use single quotes." in text
    assert "31 of 34 literals" in text


# --------------------------------------------------------------------------- #
# the whole loop
# --------------------------------------------------------------------------- #


def test_a_correction_changes_the_very_next_turn(config, bus, workspace):
    """The headline claim, end to end, with no model call involved in learning."""
    config.learning.reflect = False
    checkpoints = CheckpointStore(config.paths.checkpoints)
    memory = LearningEngine(config, bus, gateway=None, checkpoints=checkpoints)

    double_quoted = "\n".join(f'field{i} = "value"' for i in range(8)) + "\n"
    scripts = [
        Script(text="Writing it.", tool_calls=[ToolCall(
            id="c1", name="write_file",
            arguments={"path": "model.py", "content": double_quoted})]),
        Script(text="Done."),
        Script(text="Here is the next one."),
    ]
    gateway = Gateway(config, scripts=scripts)
    agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation(), memory)

    agent.run("create model.py")
    assert (workspace / "model.py").exists()

    # The user rewrites it in their own style — twice over, which is what a real
    # correction looks like across a file.
    (workspace / "model.py").write_text(
        "\n".join(f"field{i} = 'value'" for i in range(8)) + "\n", encoding="utf-8")

    agent.conversation = Conversation()
    agent.run("now create view.py the same way")

    provider = gateway.provider("fake")
    system_prompts = [f"{message.content} {message.briefing}" for call in provider.calls
                      for message in call]
    assert any("single quotes" in prompt for prompt in system_prompts), \
        "the correction should govern the very next turn"


def test_the_rule_is_announced_so_the_user_can_revoke_it(config, bus, workspace):
    config.learning.reflect = False
    checkpoints = CheckpointStore(config.paths.checkpoints)
    memory = LearningEngine(config, bus, gateway=None, checkpoints=checkpoints)

    seen: list = []
    bus.subscribe(lambda event: seen.append(event) if event.kind is Kind.MEMORY else None)

    target = workspace / "a.py"
    written = "\n".join(f'v{i} = "t"' for i in range(8)) + "\n"
    checkpoints.snapshot(target, action="create", after=written)
    target.write_text("\n".join(f"v{i} = 't'" for i in range(8)) + "\n", encoding="utf-8")

    memory.before_turn("next task")

    announced = [event for event in seen if event.get("action") == "rule"]
    assert announced, "a rule that starts applying must say so"
    assert announced[0].get("items")[0]["statement"]


def test_learning_from_corrections_costs_no_model_call(config, bus, workspace):
    """The whole point of the fast lane: it works with no provider at all."""
    config.learning.reflect = False
    checkpoints = CheckpointStore(config.paths.checkpoints)
    memory = LearningEngine(config, bus, gateway=None, checkpoints=checkpoints)

    target = workspace / "a.py"
    written = "\n".join(f'v{i} = "t"' for i in range(8)) + "\n"
    checkpoints.snapshot(target, action="create", after=written)
    target.write_text("\n".join(f"v{i} = 't'" for i in range(8)) + "\n", encoding="utf-8")

    outcome = memory.before_turn("anything")
    assert outcome.new_rules
    assert memory.gateway is None
