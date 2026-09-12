"""The user guides teach commands that exist.

F8 removed `comodor legacy`, `comodor preview`, `--no-mouse` and the slash
commands only the retired interface answered. A manual — in any language —
that still tells someone to type one of them is a product defect that no unit
test of the product can see. This scans the guides the way a reader would
meet them: every locale, every page, the words as written.

Two files are history on purpose and are read as such: the changelog, and the
surface-parity record of what the migration decided and why. A historical
mention anywhere else belongs in one of those two, not in a guide.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Where the migration is allowed to be described in the past tense.
HISTORY = {
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "surface-parity.md",
}

#: Entry points that no longer exist. Any mention in a guide is stale.
RETIRED_ENTRYPOINTS = ("comodor legacy", "comodor preview", "--no-mouse")

#: Slash commands the retired interface answered and nothing answers now.
#: `/mode` is not here — it is a Discord command that still exists — and
#: neither is anything a channel or a URL path legitimately spells with a
#: slash.
RETIRED_SLASH = (
    "save", "undo", "mouse", "computer", "approve", "model", "progress",
    "memory", "rules", "cost", "settings", "skills", "mcp", "gw", "provider",
    "help", "teach", "good", "bad",
)

#: A retired slash command taught as something to type: in backticks, or at
#: the start of a line the way a code block shows it.
SLASH = re.compile(
    r"`/(?:%(names)s)\b[^`]*`|^/(?:%(names)s)\b" % {"names": "|".join(RETIRED_SLASH)},
    re.MULTILINE,
)


#: A locale directory: two capital letters, `docs/FA`, `docs/ZH`.
LOCALE = re.compile(r"^[A-Z]{2}$")


def guides() -> list[Path]:
    """The pages a reader meets: the English guides and every translation.

    `docs/upgrade-specs/` is not walked — those are the design specs the
    features were built from, written before the interface changed hands,
    and a spec is a record of a decision rather than an instruction to type.
    """
    docs = ROOT / "docs"
    pages = [ROOT / "README.md", *sorted(docs.glob("*.md"))]
    for locale in sorted(docs.iterdir()):
        if locale.is_dir() and LOCALE.match(locale.name):
            pages.extend(sorted(locale.glob("*.md")))
    return [page for page in pages if page not in HISTORY]


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


@pytest.mark.parametrize("page", guides(), ids=relative)
def test_no_guide_teaches_a_retired_entrypoint(page):
    text = page.read_text(encoding="utf-8")
    found = [token for token in RETIRED_ENTRYPOINTS if token in text]
    assert not found, f"{relative(page)} still mentions {found}"


@pytest.mark.parametrize("page", guides(), ids=relative)
def test_no_guide_teaches_a_retired_slash_command(page):
    text = page.read_text(encoding="utf-8")
    found = sorted({match.group(0).strip("`") for match in SLASH.finditer(text)})
    assert not found, f"{relative(page)} still teaches {found}"


def test_every_locale_is_covered():
    """The guard is only as wide as the tree it walks. A locale added later
    must be walked too, and this says so if one is not."""
    covered = {relative(page).split("/")[1] for page in guides()
               if relative(page).startswith("docs/") and relative(page).count("/") == 2}
    assert {"AR", "DE", "ES", "FA", "FR", "RU", "TR", "ZH"} <= covered
