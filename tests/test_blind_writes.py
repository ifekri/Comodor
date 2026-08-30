"""Replacing a file nobody has looked at.

`write_file` replaces everything. Doing that to a file whose contents are
unknown is how the rest of it disappears, and the benchmark caught it twice in
one run: a task was failed for overwriting the sample it was being measured
against, in an attempt whose actual work was correct.

The tool's own description already says to prefer `edit_file` for a change to
an existing file. Saying it once at the top of a schema is not the same as
saying it at the moment it matters.

This is a warning and not a refusal, and that distinction is the whole design.
Rewriting a generated file, replacing something read in an earlier session, and
creating a file are all ordinary, and a tool that refused them would be a tool
people work around.
"""

from __future__ import annotations

from comodor.tools.fs import EditFile, ReadFile, WriteFile


def write(ctx, path, content):
    return WriteFile().run(ctx, path=path, content=content)


def given(ctx, name, body):
    (ctx.cwd / name).write_text(body, encoding="utf-8", newline="")
    return ctx.cwd / name


# --------------------------------------------------------------------------- #
# what it is for
# --------------------------------------------------------------------------- #


def test_replacing_an_unread_file_says_so(tool_context):
    given(tool_context, "notes.md", "one\ntwo\nthree\nfour\n")

    result = write(tool_context, "notes.md", "replaced\n")

    assert result.ok, "it is a warning, not a refusal"
    assert "WARNING" in result.content
    assert "4 lines" in result.content
    assert "edit_file" in result.content, "it should say what to do instead"


def test_the_warning_says_the_change_can_be_undone(tool_context):
    given(tool_context, "notes.md", "one\ntwo\n")

    result = write(tool_context, "notes.md", "gone\n")

    assert "/undo" in result.content


# --------------------------------------------------------------------------- #
# when it must stay quiet
# --------------------------------------------------------------------------- #


def test_creating_a_file_is_not_a_blind_write(tool_context):
    result = write(tool_context, "new.md", "hello\n")

    assert "WARNING" not in result.content


def test_reading_the_whole_file_first_settles_it(tool_context):
    given(tool_context, "notes.md", "one\ntwo\n")
    ReadFile().run(tool_context, path="notes.md")

    result = write(tool_context, "notes.md", "replaced\n")

    assert "WARNING" not in result.content


def test_a_second_write_does_not_warn_about_the_first(tool_context):
    """What put the contents there was the call before it."""
    write(tool_context, "made.py", "x = 1\n")

    result = write(tool_context, "made.py", "x = 2\n")

    assert "WARNING" not in result.content


def test_an_edit_is_never_a_blind_write(tool_context):
    """`edit_file` matches an exact string, so it cannot destroy what it has
    not seen — that is the whole reason to prefer it."""
    given(tool_context, "app.py", "def f():\n    return 1\n")

    result = EditFile().run(tool_context, path="app.py",
                            old_string="return 1", new_string="return 2")

    assert "WARNING" not in result.content


def test_a_partial_read_is_not_knowing_the_file(tool_context):
    """Twenty lines of a thousand-line file is not the file. Counting it as
    read is how the warning stops firing on the case it exists for."""
    given(tool_context, "big.py", "\n".join(f"line {n}" for n in range(200)))
    ReadFile().run(tool_context, path="big.py", offset=1, limit=20)

    result = write(tool_context, "big.py", "tiny\n")

    assert "WARNING" in result.content


# --------------------------------------------------------------------------- #
# it does not get in the way
# --------------------------------------------------------------------------- #


def test_the_file_is_still_written(tool_context):
    given(tool_context, "notes.md", "one\n")

    write(tool_context, "notes.md", "replaced\n")

    assert (tool_context.cwd / "notes.md").read_text() == "replaced\n"


def test_the_counts_and_the_diff_survive(tool_context):
    given(tool_context, "notes.md", "one\ntwo\n")

    result = write(tool_context, "notes.md", "one\nthree\n")

    assert "Wrote" in result.content and "notes.md" in result.content
    assert result.meta.get("diff") is True


def test_a_syntax_warning_and_a_blind_warning_can_both_appear(tool_context):
    given(tool_context, "app.py", "x = 1\ny = 2\n")

    result = write(tool_context, "app.py", "def broken(\n")

    assert result.content.count("WARNING") == 2, result.content
