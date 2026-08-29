"""Saying so when an answer claims the tests pass and nothing ran them.

The one failure a programmer does not forgive. Everything else about a coding
agent is visible — a wrong diff can be read, slowness can be waited out — but
"the tests pass now" when nothing was run reads exactly like the truth, and
once somebody has been caught by it every other claim the tool makes is worth
less.

Most of what is checked here is the *false* positives, because a notice that is
sometimes wrong is one people learn to scroll past, and then it protects
nobody. The bar is four conditions and all four have to hold.
"""

from __future__ import annotations

import pytest

from comodor.agent.claims import unverified

EDITED = ["read_file", "edit_file"]
RAN = ["read_file", "edit_file", "run_shell"]


# --------------------------------------------------------------------------- #
# what it is for
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("answer", [
    "Fixed the off-by-one in page_count. The tests pass.",
    "I updated the branch condition. All tests pass now.",
    "Done — the suite passes.",
    "Renamed both functions; the build succeeds.",
    "Extracted the shared helper. Everything passes.",
])
def test_a_plain_claim_with_nothing_run_is_noticed(answer):
    notice = unverified(answer, EDITED)

    assert notice, f"went unnoticed: {answer!r}"
    assert "Nothing was run" in notice


def test_the_notice_quotes_the_sentence_it_is_about():
    """So the user can see which claim, rather than being told one exists."""
    notice = unverified(
        "I rewrote the parser and tidied the imports. The tests pass.", EDITED)

    assert "The tests pass" in notice


def test_it_says_what_to_do_next():
    notice = unverified("Done, the suite passes.", EDITED)

    assert "run the tests" in notice


# --------------------------------------------------------------------------- #
# the false positives, which are what would make it useless
# --------------------------------------------------------------------------- #


def test_a_claim_backed_by_a_command_is_left_alone():
    """The user has the output. Nothing here can add to it."""
    assert not unverified("Fixed it. The tests pass.", RAN)


@pytest.mark.parametrize("tools", [
    ["read_file", "grep"],
    ["list_dir"],
    [],
])
def test_a_turn_that_changed_nothing_is_left_alone(tools):
    """With nothing edited there is nothing to have broken, and the sentence is
    far likelier to be about something else — describing the project, quoting a
    README, answering a question about how it is set up."""
    assert not unverified("As it stands the tests pass.", tools)


@pytest.mark.parametrize("answer", [
    "Make sure the tests pass before you merge.",
    "Run pytest and check that the tests pass.",
    "The tests do not pass yet — I could not find the fixture.",
    "The tests still fail; the data file is missing.",
    "If the tests pass, this is ready.",
    "Once the tests pass you can push it.",
    "I would expect the tests pass afterwards, but I have not run them.",
    "This should make the build succeed.",
    "I was unable to confirm the tests pass.",
])
def test_a_hedge_an_instruction_or_a_denial_is_not_a_claim(answer):
    assert not unverified(answer, EDITED), f"wrongly flagged: {answer!r}"


def test_an_honest_admission_is_never_flagged():
    """The behaviour being encouraged must not be the behaviour punished."""
    answer = ("I changed the comparison in pricing.py. I have not run the "
              "suite, so I cannot say whether the tests pass.")

    assert not unverified(answer, EDITED)


def test_an_empty_answer_says_nothing():
    assert not unverified("", EDITED)


def test_a_very_long_sentence_is_shortened_in_the_notice():
    long_claim = ("Having reconciled the two parsers and the three callers "
                  "that reach them, top to bottom, the tests pass")

    notice = unverified(long_claim, EDITED)

    assert notice, "a long sentence is still a claim"
    assert "…" in notice, "the notice should not repeat a whole paragraph"


# --------------------------------------------------------------------------- #
# wired into the loop
# --------------------------------------------------------------------------- #


def test_the_loop_says_it_next_to_the_answer(config, bus):
    from comodor.agent import AgentLoop, Conversation
    from comodor.events import Kind
    from comodor.providers.base import ToolCall
    from comodor.providers.fake import Script
    from comodor.providers.gateway import Gateway
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry

    notices = []
    bus.subscribe(lambda event: notices.append(event.text)
                  if event.kind is Kind.NOTICE else None)

    config.safety.auto_approve_writes = True
    scripts = [
        Script(text="Fixing it.", tool_calls=[
            ToolCall(id="c1", name="write_file",
                     arguments={"path": "a.py", "content": "x = 2\n"})]),
        Script(text="Done — the tests pass."),
    ]
    agent = AgentLoop(config, Gateway(config, scripts=scripts), ToolRegistry(),
                      bus, PermissionEngine(config, bus), Conversation())
    agent.run("fix it")

    assert any("Nothing was run" in text for text in notices), notices


def test_the_loop_stays_quiet_when_a_command_ran(config, bus):
    from comodor.agent import AgentLoop, Conversation
    from comodor.events import Kind
    from comodor.providers.base import ToolCall
    from comodor.providers.fake import Script
    from comodor.providers.gateway import Gateway
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry

    notices = []
    bus.subscribe(lambda event: notices.append(event.text)
                  if event.kind is Kind.NOTICE else None)

    config.safety.auto_approve_writes = True
    config.safety.auto_approve_shell = True
    scripts = [
        Script(text="Fixing it.", tool_calls=[
            ToolCall(id="c1", name="write_file",
                     arguments={"path": "a.py", "content": "x = 2\n"})]),
        Script(text="Checking.", tool_calls=[
            ToolCall(id="c2", name="run_shell",
                     arguments={"command": "echo done"})]),
        Script(text="Done — the tests pass."),
    ]
    agent = AgentLoop(config, Gateway(config, scripts=scripts), ToolRegistry(),
                      bus, PermissionEngine(config, bus), Conversation())
    agent.run("fix it")

    assert not any("Nothing was run" in text for text in notices), notices
