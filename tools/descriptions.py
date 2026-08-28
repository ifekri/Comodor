"""Put each skill's real description back into the catalogue.

The catalogue was built with the description cut at four hundred characters,
which for thirty of these landed mid-word: the picker showed a sentence ending
"…semantic HTML, for" and there was nothing anywhere with the rest of it.

The interface no longer needs the cut. Rows show one line and truncate to the
column, and the full text is a keypress away — so the catalogue carries what
the skill actually says about itself, and the display decides how much of it
to show.

Run from the root of the `skills` branch:

    python tools/descriptions.py          # report what would change
    python tools/descriptions.py --write  # write it
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTMATTER = re.compile(r"^---\s*$(.*?)^---\s*$", re.S | re.M)
#: `description:` up to the next top-level key, so a folded block over several
#: lines is taken whole rather than truncated at the first newline.
FIELD = re.compile(r"^description:\s*(.+?)(?=^[A-Za-z_-]+:|\Z)", re.S | re.M)
#: A leading `>-` or `|` is a YAML block marker, not part of the sentence.
MARKER = re.compile(r"^[>|][-+]?\s*")


def described(skill: Path) -> str:
    """The description a skill gives of itself, on one line."""
    text = skill.read_text(encoding="utf-8", errors="replace")
    block = FRONTMATTER.search(text)
    if not block:
        return ""
    found = FIELD.search(block.group(1))
    if not found:
        return ""
    body = MARKER.sub("", found.group(1).strip())
    return " ".join(body.strip().strip('"').strip("'").split())


def main() -> int:
    write = "--write" in sys.argv
    path = ROOT / "catalogue.json"
    catalogue = json.loads(path.read_text(encoding="utf-8"))

    changed = 0
    for entry in catalogue["skills"]:
        skill = ROOT / "skills" / entry["id"] / "SKILL.md"
        if not skill.exists():
            print(f"  missing  {entry['id']}")
            continue
        full = described(skill)
        if not full or full == entry["description"]:
            continue
        if len(full) > len(entry["description"]):
            print(f"  {entry['id']:<34} {len(entry['description']):>4} "
                  f"-> {len(full):>4}")
        entry["description"] = full
        changed += 1

    widest = max(len(entry["description"]) for entry in catalogue["skills"])
    print(f"\n  {changed} descriptions restored, longest is now {widest}")

    if write:
        path.write_text(json.dumps(catalogue, indent=2, ensure_ascii=False)
                        + "\n", encoding="utf-8")
        print(f"  written to {path}")
    else:
        print("  (nothing written — pass --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
