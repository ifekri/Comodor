"""One tool result that pays for the rest of the task.

A result is written into the conversation once and resent with every request
that follows it, so its real price is its size times the number of steps still
to come. Reading one ordinary module in this repository cost 23,082 tokens —
about a quarter of a million over the ten steps a task usually takes after it.

Truncating bounds the cost and loses the content: the middle of a failing test
run is gone, and the agent answers from the half it kept. So nothing is
discarded here. What does not fit is moved, and what comes back says exactly
where it went.
"""

from __future__ import annotations

import re

from comodor.tools import overflow


def spilled_path(content: str) -> str:
    found = re.search(r"All of it is at (\S+)", content)
    assert found, f"no path in the pointer: {content[-200:]}"
    return found.group(1)


# --------------------------------------------------------------------------- #
# the budget
# --------------------------------------------------------------------------- #


def test_a_small_result_is_left_exactly_as_it_was(tools, tool_context, workspace):
    (workspace / "small.py").write_text("print('hi')\n", encoding="utf-8")

    result = tools.invoke("read_file", tool_context, {"path": "small.py"})

    assert "not shown" not in result.content
    assert not result.meta.get("overflowed")


def test_a_large_result_is_bounded(tools, tool_context, workspace):
    tool_context.config.agent.max_tool_chars = 2_000
    (workspace / "big.py").write_text("x = 1\n" * 20_000, encoding="utf-8")

    result = tools.invoke("read_file", tool_context, {"path": "big.py"})

    assert result.ok
    assert len(result.content) <= 2_400          # the pointer is allowed to spill a little
    assert result.meta["overflowed"] is True


def test_the_ends_are_what_is_kept(tool_context):
    """The end of a command's output is where the error is; the beginning is
    where the shape of it is. The middle is what a person skims past."""
    tool_context.config.agent.max_tool_chars = 1_000
    body = "\n".join(f"line {n}" for n in range(5_000))
    from comodor.tools.base import ToolResult

    result = overflow.contain(ToolResult.success(body), tool_context, "run_shell")

    assert "line 0" in result.content
    assert "line 4999" in result.content
    assert "line 2500" not in result.content


def test_what_the_user_sees_is_not_what_is_billed(tool_context):
    """The transcript pane costs nothing, so it keeps the whole thing."""
    from comodor.tools.base import ToolResult

    tool_context.config.agent.max_tool_chars = 500
    body = "y" * 20_000
    result = overflow.contain(ToolResult.success(body), tool_context, "run_shell")

    assert len(result.rendered) == 20_000
    assert len(result.content) < 1_000


def test_the_pane_is_generous_but_not_unbounded(tool_context):
    """It costs no tokens, but it is re-split on every repaint, twenty times a
    second, for the rest of the session."""
    from comodor.tools.base import ToolResult

    tool_context.config.agent.max_tool_chars = 500
    body = "z" * (overflow.DISPLAY_CHARS * 3)
    result = overflow.contain(ToolResult.success(body), tool_context, "run_shell")

    assert len(result.rendered) < overflow.DISPLAY_CHARS + 200
    assert "more]" in result.rendered


# --------------------------------------------------------------------------- #
# nothing is lost
# --------------------------------------------------------------------------- #


def test_output_that_existed_nowhere_else_is_written_down(tools, tool_context):
    """Truncation would make a long test run unrecoverable at any price."""
    tool_context.config.agent.max_tool_chars = 1_000
    from comodor.tools.base import ToolResult

    body = "\n".join(f"line {n}" for n in range(5_000))
    result = overflow.contain(ToolResult.success(body), tool_context, "run_shell")

    from pathlib import Path
    saved = Path(spilled_path(result.content))
    assert saved.is_file()
    assert saved.read_text(encoding="utf-8") == body


def test_the_pointer_can_be_followed(tools, tool_context):
    """A path the agent cannot then read is a promise the tool does not keep."""
    tool_context.config.agent.max_tool_chars = 1_000
    from comodor.tools.base import ToolResult

    body = "\n".join(f"line {n}" for n in range(5_000))
    result = overflow.contain(ToolResult.success(body), tool_context, "run_shell")

    back = tools.invoke("read_file", tool_context,
                        {"path": spilled_path(result.content), "offset": 2_501,
                         "limit": 1})

    assert back.ok, back.content
    assert "line 2500" in back.content


def test_a_file_already_on_disk_is_not_copied(tools, tool_context, workspace):
    """A second copy of a file that already exists is more wasteful than the
    problem being solved."""
    tool_context.config.agent.max_tool_chars = 1_000
    (workspace / "big.py").write_text("x = 1\n" * 20_000, encoding="utf-8")

    result = tools.invoke("read_file", tool_context, {"path": "big.py"})

    assert "big.py" in result.content
    assert "read_file using offset and limit" in result.content
    assert not overflow.directory(tool_context).exists()


def test_the_pointer_says_how_long_the_file_is(tools, tool_context, workspace):
    tool_context.config.agent.max_tool_chars = 1_000
    (workspace / "big.py").write_text("x = 1\n" * 20_000, encoding="utf-8")

    result = tools.invoke("read_file", tool_context, {"path": "big.py"})

    assert "20,000 lines" in result.content


# --------------------------------------------------------------------------- #
# it applies to everything, including what was never written here
# --------------------------------------------------------------------------- #


def test_shell_output_is_bounded_too(tools, tool_context):
    tool_context.config.agent.max_tool_chars = 800

    result = tools.invoke("run_python", tool_context,
                          {"code": "print('z' * 40000)"})

    assert result.ok
    assert len(result.content) < 1_500
    assert "All of it is at" in result.content


def test_the_shell_no_longer_cuts_before_anything_can_save_it(tools, tool_context):
    """It kept the head and tail and dropped the middle, so the saved copy was
    an already-cut one and the middle of a failing run was unrecoverable."""
    tool_context.config.agent.max_tool_chars = 1_000
    size = 200_000

    result = tools.invoke("run_python", tool_context,
                          {"code": f"print('q' * {size})"})

    from pathlib import Path
    saved = Path(spilled_path(result.content))
    assert saved.stat().st_size >= size


def test_a_failure_stays_a_failure(tool_context):
    from comodor.tools.base import ToolResult

    tool_context.config.agent.max_tool_chars = 100
    result = overflow.contain(ToolResult.failure("x" * 5_000), tool_context, "run_shell")

    assert not result.ok


def test_a_home_that_cannot_be_written_to_costs_the_copy_not_the_call(tool_context,
                                                                     monkeypatch):
    """A full disk must not turn a working tool call into a failed one."""
    from comodor.tools.base import ToolResult

    monkeypatch.setattr(overflow, "_write", lambda *a, **k: None)
    tool_context.config.agent.max_tool_chars = 500

    result = overflow.contain(ToolResult.success("w" * 9_000), tool_context, "grep")

    assert result.ok
    assert "re-run" in result.content


# --------------------------------------------------------------------------- #
# the spill is a cache, not a record
# --------------------------------------------------------------------------- #


def test_old_output_is_cleared_away(tool_context):
    import time

    from comodor.tools.base import ToolResult

    tool_context.config.agent.max_tool_chars = 500
    overflow.contain(ToolResult.success("a" * 9_000), tool_context, "grep")

    folder = overflow.directory(tool_context)
    stale = folder / "20200101-000000-grep.txt"
    stale.write_text("old", encoding="utf-8")
    import os
    ancient = time.time() - overflow.KEEP_SECONDS - 60
    os.utime(stale, (ancient, ancient))

    overflow.contain(ToolResult.success("b" * 9_000), tool_context, "grep")

    assert not stale.exists()


def test_two_results_in_the_same_second_do_not_overwrite_each_other(tool_context):
    from comodor.tools.base import ToolResult

    tool_context.config.agent.max_tool_chars = 500
    first = overflow.contain(ToolResult.success("1" * 9_000), tool_context, "grep")
    second = overflow.contain(ToolResult.success("2" * 9_000), tool_context, "grep")

    assert spilled_path(first.content) != spilled_path(second.content)
