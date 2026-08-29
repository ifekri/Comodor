"""Telling the model what it just broke, in the same turn it broke it.

The system prompt asks for a test run after every change. Asking is not a
guarantee, and the gap between asking and getting is widest on exactly the
cheap models this is meant to help. So the file is parsed here.

Most of what is checked is the ways this feature could make things worse rather
than better: refusing a write, raising from inside a verifier, or slowing down
the hottest path in the product.
"""

from __future__ import annotations

import time

import pytest

from comodor.tools import verify
from comodor.tools.fs import EditFile, WriteFile


def write(ctx, path: str, content: str):
    return WriteFile().run(ctx, path=path, content=content)


# --------------------------------------------------------------------------- #
# what it catches
# --------------------------------------------------------------------------- #


def test_a_broken_python_file_is_named_with_its_line(tool_context):
    result = write(tool_context, "broken.py",
                   "def f():\n    return 1\n  else:\n        pass\n")

    assert result.ok, "the write itself must still succeed"
    assert "line 3" in result.content
    assert "Error" in result.content


def test_a_good_python_file_says_nothing_extra(tool_context):
    result = write(tool_context, "fine.py", "def f():\n    return 1\n")

    assert "WARNING" not in result.content


def test_an_edit_that_breaks_a_file_reports_it(tool_context):
    write(tool_context, "app.py", "def f():\n    return 1\n\n\ndef g():\n    return 2\n")

    result = EditFile().run(tool_context, path="app.py",
                            old_string="def g():\n    return 2",
                            new_string="def g(:\n    return 2")

    assert result.ok, "the edit applied; only the report changed"
    assert "WARNING" in result.content
    assert "Edited" in result.content, "the edit's own report must survive"


def test_broken_json_is_caught(tool_context):
    result = write(tool_context, "settings.json", '{"a": 1,}')

    assert "not valid JSON" in result.content


def test_broken_toml_is_caught(tool_context):
    result = write(tool_context, "thing.toml", "name = \nversion = '1'\n")

    assert "not valid TOML" in result.content


@pytest.mark.parametrize("name,body", [
    ("notes.md", "# heading\n```python\ndef ( broken\n```\n"),
    ("data.csv", "a,b\n1,2,3\n"),
    ("script.sh", "if [ -f x ; then\n"),
    ("styles.css", "body { color: }\n"),
])
def test_a_kind_it_does_not_know_is_left_alone(tool_context, name, body):
    """Silence is the right answer for a format we cannot judge. Guessing at
    one produces false alarms, and a warning that is usually wrong is worse
    than no warning."""
    result = write(tool_context, name, body)

    assert "WARNING" not in result.content


def test_an_empty_json_file_is_not_an_error(tool_context):
    """A file created empty and filled by the next edit is normal."""
    result = write(tool_context, "empty.json", "")

    assert "WARNING" not in result.content


# --------------------------------------------------------------------------- #
# the ways it could make things worse
# --------------------------------------------------------------------------- #


def test_a_broken_file_is_still_written(tool_context):
    """The bytes must land. Half a refactor leaves a file inconsistent, and the
    second edit of the pair cannot be made if the first was refused."""
    write(tool_context, "half.py", "def f(\n")

    assert (tool_context.cwd / "half.py").read_text(encoding="utf-8") == "def f(\n"


def test_a_verifier_that_raises_does_not_fail_the_edit(tool_context, monkeypatch):
    def explode(path, content):
        raise RuntimeError("the parser is having a day")

    monkeypatch.setattr(verify, "_checker", lambda path: explode)

    result = write(tool_context, "thing.py", "x = 1\n")

    assert result.ok
    assert "WARNING" not in result.content
    assert (tool_context.cwd / "thing.py").exists()


def test_it_can_be_switched_off(tool_context):
    tool_context.config.safety.verify_edits = False

    result = write(tool_context, "broken.py", "def f(\n")

    assert "WARNING" not in result.content
    assert result.ok


def test_checking_a_large_file_is_not_something_anyone_notices(tool_context):
    """It sits on the hottest path in the product. A tenth of a second per edit
    would be felt; parsing in this process is three orders off that."""
    big = "\n".join(f"def f{index}():\n    return {index}" for index in range(2000))

    started = time.monotonic()
    verify.check(tool_context.cwd / "big.py", big)
    elapsed = time.monotonic() - started

    assert elapsed < 0.5, f"parsing two thousand functions took {elapsed:.2f}s"


def test_the_warning_does_not_replace_what_the_tool_already_said(tool_context):
    """The counts and the path are what the model reads to know the edit landed.
    A verifier that overwrote them would trade one silent failure for another."""
    result = write(tool_context, "broken.py", "def f(\n")

    assert "Wrote" in result.content and "broken.py" in result.content
    assert "WARNING" in result.content


def test_a_null_byte_is_reported_rather_than_raised(tool_context):
    """How a mangled shell heredoc corrupts a source file — and the one case
    the interpreter reports with no line number attached."""
    report = verify.check(tool_context.cwd / "x.py", "x = 1\x00\n")

    assert report, "a file full of null bytes passed as valid"
    assert "null byte" in report
    assert "None" not in report, "a missing line number must not be printed"
