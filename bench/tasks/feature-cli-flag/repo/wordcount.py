"""Count the words in a file.

    python wordcount.py notes.txt
    notes.txt: 128 words, 24 lines, 743 characters
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def measure(text: str) -> dict[str, int]:
    return {
        "words": len(text.split()),
        "lines": len(text.splitlines()),
        "characters": len(text),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Count words in a file.")
    parser.add_argument("path", help="the file to measure")
    args = parser.parse_args(argv)

    path = Path(args.path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as problem:
        print(f"wordcount: {problem}", file=sys.stderr)
        return 1

    counted = measure(text)
    print(f"{path.name}: {counted['words']} words, {counted['lines']} lines, "
          f"{counted['characters']} characters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
