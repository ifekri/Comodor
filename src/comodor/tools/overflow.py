"""Keeping one tool result from paying for the rest of the task.

A tool result is not paid for once. It is written into the conversation and
then resent with every request that follows it, so its real price is its size
multiplied by the number of steps still to come. Reading one ordinary module in
this repository costs 23,082 tokens; over the ten steps a task usually takes
after it, that single call is a quarter of a million tokens of billing.

Truncation is the usual answer and it is a bad one. It bounds the cost and
loses the content: the middle of a test run is gone, and if the failure was
there the agent cannot get it back at any price. It then answers from the half
it has, which is worse than not having asked.

So nothing is discarded here. What exceeds the budget is **moved**, and what
comes back is the beginning, the end, and an exact instruction for reaching the
rest:

* output the agent generated — a test run, a search, a page, an MCP reply — is
  written to a file under the user's directory, and the result names it;
* output that was *already* a file on disk — a file the agent read — is not
  copied anywhere. The pointer names the original and the lines that were
  skipped, because a second copy of a file that already exists is the one thing
  more wasteful than the problem being solved.

Both cases end in the same place: the agent has a path, a line range, and two
tools that read paths. The cost is bounded, and nothing is unreachable.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .base import ToolContext, ToolResult

#: Characters kept inline before the rest is moved aside. Four to a token,
#: roughly, so this is about three thousand tokens — enough for a stack trace,
#: a directory listing, or the interesting part of a diff, and not enough for a
#: file to dominate the conversation that follows it.
BUDGET_CHARS = 12_000
#: How the kept portion is split. The end of a command's output is where the
#: error is; the beginning is where the shape of it is.
HEAD_SHARE = 0.55
#: Files older than this are removed when a new one is written. The spill is a
#: cache of something the agent already had, not a record.
KEEP_SECONDS = 7 * 24 * 3600
#: And never more than this many, however recent.
KEEP_FILES = 200
#: What the transcript pane keeps. It costs no tokens, so it is far larger than
#: the model's share — but not unbounded: the pane re-splits this string on
#: every repaint, twenty times a second, and a megabyte of shell output would
#: be re-split a megabyte at a time for the rest of the session.
DISPLAY_CHARS = 60_000

_SAFE = re.compile(r"[^a-z0-9_-]+")


def directory(ctx: ToolContext) -> Path:
    return Path(ctx.config.paths.user) / "output"


def contain(result: ToolResult, ctx: ToolContext, tool: str) -> ToolResult:
    """Bound what one call adds to the conversation, losing nothing.

    Applied centrally rather than in each tool, so a tool added tomorrow — or
    one that arrived over MCP and was never written here at all — is covered by
    the same rule as the ones that exist today.
    """
    content = result.content or ""
    budget = _budget(ctx)
    if len(content) <= budget:
        return result

    source = result.meta.get("path")
    if source and _is_a_readable_file(source, len(content)):
        pointer = _point_at_the_original(result, Path(source), ctx)
    else:
        pointer = _point_at_a_copy(content, ctx, tool)

    kept = _head_and_tail(content, budget - len(pointer))
    return ToolResult(
        ok=result.ok,
        content=f"{kept}\n\n{pointer}",
        display=_for_the_pane(result.display or content),
        meta={**result.meta, "overflowed": True, "full_chars": len(content)},
        elapsed=result.elapsed,
    )


def _for_the_pane(text: str) -> str:
    """What the user sees. Not billed, but still redrawn twenty times a second."""
    if len(text) <= DISPLAY_CHARS:
        return text
    return text[:DISPLAY_CHARS] + f"\n\n… [{len(text) - DISPLAY_CHARS:,} more]"


def _budget(ctx: ToolContext) -> int:
    configured = getattr(ctx.config.agent, "max_tool_chars", 0)
    return int(configured) if configured else BUDGET_CHARS


def _head_and_tail(text: str, budget: int) -> str:
    """The start and the end, cut at line boundaries so nothing lands mid-token."""
    budget = max(400, budget)
    head_len = int(budget * HEAD_SHARE)
    head = text[:head_len].rsplit("\n", 1)[0]
    tail = text[-(budget - len(head)):]
    tail = tail.split("\n", 1)[-1] if "\n" in tail else tail
    dropped = len(text) - len(head) - len(tail)
    return f"{head}\n\n… [{dropped:,} characters not shown] …\n\n{tail}"


def _is_a_readable_file(path: Any, size: int) -> bool:
    """Whether the content is already on disk under its own name."""
    try:
        target = Path(str(path))
        return target.is_file() and target.stat().st_size >= size * 0.5
    except OSError:
        return False


def _point_at_the_original(result: ToolResult, path: Path, ctx: ToolContext) -> str:
    """No copy. The file is where it has always been."""
    where = ctx.relative(path)
    lines = result.meta.get("lines")
    span = f" It has {lines:,} lines." if isinstance(lines, int) and lines else ""
    return (f"[This is the head and tail only.{span} The file is unchanged at "
            f"{where} — read any part of it with read_file using offset and "
            f"limit, or find what you need in it with grep.]")


def _point_at_a_copy(content: str, ctx: ToolContext, tool: str) -> str:
    """Output that existed nowhere else, written down so it still exists."""
    target = _write(content, ctx, tool)
    if target is None:
        return ("[This is the head and tail only. The rest could not be saved, "
                "so re-run the command if you need it.]")
    return (f"[This is the head and tail of {len(content):,} characters. All of "
            f"it is at {target} — read it with read_file using offset and "
            f"limit, or search it with grep.]")


def _write(content: str, ctx: ToolContext, tool: str) -> Path | None:
    folder = directory(ctx)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        name = _SAFE.sub("-", tool.lower()) or "tool"
        target = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}.txt"
        # Two calls in the same second must not overwrite each other.
        counter = 2
        while target.exists():
            target = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}-{counter}.txt"
            counter += 1
        target.write_text(content, encoding="utf-8", errors="replace")
        _prune(folder)
        return target
    except OSError:
        # A full disk or a read-only home must not turn a working tool call
        # into a failed one; the head and tail are still useful.
        return None


def _prune(folder: Path) -> None:
    try:
        files = sorted(folder.glob("*.txt"), key=lambda p: p.stat().st_mtime,
                       reverse=True)
    except OSError:
        return
    cutoff = time.time() - KEEP_SECONDS
    for index, path in enumerate(files):
        try:
            if index >= KEEP_FILES or path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue
