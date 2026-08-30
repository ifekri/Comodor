"""Filesystem tools: read, write, edit, list.

Two decisions shape this module.

*Edits are exact-match replacements, not line numbers.* Line numbers drift the
moment anything else changes; an anchored string either matches or it does not,
and an ambiguous match is reported rather than guessed at.

*Every mutation is checkpointed first.* By the time a write happens the old
bytes are already in the checkpoint store, so ``/undo`` always has something to
restore.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from ..safety import Risk
from . import matching, verify
from .base import Tool, ToolContext, ToolResult

BINARY_SNIFF = 8000
TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "cp1252", "latin-1")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def read_text(path: Path, limit: int) -> tuple[str, str]:
    """Return ``(text, error)``; binary and oversized files are refused."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        return "", str(exc)
    if size > limit:
        return "", (f"file is {size:,} bytes, over the {limit:,} byte limit — "
                    "read a slice with offset/limit instead")

    try:
        raw = path.read_bytes()
    except OSError as exc:
        return "", str(exc)
    if b"\x00" in raw[:BINARY_SNIFF]:
        return "", "file appears to be binary"

    for encoding in TEXT_ENCODINGS:
        try:
            return raw.decode(encoding), ""
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), ""


def read_window(path: Path, start: int, count: int, cap: int
                ) -> tuple[list[str], int, str]:
    """Lines ``start`` to ``start + count``, and how many there are in all.

    Streamed rather than loaded. The point is that a slice of a very large file
    must cost what the slice costs — the alternative is a tool whose advice for
    an oversized file ("read a slice with offset/limit") it cannot itself
    carry out.
    """
    try:
        size = path.stat().st_size
    except OSError as exc:
        return [], 0, str(exc)
    if size > cap:
        return [], 0, (f"file is {size:,} bytes, over the {cap:,} byte scan "
                       f"limit — search it with grep instead")

    try:
        with path.open("rb") as handle:
            if b"\x00" in handle.read(BINARY_SNIFF):
                return [], 0, "file appears to be binary"
    except OSError as exc:
        return [], 0, str(exc)

    window: list[str] = []
    total = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            for index, line in enumerate(handle):
                total = index + 1
                if start <= total < start + count:
                    window.append(line.rstrip("\n").rstrip("\r"))
    except OSError as exc:
        return [], 0, str(exc)
    return window, total, ""


def unified_diff(before: str, after: str, path: str) -> str:
    """A unified diff, capped so a huge rewrite cannot flood the screen."""
    lines = list(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}", n=3,
    ))
    if not lines:
        return "(no changes)"
    if len(lines) > 400:
        head = "".join(lines[:400])
        return head + f"\n… {len(lines) - 400} more diff lines"
    return "".join(lines)


def change_stats(before: str, after: str) -> tuple[int, int]:
    added = removed = 0
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def _write(ctx: ToolContext, path: Path, content: str, action: str,
           tool: str) -> str:
    """Write the file, then say what is wrong with what was written.

    The check runs after the write and never gates it. Both halves of a
    two-part edit have to be possible, and the first half of one usually leaves
    the file inconsistent — a verifier that refused it would make the pair
    unreachable. The bytes are down and the checkpoint is taken; all this does
    is make sure the model finds out.
    """
    # The snapshot records both sides: what was there before, so /undo works,
    # and what the agent is about to leave, so a later hand-edit is detectable.
    if ctx.config.safety.checkpoints:
        ctx.checkpoints.snapshot(path, action=action, tool=tool, after=content)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")

    # Written is known. Without this a second `write_file` to the same path
    # would warn that the contents are unread, when the thing that put them
    # there was the call before it.
    ctx.note_read(path)

    if not getattr(ctx.config.safety, "verify_edits", True):
        return ""
    return verify.check(path, content)


def _and_the_damage(report: str) -> str:
    """The verifier's finding, as a line under what the tool already said."""
    return f"\n\nWARNING  {report}" if report else ""


def _splice(text: str, matches, replacement: str) -> str:
    """Put `replacement` at every match, working from the back.

    Backwards because each replacement shifts everything after it, and the
    offsets were all measured against the text as it stands now.
    """
    for one in reversed(matches):
        text = text[:one.start] + replacement + text[one.end:]
    return text


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #


class ReadFile(Tool):
    name = "read_file"
    description = (
        "Read a text file from the workspace. Returns the content with line numbers. "
        "Use offset and limit for large files."
    )
    risk = Risk.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path, relative to the workspace."},
            "offset": {"type": "integer", "description": "First line to return (1-based)."},
            "limit": {"type": "integer", "description": "How many lines to return."},
        },
        "required": ["path"],
    }

    def summary(self, args: dict[str, Any]) -> str:
        return f"read {args.get('path', '?')}"

    def run(self, ctx: ToolContext, path: str, offset: int = 1,
            limit: int = 2000, **_: Any) -> ToolResult:
        target = ctx.resolve(path)
        if not target.exists():
            return ToolResult.failure(f"{ctx.relative(target)} does not exist")
        if target.is_dir():
            return ToolResult.failure(f"{ctx.relative(target)} is a directory — use list_dir")

        start = max(1, int(offset))
        count = max(1, int(limit))
        window, total, error = read_window(
            target, start, count, ctx.config.safety.max_file_scan_bytes)
        if error:
            return ToolResult.failure(error)

        # Recorded before the result is built, so a later write to this path
        # can tell "replacing something I have read" from "replacing something
        # I have not". Only a whole read counts: a twenty-line window of a
        # thousand-line file is not knowing the file.
        if start == 1 and len(window) >= total:
            ctx.note_read(target)

        numbered = "\n".join(f"{start + index:6d}\t{line}"
                              for index, line in enumerate(window))
        end = start + len(window) - 1
        note = ""
        if window and end < total:
            note = f"\n\n[showing lines {start}-{end} of {total}]"
        elif not window and total:
            note = f"[the file has {total} lines; line {start} is past the end]"
        return ToolResult.success(
            content=numbered + note or "(empty file)",
            display="\n".join(window),
            path=str(target), lines=total, language=target.suffix.lstrip("."),
        )


class WriteFile(Tool):
    name = "write_file"
    description = (
        "Create a file or replace its entire contents. "
        "Prefer edit_file for changes to an existing file."
    )
    risk = Risk.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string", "description": "The complete new file contents."},
        },
        "required": ["path", "content"],
    }

    def summary(self, args: dict[str, Any]) -> str:
        return f"write {args.get('path', '?')}"

    def detail(self, ctx: ToolContext, args: dict[str, Any]) -> str:
        target = ctx.resolve(args.get("path", ""))
        before, _ = read_text(target, 512_000) if target.exists() else ("", "")
        return unified_diff(before, str(args.get("content", "")), ctx.relative(target))

    def run(self, ctx: ToolContext, path: str, content: str, **_: Any) -> ToolResult:
        target = ctx.resolve(path)
        allowed, reason = ctx.permissions.path_allowed(target)
        if not allowed:
            return ToolResult.failure(reason)

        before = ""
        blind = ""
        if target.exists():
            before, error = read_text(target, 2_000_000)
            if error:
                before = ""
            if not ctx.was_read(target):
                # Not refused — creating a file, rewriting a generated one, or
                # replacing something read in an earlier session are all
                # ordinary. But `write_file` replaces everything, and doing
                # that to a file whose contents are unknown is how the rest of
                # it disappears. The benchmark caught exactly this: a task
                # failed for overwriting the sample it was measured against, in
                # a run whose actual work was correct.
                blind = (f"{len(before.splitlines())} lines were replaced in a "
                         f"file this session had not read. If you meant to "
                         f"change part of it, read it and use edit_file; "
                         f"/undo restores it.")

        report = _write(ctx, target, content,
                        action="write" if target.exists() else "create",
                        tool=self.name)
        added, removed = change_stats(before, content)
        rel = ctx.relative(target)
        return ToolResult.success(
            content=f"Wrote {rel} ({len(content.splitlines())} lines, "
                    f"+{added}/-{removed})."
                    + _and_the_damage(blind)
                    + _and_the_damage(report),
            display=unified_diff(before, content, rel),
            path=str(target), added=added, removed=removed, diff=True,
        )


class EditFile(Tool):
    name = "edit_file"
    description = (
        "Replace an exact string in a file. old_string must appear exactly once "
        "unless replace_all is true. Include enough surrounding context to be unique."
    )
    risk = Risk.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string", "description": "Exact text to replace."},
            "new_string": {"type": "string", "description": "Replacement text."},
            "replace_all": {"type": "boolean", "description": "Replace every occurrence."},
        },
        "required": ["path", "old_string", "new_string"],
    }

    def summary(self, args: dict[str, Any]) -> str:
        return f"edit {args.get('path', '?')}"

    def detail(self, ctx: ToolContext, args: dict[str, Any]) -> str:
        target = ctx.resolve(args.get("path", ""))
        before, error = read_text(target, 2_000_000)
        if error:
            return error
        old, new = str(args.get("old_string", "")), str(args.get("new_string", ""))
        if old not in before:
            return "old_string was not found in the file"
        after = (before.replace(old, new) if args.get("replace_all")
                 else before.replace(old, new, 1))
        return unified_diff(before, after, ctx.relative(target))

    def run(self, ctx: ToolContext, path: str, old_string: str, new_string: str,
            replace_all: bool = False, **_: Any) -> ToolResult:
        target = ctx.resolve(path)
        allowed, reason = ctx.permissions.path_allowed(target)
        if not allowed:
            return ToolResult.failure(reason)
        if not target.exists():
            return ToolResult.failure(f"{ctx.relative(target)} does not exist")

        before, error = read_text(target, 2_000_000)
        if error:
            return ToolResult.failure(error)

        matches, _ = matching.find(before, old_string, all_of_them=replace_all)
        occurrences = len(matches)
        if occurrences == 0:
            # A bare "not found" sends the model back to read the whole file
            # and guess again. Naming the closest few places, with the nearest
            # diffed against what was asked for, usually makes the next call
            # the right one instead of the second wrong one.
            hint = matching.near_misses(before, old_string)
            return ToolResult.failure(
                "old_string was not found. The text may have changed since you "
                "read it, or the whitespace does not match."
                + (f"\n\n{hint}" if hint else "")
            )
        if occurrences > 1 and not replace_all:
            lines = ", ".join(str(before.count("\n", 0, one.start) + 1)
                              for one in matches[:6])
            return ToolResult.failure(
                f"old_string matches {occurrences} places — lines {lines}. Add "
                "surrounding context to make it unique, or pass replace_all=true."
            )

        after = _splice(before, matches, new_string)
        if after == before:
            return ToolResult.failure("the replacement produced no change")

        report = _write(ctx, target, after, action="edit", tool=self.name)
        added, removed = change_stats(before, after)
        rel = ctx.relative(target)
        # Announced, never silent. An edit that landed somewhere slightly
        # different from what was asked for and says nothing about it is worse
        # than one that refused.
        how = matches[0].how
        return ToolResult.success(
            content=f"Edited {rel} (+{added}/-{removed}, "
                    f"{occurrences if replace_all else 1} "
                    f"replacement{'s' if replace_all and occurrences > 1 else ''})."
                    + (f" {how[0].upper()}{how[1:]}." if how else "")
                    + _and_the_damage(report),
            display=unified_diff(before, after, rel),
            path=str(target), added=added, removed=removed, diff=True,
        )


class ListDir(Tool):
    name = "list_dir"
    description = "List the entries of a directory, marking subdirectories and file sizes."
    risk = Risk.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string",
                     "description": "Directory path. Defaults to the workspace root."},
            "all": {"type": "boolean", "description": "Include dotfiles."},
        },
    }

    def summary(self, args: dict[str, Any]) -> str:
        return f"list {args.get('path', '.')}"

    def run(self, ctx: ToolContext, path: str = ".", all: bool = False,
            **_: Any) -> ToolResult:
        target = ctx.resolve(path)
        if not target.exists():
            return ToolResult.failure(f"{ctx.relative(target)} does not exist")
        if not target.is_dir():
            return ToolResult.failure(f"{ctx.relative(target)} is not a directory")

        try:
            entries = sorted(target.iterdir(),
                             key=lambda item: (item.is_file(), item.name.lower()))
        except OSError as exc:
            return ToolResult.failure(str(exc))

        skip = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache"}
        rows: list[str] = []
        for entry in entries:
            if entry.name in skip:
                continue
            if not all and entry.name.startswith("."):
                continue
            if entry.is_dir():
                rows.append(f"{entry.name}/")
            else:
                try:
                    rows.append(f"{entry.name}  ({entry.stat().st_size:,} B)")
                except OSError:
                    rows.append(entry.name)

        listing = "\n".join(rows) or "(empty)"
        return ToolResult.success(
            content=f"{ctx.relative(target)}:\n{listing}",
            display=listing,
            path=str(target), count=len(rows),
        )
