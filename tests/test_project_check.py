"""`agent.verify_command` — the project's own check, run before "done".

The system prompt asks the model to run the tests after a change. Asking is not
getting, and the benchmark found the gap: a task reported as complete by a model
that had run nothing at all.

With this set, "done" means "done, and the project still works" — a different
claim, and the one people actually want.

Most of what is checked here is the ways it could be worse than nothing: firing
when there was nothing to verify, looping on a failure it cannot fix, or turning
a finished task into an error because the command was mistyped.
"""

from __future__ import annotations

import sys

from comodor.agent import AgentLoop, Conversation
from comodor.agent import verify as project
from comodor.events import Kind
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry


def agent_for(config, bus, scripts):
    config.safety.auto_approve_writes = True
    config.safety.auto_approve_shell = True
    return AgentLoop(config, Gateway(config, scripts=scripts), ToolRegistry(),
                     bus, PermissionEngine(config, bus), Conversation())


def notices(bus) -> list[str]:
    seen: list[str] = []
    bus.subscribe(lambda event: seen.append(event.text)
                  if event.kind is Kind.NOTICE else None)
    return seen


def a_write(call_id="c1", path="made.py", content="x = 1\n") -> ToolCall:
    return ToolCall(id=call_id, name="write_file",
                    arguments={"path": path, "content": content})


def python_that(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


# --------------------------------------------------------------------------- #
# the command itself
# --------------------------------------------------------------------------- #


def test_a_passing_command_passes(tmp_path):
    outcome = project.run(python_that("pass"), tmp_path)

    assert outcome.ran and outcome.passed


def test_a_failing_command_brings_its_output_back(tmp_path):
    outcome = project.run(
        python_that("import sys; print('two tests failed'); sys.exit(1)"),
        tmp_path)

    assert outcome.ran and not outcome.passed
    assert "two tests failed" in outcome.output


def test_an_empty_command_does_nothing(tmp_path):
    assert project.run("   ", tmp_path).ran is False


def test_a_command_that_hangs_is_given_up_on(tmp_path):
    outcome = project.run(python_that("import time; time.sleep(30)"),
                          tmp_path, patience=2.0)

    assert outcome.ran and not outcome.passed
    assert "no result within" in outcome.output


def test_patience_is_a_ceiling_and_not_a_suggestion(tmp_path):
    """The message said "no result within 2s" after waiting twenty.

    `shell=True` starts a shell, and the check is its child. Killing the shell
    on a timeout left that child alive holding the pipes open, so the read
    carried on blocking until the command finished on its own. With the
    default patience of ten minutes, one hung command held the turn for ten
    minutes and then reported a number that had never been true.
    """
    import time

    began = time.monotonic()
    outcome = project.run(python_that("import time; time.sleep(20)"),
                          tmp_path, patience=1.0)
    took = time.monotonic() - began

    assert not outcome.passed
    assert took < 8, \
        f"waited {took:.0f}s for a 1s ceiling — the child outlived the shell"


def test_giving_up_does_not_leave_the_command_running(tmp_path):
    """A check that starts workers — `pytest -n`, a bundler — leaves them
    behind if only the shell is killed. They then run on against the user's
    project after the turn that started them was abandoned.

    The witness file is written after a delay the run is not allowed to reach,
    so its absence a moment later means the process really is gone rather than
    merely detached from.
    """
    import time

    witness = tmp_path / "still-here"
    project.run(
        python_that(f"import time; time.sleep(3); "
                    f"open({str(witness)!r}, 'w').write('x')"),
        tmp_path, patience=0.5)

    time.sleep(4)

    assert not witness.exists(), "the command outlived the turn that ran it"


def test_enormous_output_is_cut_from_the_front(tmp_path):
    """A failing suite prints megabytes and the useful part is at the end."""
    outcome = project.run(
        python_that("import sys; print('x' * 200000); sys.exit(1)"), tmp_path)

    assert len(outcome.output) < project.MOST + 200


def test_the_check_cannot_call_the_agent_back(tmp_path):
    """A check that shells out to Comodor would be a loop with a bill on it."""
    outcome = project.run(
        python_that("import os; print(os.environ.get('COMODOR_VERIFYING'))"),
        tmp_path)

    assert outcome.output.strip() == "1"


# --------------------------------------------------------------------------- #
# in the loop
# --------------------------------------------------------------------------- #


def test_it_does_not_run_when_nothing_changed(config, bus):
    """A turn that read files and answered a question has nothing to verify,
    and a suite run for it is a minute of somebody's time for no information."""
    config.agent.verify_command = python_that("import sys; sys.exit(1)")
    seen = notices(bus)

    scripts = [
        Script(text="Looking.", tool_calls=[
            ToolCall(id="c1", name="list_dir", arguments={"path": "."})]),
        Script(text="Nothing to change."),
    ]
    agent_for(config, bus, scripts).run("what is here")

    assert not any("fails" in text for text in seen), seen


def test_a_passing_check_is_reported_and_the_turn_ends(config, bus):
    config.agent.verify_command = python_that("pass")
    seen = notices(bus)

    result = agent_for(config, bus, [
        Script(text="Writing.", tool_calls=[a_write()]),
        Script(text="Done."),
    ]).run("make a file")

    assert result.stopped == "done"
    assert any("passed" in text for text in seen), seen


def test_a_failing_check_gives_the_model_one_more_turn(config, bus):
    config.agent.verify_command = python_that(
        "import sys; print('AssertionError: 1 != 2'); sys.exit(1)")

    result = agent_for(config, bus, [
        Script(text="Writing.", tool_calls=[a_write()]),
        Script(text="Done."),
        Script(text="Fixed it properly."),
    ]).run("make a file")

    assert result.text == "Fixed it properly."


def test_the_model_is_shown_the_output(config, bus):
    config.agent.verify_command = python_that(
        "import sys; print('AssertionError: 1 != 2'); sys.exit(1)")

    agent = agent_for(config, bus, [
        Script(text="Writing.", tool_calls=[a_write()]),
        Script(text="Done."),
        Script(text="Fixed."),
    ])
    agent.run("make a file")

    said = " ".join(message.content for message in agent.conversation.messages)
    assert "AssertionError: 1 != 2" in said
    assert "do not change unrelated code" in said, \
        "it should not invite a change that only makes the command pass"


def test_it_runs_once_and_does_not_loop(config, bus):
    """A model that cannot fix a failing suite on its first try will not fix it
    on its fifth, and the user is better told than billed."""
    config.agent.verify_command = python_that("import sys; sys.exit(1)")

    result = agent_for(config, bus, [
        Script(text="Writing.", tool_calls=[a_write()]),
        Script(text="Done."),
        Script(text="Still not fixed."),
        Script(text="Nor now."),
    ]).run("make a file")

    assert result.text == "Still not fixed."
    assert result.steps == 3, f"it ran {result.steps} steps"


def test_a_command_that_cannot_run_does_not_fail_the_turn(config, bus):
    """A verifier that turns a finished task into an error is one people
    switch off."""
    config.agent.verify_command = "this-command-does-not-exist --please"
    seen = notices(bus)

    result = agent_for(config, bus, [
        Script(text="Writing.", tool_calls=[a_write()]),
        Script(text="Done."),
    ]).run("make a file")

    assert result.ok
    assert result.text == "Done."
    assert any("could not be run" in text or "fails" in text for text in seen)


def test_nothing_happens_when_it_is_unset(config, bus):
    """The default, and it must cost nothing at all."""
    assert config.agent.verify_command == ""
    seen = notices(bus)

    result = agent_for(config, bus, [
        Script(text="Writing.", tool_calls=[a_write()]),
        Script(text="Done."),
    ]).run("make a file")

    assert result.text == "Done."
    assert result.steps == 2
    assert not any("Running" in text for text in seen), seen
