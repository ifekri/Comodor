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


def main(argv: list[str]) -> int:
    wheels = [Path(arg) for arg in argv]
    if not wheels:
        sys.stderr.write("usage: check-wheel-contents.py WHEEL...\n")
        return 2
    problems = [problem for wheel in wheels for problem in check(wheel)]
    for problem in problems:
        sys.stderr.write(problem + "\n")
    if not problems:
        print(f"wheel contents: ok ({', '.join(wheel.name for wheel in wheels)})")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
