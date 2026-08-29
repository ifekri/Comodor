"""Checking an edit the moment it lands, before anyone is told it worked.

The system prompt asks the model to run the tests after a change. Strong models
usually do; cheap ones usually do not; and neither is a guarantee. So the file
that was just written is parsed here, by us, and what comes back goes into the
same tool result the model is already reading. It finds out in the same turn,
for nothing, whether it has left the file broken.

Three rules, and each one is a way this could make things worse rather than
better.

*It never blocks the write.* The bytes are already down and the checkpoint is
already taken. A verifier that refused an edit would make a half-finished
refactor impossible: the second edit of a pair cannot be applied if the first
one is rejected for leaving the file inconsistent.

*It never raises.* A parser that throws for its own reasons must not turn a
successful edit into a failed tool call. Anything unexpected in here is
swallowed and the edit reports exactly as it did before this existed.

*It is fast, or it is not done.* Python, JSON and TOML are parsed in this
process in microseconds. JavaScript costs a subprocess, so it is attempted only
when `node` is already on the path, and the answer is cached for the life of
the run. Nothing here is allowed to add a noticeable pause to an edit.

What it is not: a linter, a type checker, or a test run. It answers one
question — is this file still parseable — because that is the failure that is
both silent and certain to matter. The project's own checks belong to
`agent.verify_command`, which runs once at the end of a turn.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path

#: A syntax check that takes longer than this is not worth having on an edit.
PATIENCE = 5.0

#: Where `node` is, once it has been looked for. `None` means "not looked yet"
#: and an empty string means "looked, and it is not installed" — a distinction
#: worth keeping, because otherwise every edit to a `.js` file searches the
#: whole PATH again to reach the same answer.
_node: str | None = None


def check(path: Path, content: str) -> str:
    """What is wrong with this file, or an empty string.

    The return value is written straight into what the model reads, so it is
    phrased for that reader: what broke, and where.
    """
    try:
        checker = _checker(path)
        return checker(path, content) if checker else ""
    except Exception:
        # Never the reason an edit reports failure. A verifier is a courtesy.
        return ""


def _checker(path: Path):
    suffix = path.suffix.lower()
    if suffix in (".py", ".pyi"):
        return _python
    if suffix == ".json":
        return _json
    if suffix in (".toml",):
        return _toml
    if suffix in (".js", ".mjs", ".cjs"):
        return _javascript
    return None


def _python(path: Path, content: str) -> str:
    advice = " The file was written as given — read it and fix it."
    try:
        ast.parse(content, filename=str(path))
    except SyntaxError as broken:
        # Not every SyntaxError has a line. A null byte in the source is
        # raised without one, and "at line None" is worse than saying nothing
        # about where.
        where = f" at line {broken.lineno}" if broken.lineno else ""
        return f"{type(broken).__name__}{where}: {broken.msg}.{advice}"
    except ValueError as broken:
        # Older interpreters raise this rather than SyntaxError for a null
        # byte, and the message alone does not say which file.
        return f"the file cannot be parsed: {broken}.{advice}"
    return ""


def _json(path: Path, content: str) -> str:
    if not content.strip():
        return ""
    try:
        json.loads(content)
    except ValueError as broken:
        return f"this is not valid JSON: {broken}"
    return ""


def _toml(path: Path, content: str) -> str:
    import tomllib

    if not content.strip():
        return ""
    try:
        tomllib.loads(content)
    except tomllib.TOMLDecodeError as broken:
        return f"this is not valid TOML: {broken}"
    return ""


def _javascript(path: Path, content: str) -> str:
    binary = _find_node()
    if not binary:
        return ""
    try:
        finished = subprocess.run(
            [binary, "--check", str(path)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=PATIENCE)
    except (OSError, subprocess.SubprocessError):
        return ""
    if finished.returncode == 0:
        return ""
    # node prints the offending line, a caret, then the error. The last
    # non-empty line is the part worth repeating.
    lines = [line.strip() for line in finished.stderr.splitlines() if line.strip()]
    reason = next((line for line in lines
                   if "Error" in line or "error" in line), lines[-1] if lines else "")
    return f"node could not parse it: {reason[:200]}"


def _find_node() -> str:
    global _node
    if _node is None:
        _node = shutil.which("node") or ""
    return _node
