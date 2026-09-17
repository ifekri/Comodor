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

import hashlib
import re
import time
from pathlib import Path
from typing import Any

from .base import ToolContext, ToolResult

#: Tools whose output is a log: a test run, a build, a script. A passing log
#: collapses to its outcome; a failing one keeps every failing case.
COMMANDS = frozenset({"run_shell", "run_python"})

#: A line that says a run passed. Kept when the rest of a passing log goes.
_PASSED = re.compile(
    r"(\b\d+ passed\b|\bpassed\b.*\bin \d|\bok\b\s*$|\ball tests passed\b"
    r"|\bbuild succeeded\b|\bcompiled successfully\b|\bsuccess\b)", re.I)

#: A line that belongs to a failure: the case, its location, its message.
_FAILING = re.compile(
    r"(\bFAILED?\b|\bERROR\b|\bError\b|\bTraceback\b|\bException\b|\bassert"
    r"|\bAssertionError\b|\bpanic\b|\bfatal\b|\bnot ok\b|\bFAIL:|^E\s{2,}"
    r"|^\s+File \".+\", line \d+|\berror\[E\d+\]|\berror:)", re.I | re.M)

#: A summary that names *zero* failures — "0 errors", "error(s): 0". A
#: successful build or test run prints these, and matching the word "error"
#: in one would carry a passing run as a failing one and invite a pointless
#: fix. A line that only says there were none is not a failing line.
_ZERO = re.compile(r"\b0\s+(?:errors?|failures?|warnings?)\b"
                   r"|\b(?:errors?|failures?)\s*[:=]\s*0\b", re.I)


def _failing_line(line: str) -> bool:
    return bool(_FAILING.search(line)) and not _ZERO.search(line)

#: How many lines around a failing line travel with it.
_AROUND = 3

#: Above this a passing log is worth collapsing; below it the log is cheap.
_LOG_WORTH = 1_500

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


def contain(result: ToolResult, ctx: ToolContext, tool: str,
            command: str = "") -> ToolResult:
    """Bound what one call adds to the conversation, losing nothing.

    Applied centrally rather than in each tool, so a tool added tomorrow — or
    one that arrived over MCP and was never written here at all — is covered by
    the same rule as the ones that exist today.
    """
    content = result.content or ""
    if tool in COMMANDS and len(content) > _LOG_WORTH and _log_summaries_on(ctx) \
            and _is_validation(tool, command, content):
        # A validation log first: a passing run collapses to its outcome, a
        # failing run to its failing cases — before the size rule, which would
        # otherwise keep an arbitrary head and tail of a log whose useful part
        # is the failure in the middle (FR-090). Only validation output is
        # collapsed this way: a large `git diff`, a JSON query or a source
        # dump is data, not a run, and its body matters.
        summarised = _summarise_log(result, content, ctx, tool)
        if summarised is not None:
            return summarised
    budget = _budget(ctx)
    if len(content) <= budget:
        return result

    source = result.meta.get("path")
    spill = ""
    if source and _is_a_readable_file(source, len(content)):
        pointer = _point_at_the_original(result, Path(source), ctx)
    else:
        pointer, spill = _point_at_a_copy(content, ctx, tool)

    kept = _head_and_tail(content, budget - len(pointer))
    return ToolResult(
        ok=result.ok,
        content=f"{kept}\n\n{pointer}",
        display=_for_the_pane(result.display or content),
        meta={**result.meta, "overflowed": True, "full_chars": len(content),
              "content_fingerprint": _full_fingerprint(content),
              **({"spill": spill} if spill else {})},
        elapsed=result.elapsed,
    )


#: Commands whose output is a validation/build/test run — the only ones the
#: passing/failing summary is written for (FR-090).
_VALIDATION_COMMAND = re.compile(
    r"(?i)\b(pytest|unittest|nose|tox|ruff|flake8|pylint|mypy|black|isort|"
    r"eslint|tsc|jest|vitest|mocha|test|tests|build|lint|check|coverage|"
    r"cargo|gradle|mvn|make|npm|yarn|pnpm|go)\b")

#: Output that reads as a validation run even without the command: a line that
#: says a case passed or failed, or a run summary naming its counts.
_VALIDATION_OUTPUT = re.compile(
    r"(?i)(\b\d+\s+(?:passed|failed|errors?|failures?|skipped)\b"
    r"|\b(?:passed|failed)\b.*\bin \d|\ball tests passed\b|\bbuild succeeded\b"
    r"|\bcompiled successfully\b|\bFAILED?\b|\bTraceback\b|\bAssertionError\b"
    r"|\b(?:errors?|failures?|warnings?)\s*[:=]\s*\d+\b)")


def _is_validation(tool: str, command: str, content: str) -> bool:
    """Whether this output is a validation run rather than arbitrary data.

    The command decides when it is known — a `git diff` or a JSON query is
    not a run. When the caller passes no command (a direct containment call),
    the output's own shape decides.
    """
    if command:
        return bool(_VALIDATION_COMMAND.search(command))
    return bool(_VALIDATION_OUTPUT.search(content))


def _full_fingerprint(content: str) -> str:
    """The identity of the whole observed content, before it was shortened.

    The conversation keeps only a head and tail, but deduplication must
    compare the *original* bytes: a change confined to the omitted middle
    leaves the visible head and tail identical, and a fingerprint of the
    shortened form would call the reread unchanged (FR-101).
    """
    import hashlib

    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]


def _log_summaries_on(ctx: ToolContext) -> bool:
    agent = getattr(ctx.config, "agent", None)
    if getattr(agent, "context_strategy", "current") == "naive":
        return False
    return "log_summary" not in set(getattr(agent, "optimizations_off", None) or ())


def _summarise_log(result: ToolResult, content: str, ctx: ToolContext,
                   tool: str) -> ToolResult | None:
    """The carried form of a command's output (FR-090, SC-027).

    Passing: the header, the outcome lines, and a pointer to the whole log.
    Failing: every failing line with its surroundings — the case, where it
    is, what it said — the tail, and the pointer. A failing run is never a
    flag: if nothing in it reads as a failure, it is carried as it was.
    """
    passed = _exit_code(result) == 0 and not any(
        _failing_line(line) for line in content.splitlines())
    lines = content.splitlines()
    pointer, spill = _point_at_a_copy(content, ctx, tool)
    if passed:
        kept = lines[:2] + [line for line in lines[2:] if _PASSED.search(line)][-6:]
        if len(kept) < 2:
            kept = lines[:2] + lines[-3:]
        body = "\n".join(kept)
        note = (f"[Passing run: {len(lines):,} lines collapsed to the outcome. "
                f"{pointer}]")
        return ToolResult(
            ok=result.ok, content=f"{body}\n\n{note}",
            display=_for_the_pane(result.display or content),
            meta={**result.meta, "overflowed": True, "log": "passed",
                  "full_chars": len(content),
                  "content_fingerprint": _full_fingerprint(content),
                  **({"spill": spill} if spill else {})},
            elapsed=result.elapsed)
    failing = [index for index, line in enumerate(lines) if _failing_line(line)]
    if not failing:
        return None
    keep: set[int] = set(range(min(2, len(lines))))
    for index in failing:
        keep.update(range(max(0, index - _AROUND), min(len(lines), index + _AROUND + 1)))
    keep.update(range(max(0, len(lines) - 5), len(lines)))
    kept_lines: list[str] = []
    previous = -1
    for index in sorted(keep):
        if previous >= 0 and index != previous + 1:
            kept_lines.append("…")
        kept_lines.append(lines[index])
        previous = index
    body = "\n".join(kept_lines)
    if len(body) >= len(content):
        return None
    note = (f"[Failing run: {len(failing)} failing line{'s' if len(failing) != 1 else ''} "
            f"kept with context out of {len(lines):,}; nothing else is claimed about "
            f"the rest. {pointer}]")
    return ToolResult(
        ok=result.ok, content=f"{body}\n\n{note}",
        display=_for_the_pane(result.display or content),
        meta={**result.meta, "overflowed": True, "log": "failed",
              "full_chars": len(content),
              "content_fingerprint": _full_fingerprint(content),
              **({"spill": spill} if spill else {})},
        elapsed=result.elapsed)


def _exit_code(result: ToolResult) -> int | None:
    code = result.meta.get("exit_code")
    return int(code) if isinstance(code, int) and not isinstance(code, bool) else None


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


def _point_at_a_copy(content: str, ctx: ToolContext, tool: str) -> tuple[str, str]:
    """Output that existed nowhere else, written down so it still exists.

    Returns the pointer and the file it names, so the path survives when the
    pointer text itself is later replaced (a withheld result must say where the
    output went, never "run the command again" — a commit or a migration is not
    safe to repeat).
    """
    target = _write(content, ctx, tool)
    if target is None:
        return ("[This is the head and tail only. The rest could not be saved, "
                "so re-run the command if you need it.]", "")
    return (f"[This is the head and tail of {len(content):,} characters. All of "
            f"it is at {target} — read it with read_file using offset and "
            f"limit, or search it with grep.]", str(target))


def _write(content: str, ctx: ToolContext, tool: str) -> Path | None:
    folder = directory(ctx)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        name = _SAFE.sub("-", tool.lower()) or "tool"
        # The same output spilled twice points at one file, not two: the
        # name carries a hash of the content, so identical results dedup
        # on disk and a changed result — a different hash — never resolves
        # to the old copy (FR-089).
        digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:12]
        target = folder / f"{name}-{digest}.txt"
        if target.exists():
            target.touch()
            _remember(ctx, target)
            return target
        target.write_text(content, encoding="utf-8", errors="replace")
        _remember(ctx, target)
        _prune(folder, keep=_referenced(ctx))
        return target
    except OSError:
        # A full disk or a read-only home must not turn a working tool call
        # into a failed one; the head and tail are still useful.
        return None


def _remember(ctx: ToolContext, target: Path) -> None:
    """A pointer handed to this session stays valid for the session: pruning
    never removes a file the conversation still points at."""
    try:
        held = getattr(ctx, "spilled", None)
        if held is None:
            held = set()
            ctx.spilled = held                      # type: ignore[attr-defined]
        held.add(str(target))
    except Exception:
        pass


def _referenced(ctx: ToolContext) -> set[str]:
    try:
        return set(getattr(ctx, "spilled", None) or ())
    except Exception:
        return set()


def _prune(folder: Path, keep: set[str] | None = None) -> None:
    try:
        files = sorted(folder.glob("*.txt"), key=lambda p: p.stat().st_mtime,
                       reverse=True)
    except OSError:
        return
    cutoff = time.time() - KEEP_SECONDS
    protected = keep or set()
    for index, path in enumerate(files):
        if str(path) in protected:
            continue
        try:
            if index >= KEEP_FILES or path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue
