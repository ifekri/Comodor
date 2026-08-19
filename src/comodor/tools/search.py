"""Finding things: glob by name, grep by content.

Both walk the tree in pure Python rather than shelling out to ``rg`` or
``find`` — the agent must behave identically on a bare Windows box and a Linux
CI runner, and neither tool is guaranteed to exist.

Ignore rules matter more than they look: without them a search in any real
project drowns in ``node_modules`` and ``.venv`` hits, which wastes the model's
context on noise. ``.gitignore`` is honoured plus a built-in list of directories
that are never interesting.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any, Iterator

from ..safety import Risk
from .base import Tool, ToolContext, ToolResult

ALWAYS_SKIP = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", ".next",
    ".tox", ".gradle", "target", ".idea", ".vscode", ".comodor",
}
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz",
    ".tar", ".7z", ".exe", ".dll", ".so", ".dylib", ".pyc", ".pyd", ".class",
    ".jar", ".mp3", ".mp4", ".mov", ".woff", ".woff2", ".ttf", ".db", ".sqlite",
}
MAX_SCAN_BYTES = 2_000_000


# --------------------------------------------------------------------------- #
# ignore handling
# --------------------------------------------------------------------------- #


class IgnoreRules:
    """A small ``.gitignore`` reader.

    Deliberately not a full implementation — it covers directory names, glob
    patterns and negations, which is what actually appears in the ignore files
    of real projects. Anything exotic simply does not match, and the worst case
    is that we search a file we could have skipped.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.patterns: list[tuple[str, bool]] = []      # (pattern, negated)
        self._load(root / ".gitignore")

    def _load(self, path: Path) -> None:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            negated = line.startswith("!")
            if negated:
                line = line[1:]
            self.patterns.append((line.rstrip("/"), negated))

    def ignored(self, path: Path) -> bool:
        if path.name in ALWAYS_SKIP:
            return True
        try:
            relative = path.relative_to(self.root).as_posix()
        except ValueError:
            return False

        ignored = False
        for pattern, negated in self.patterns:
            if self._matches(relative, path.name, pattern):
                ignored = not negated
        return ignored

    @staticmethod
    def _matches(relative: str, name: str, pattern: str) -> bool:
        if pattern.startswith("/"):
            return fnmatch.fnmatch(relative, pattern.lstrip("/"))
        if "/" in pattern:
            return fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(relative, f"*/{pattern}")
        return fnmatch.fnmatch(name, pattern)


def walk(root: Path, rules: IgnoreRules, limit: int = 20000) -> Iterator[Path]:
    """Yield every file under ``root`` that survives the ignore rules."""
    stack = [root]
    seen = 0
    while stack and seen < limit:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (OSError, PermissionError):
            continue
        for entry in entries:
            if rules.ignored(entry):
                continue
            if entry.is_dir():
                if not entry.is_symlink():
                    stack.append(entry)
            else:
                seen += 1
                yield entry
                if seen >= limit:
                    return


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #


class Glob(Tool):
    name = "glob"
    description = (
        "Find files by name pattern, e.g. '**/*.py' or 'src/**/test_*.py'. "
        "Results are sorted by modification time, newest first."
    )
    risk = Risk.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern."},
            "path": {"type": "string", "description": "Directory to search in."},
            "limit": {"type": "integer", "description": "Maximum results (default 100)."},
        },
        "required": ["pattern"],
    }

    def summary(self, args: dict[str, Any]) -> str:
        return f"glob {args.get('pattern', '?')}"

    def run(self, ctx: ToolContext, pattern: str, path: str = ".",
            limit: int = 100, **_: Any) -> ToolResult:
        root = ctx.resolve(path)
        if not root.is_dir():
            return ToolResult.failure(f"{ctx.relative(root)} is not a directory")

        rules = IgnoreRules(ctx.cwd)
        matches: list[Path] = []
        for candidate in root.glob(pattern):
            if candidate.is_file() and not rules.ignored(candidate):
                matches.append(candidate)
            if len(matches) >= limit * 4:
                break

        matches.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0,
                     reverse=True)
        matches = matches[:limit]
        if not matches:
            return ToolResult.success(f"No files match {pattern}.", count=0)

        listing = "\n".join(ctx.relative(match) for match in matches)
        return ToolResult.success(
            content=f"{len(matches)} match(es):\n{listing}",
            display=listing, count=len(matches),
        )


class Grep(Tool):
    name = "grep"
    description = (
        "Search file contents with a regular expression. Returns matching lines "
        "with their file and line number."
    )
    risk = Risk.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python regular expression."},
            "path": {"type": "string", "description": "Directory or file to search."},
            "glob": {"type": "string", "description": "Only search files matching this pattern."},
            "ignore_case": {"type": "boolean"},
            "context": {"type": "integer", "description": "Lines of context around each match."},
            "limit": {"type": "integer", "description": "Maximum matching lines (default 80)."},
        },
        "required": ["pattern"],
    }

    def summary(self, args: dict[str, Any]) -> str:
        target = args.get("path", ".")
        return f"grep /{args.get('pattern', '')}/ in {target}"

    def run(self, ctx: ToolContext, pattern: str, path: str = ".", glob: str = "",
            ignore_case: bool = False, context: int = 0, limit: int = 80,
            **_: Any) -> ToolResult:
        try:
            regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error as exc:
            return ToolResult.failure(f"invalid regular expression: {exc}")

        root = ctx.resolve(path)
        if not root.exists():
            return ToolResult.failure(f"{ctx.relative(root)} does not exist")

        rules = IgnoreRules(ctx.cwd)
        candidates = [root] if root.is_file() else walk(root, rules)

        hits: list[str] = []
        files_with_matches = 0
        scanned = 0

        for candidate in candidates:
            if ctx.cancel.cancelled or len(hits) >= limit:
                break
            if candidate.suffix.lower() in BINARY_SUFFIXES:
                continue
            if glob and not fnmatch.fnmatch(candidate.name, glob):
                continue
            try:
                if candidate.stat().st_size > MAX_SCAN_BYTES:
                    continue
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            scanned += 1
            lines = text.splitlines()
            matched_here = False
            for index, line in enumerate(lines):
                if not regex.search(line):
                    continue
                matched_here = True
                relative = ctx.relative(candidate)
                if context > 0:
                    start = max(0, index - context)
                    end = min(len(lines), index + context + 1)
                    block = "\n".join(f"{relative}:{n + 1}: {lines[n]}"
                                      for n in range(start, end))
                    hits.append(block)
                else:
                    hits.append(f"{relative}:{index + 1}: {line.strip()[:300]}")
                if len(hits) >= limit:
                    break
            if matched_here:
                files_with_matches += 1

        if not hits:
            return ToolResult.success(
                f"No matches for /{pattern}/ in {scanned} file(s).", count=0)

        body = "\n".join(hits)
        header = f"{len(hits)} match(es) in {files_with_matches} file(s):"
        return ToolResult.success(content=f"{header}\n{body}", display=body,
                                  count=len(hits), files=files_with_matches)
