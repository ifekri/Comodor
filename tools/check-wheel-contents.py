#!/usr/bin/env python3
"""Refuse a wheel that still carries what the repository retired.

    python tools/check-wheel-contents.py dist/*.whl

The wheel is built from `src/comodor`, so a package that is deleted from the
tree cannot be in it — unless something puts the tree back: a stale checkout,
a merge that resurrects a directory, a build run from the wrong branch. This
is the check that turns that from a surprise in an installed environment
into a failed build step. It also confirms the one thing the wheel must still
carry, the packaged renderer, so a wheel that passes here is one that can
draw.
"""

from __future__ import annotations

import glob
import sys
import zipfile
from pathlib import Path

#: Path prefixes inside the wheel that must not exist. Each is a package the
#: repository retired; the reason is beside it so the list stays honest.
RETIRED = {
    "comodor/ui/": "the previous Rich interface, removed once OpenTUI reached parity",
}

#: What must be there for the wheel to be a Comodor that can start.
REQUIRED = (
    "comodor/tui/dist/main.js",
    "comodor/tui/dist/manifest.json",
    "comodor/terminal/console.py",
)


def check(wheel: Path) -> list[str]:
    problems: list[str] = []
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    for prefix, why in RETIRED.items():
        found = [name for name in names if name.startswith(prefix)]
        if found:
            problems.append(f"{wheel.name}: carries {prefix} ({why}): "
                            f"{len(found)} file(s), first {found[0]}")
    for name in REQUIRED:
        if name not in names:
            problems.append(f"{wheel.name}: missing {name}")
    return problems


def wheels_named(argv: list[str]) -> list[Path]:
    """The wheels the arguments name, patterns expanded here.

    `dist/*.whl` is expanded by bash and handed over verbatim by PowerShell,
    which is what CI runs on Windows; a guard that passes on one shell and
    crashes on the other is not guarding anything. A pattern that matches
    nothing is kept as written, so the failure names what was asked for.
    """
    found: list[Path] = []
    for arg in argv:
        matches = sorted(glob.glob(arg)) if any(c in arg for c in "*?[") else []
        found.extend(Path(match) for match in matches or [arg])
    return found


def main(argv: list[str]) -> int:
    wheels = wheels_named(argv)
    if not wheels:
        sys.stderr.write("usage: check-wheel-contents.py WHEEL...\n")
        return 2
    missing = [wheel for wheel in wheels if not wheel.is_file()]
    if missing:
        for wheel in missing:
            sys.stderr.write(f"no such wheel: {wheel}\n")
        return 2
    problems = [problem for wheel in wheels for problem in check(wheel)]
    for problem in problems:
        sys.stderr.write(problem + "\n")
    if not problems:
        print(f"wheel contents: ok ({', '.join(wheel.name for wheel in wheels)})")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
