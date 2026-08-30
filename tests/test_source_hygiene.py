"""No source file carries a control character it did not ask for.

This exists because it happened three times in one afternoon, and twice it was
invisible.

A shell heredoc turns `\\b` inside a quoted body into a real backspace byte and
`\\n` into a real newline. The newline breaks the file loudly — a `SyntaxError`
at collection, which is annoying and obvious. The backspace does not: the file
parses, the tests import, and a regex that reads

    re.compile(r"\\b(?:1000|thousand)\\b")

quietly matches nothing at all, because what is actually in the file is a
control character where the word boundary should be. Printing the pattern shows
nothing wrong, because a backspace is invisible. The judge that depended on it
failed every correct answer and gave a plausible reason for it.

A tab is fine and a newline is fine. Nothing else belongs in a source file,
and the check costs a few milliseconds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Exactly the bytes a mangled backslash escape turns into — `\\0`, `\\a`,
#: `\\b`, `\\v`, `\\f`, `\\e` — plus DEL.
#:
#: Not every control character: this is a terminal program, and the interface
#: matches real keystrokes by their byte. `app.py` compares against a literal
#: Ctrl-S, which is 0x13 and entirely deliberate. Banning the whole C0 range
#: would fail that, and a guard that cries wolf about correct code is one
#: somebody switches off — which would cost more than it saves, since the
#: byte it is really here for is invisible.
FORBIDDEN = {0x00, 0x07, 0x08, 0x0B, 0x0C, 0x1B, 0x7F}

NAMES = {0x00: "NUL", 0x07: "bell", 0x08: "backspace", 0x0B: "vertical tab",
         0x0C: "form feed", 0x1B: "escape", 0x7F: "delete"}

SKIP = {".venv", "__pycache__", ".git", "node_modules", ".pytest_cache",
        ".ruff_cache", "build", "dist"}


def sources() -> list[Path]:
    return [path for path in sorted(ROOT.rglob("*.py"))
            if not any(part in SKIP for part in path.parts)]


@pytest.mark.parametrize("path", sources(),
                         ids=lambda path: str(path.relative_to(ROOT)))
def test_no_stray_control_characters(path):
    raw = path.read_bytes()
    found = {byte for byte in raw if byte in FORBIDDEN}
    if not found:
        return

    where = []
    for byte in sorted(found):
        first = raw.index(bytes([byte]))
        line = raw[:first].count(b"\n") + 1
        where.append(f"{NAMES.get(byte, hex(byte))} at line {line}")
    pytest.fail(f"{path.relative_to(ROOT)} carries {', '.join(where)} — "
                f"almost certainly a shell heredoc that ate a backslash")


def test_the_check_would_catch_one(tmp_path):
    """A guard that cannot fail is not a guard."""
    victim = tmp_path / "broken.py"
    victim.write_bytes(b'import re\nP = re.compile(r"\x08word\x08")\n')

    raw = victim.read_bytes()
    assert {byte for byte in raw if byte in FORBIDDEN} == {0x08}
