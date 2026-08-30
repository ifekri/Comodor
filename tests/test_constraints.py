"""What the user said not to do, put back where it applies.

Every `careful` failure the benchmark finds has one shape. The user says "do
not invent the coordinates" or "only `importer.py`", the model reads it, works
for twenty steps, and by the time it writes a file that sentence is thousands
of tokens up the context behind everything it has read since. It does the
forbidden thing — not out of defiance, but because the instruction is no longer
where it is looking.

So the prohibitions come out of the request once and go back on the result of a
write, which is the last thing the model reads before deciding what to do next.

What is checked most here is restraint. This restates; it does not judge. A
rule it cannot understand well enough to enforce is a rule it must not pretend
to enforce, because a wrong refusal costs more than a forgotten instruction.
"""

from __future__ import annotations

import pytest

from comodor.agent.constraints import MOST, prohibitions, reminder, unwrap

# --------------------------------------------------------------------------- #
# what counts as a rule
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("said", [
    "Do not change the tests.",
    "Don't touch anything else.",
    "Never write to that directory.",
    "The tests are correct and must not be changed.",
    "Make the whole suite pass without changing any test.",
    "Nothing else in this project is in scope.",
    "Leave the exporter alone.",
])
def test_a_prohibition_is_found(said):
    assert prohibitions(f"Fix the bug in a.py. {said}") == [said]


@pytest.mark.parametrize("said", [
    "Fix the failing test.",
    "Rename the function everywhere it appears.",
    "Add a --json flag to the script.",
    "The suite should go green.",
])
def test_an_instruction_is_not_a_prohibition(said):
    assert prohibitions(said) == []


def test_a_report_about_a_rule_is_not_a_rule():
    """"I did not change the tests" is somebody saying what happened."""
    assert prohibitions("I did not change the tests.") == []


def test_only_is_a_rule_when_it_is_about_scope():
    """"only" carries a prohibition in "only importer.py" and none at all in
    "it only takes a second"."""
    assert prohibitions("Change only importer.py, nothing else.")
    assert prohibitions("This only takes a second.") == []


# --------------------------------------------------------------------------- #
# a wrapped request is still one sentence
# --------------------------------------------------------------------------- #


def test_a_sentence_split_by_a_hard_wrap_is_kept_whole():
    """Requests are written in a terminal and wrapped at eighty columns. The
    first version cut "do not write a stand-in table" after "stand-in", and
    half a rule restated at the point of action reads as though something was
    lost — which it was."""
    wrapped = ("Get the suite green.\n\n"
               "Do not make any up, and do not write a stand-in\n"
               "table — a wrong coordinate is worse than an error.")

    found = prohibitions(wrapped)

    assert found and "stand-in table" in found[0]


def test_a_bullet_list_is_not_joined_into_one_sentence():
    text = unwrap("Rules:\n- do not touch a.py\n- do not touch b.py\n")

    assert "- do not touch a.py" in text.splitlines()
    assert "- do not touch b.py" in text.splitlines()


def test_a_blank_line_still_separates():
    assert unwrap("first line\n\nsecond line").splitlines() == [
        "first line", "", "second line"]


# --------------------------------------------------------------------------- #
# what it will not do
# --------------------------------------------------------------------------- #


def test_a_paragraph_is_not_a_rule():
    """Restating a paragraph at the point of action is noise, and noise is
    what makes a reminder ignorable."""
    essay = ("Do not " + "consider the implications of anything at all " * 8
             + "under any circumstances.")

    assert prohibitions(essay) == []


def test_it_carries_at_most_a_few():
    text = "\n".join(f"Do not touch file{n}.py." for n in range(10))

    assert len(prohibitions(text)) == MOST


def test_the_same_rule_twice_is_carried_once():
    text = "Do not change the tests. Fix a.py. Do not change the tests."

    assert prohibitions(text) == ["Do not change the tests."]


def test_nothing_said_means_nothing_shown():
    assert prohibitions("") == []
    assert reminder([]) == ""


# --------------------------------------------------------------------------- #
# how it reads
# --------------------------------------------------------------------------- #


def test_one_rule_reads_as_a_quotation():
    said = reminder(["Do not change the tests."])

    assert said == "You were asked: Do not change the tests."
    assert "violat" not in said.lower(), "it restates, it does not accuse"


def test_several_rules_are_listed():
    said = reminder(["Do not touch a.py.", "Do not touch b.py."])

    assert said.count("  - ") == 2


# --------------------------------------------------------------------------- #
# where it appears
# --------------------------------------------------------------------------- #


def test_a_write_carries_it(tool_context):
    from comodor.tools.fs import WriteFile

    tool_context.rules = ["Do not change the tests."]

    result = WriteFile().run(tool_context, path="a.py", content="x = 1\n")

    assert "You were asked: Do not change the tests." in result.content


def test_an_edit_carries_it(tool_context):
    from comodor.tools.fs import EditFile

    (tool_context.cwd / "a.py").write_text("x = 1\n", encoding="utf-8")
    tool_context.rules = ["Leave b.py alone."]

    result = EditFile().run(tool_context, path="a.py",
                            old_string="x = 1", new_string="x = 2")

    assert "Leave b.py alone." in result.content


def test_it_is_said_once_and_not_on_every_write(tool_context):
    """A reminder on every write is one nobody reads."""
    from comodor.tools.fs import WriteFile

    tool_context.rules = ["Do not change the tests."]
    tool = WriteFile()

    first = tool.run(tool_context, path="a.py", content="x = 1\n")
    second = tool.run(tool_context, path="b.py", content="y = 2\n")

    assert "You were asked" in first.content
    assert "You were asked" not in second.content


def test_a_read_does_not_carry_it(tool_context):
    """It belongs where a decision is about to be made, not on everything."""
    from comodor.tools.fs import ReadFile

    (tool_context.cwd / "a.py").write_text("x = 1\n", encoding="utf-8")
    tool_context.rules = ["Do not change the tests."]

    assert "You were asked" not in ReadFile().run(
        tool_context, path="a.py").content


def test_a_turn_with_no_rules_costs_nothing(tool_context):
    from comodor.tools.fs import WriteFile

    result = WriteFile().run(tool_context, path="a.py", content="x = 1\n")

    assert result.content == "Wrote a.py (1 lines, +1/-0)."


def test_the_write_still_says_what_it_did(tool_context):
    from comodor.tools.fs import WriteFile

    tool_context.rules = ["Do not change the tests."]

    result = WriteFile().run(tool_context, path="a.py", content="x = 1\n")

    assert result.content.startswith("Wrote a.py")
    assert result.meta.get("diff") is True
