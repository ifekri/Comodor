"""What `pip install comodor` promises, against what the package can do.

The metadata is the only thing a resolver reads. A floor lower than the code
needs is the worst kind of install: it succeeds, and the first `comodor
--version` is a traceback. That happened — `requires-python = ">=3.9"` sat
under a package using `dataclass(slots=True)` (3.10) and `tomllib` (3.11)
while the documentation said 3.11 the whole time.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def metadata() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_python_floor_is_the_one_the_documentation_states():
    project = metadata()["project"]
    floor = project["requires-python"]
    assert floor == ">=3.11", floor

    for page in ("README.md", "docs/getting-started.md", "docs/troubleshooting.md",
                 "CONTRIBUTING.md"):
        text = (ROOT / page).read_text(encoding="utf-8")
        assert "3.11 or newer" in text, f"{page} states a different floor"


def test_no_classifier_claims_a_python_below_the_floor():
    project = metadata()["project"]
    floor = tuple(int(part) for part in
                  project["requires-python"].removeprefix(">=").split("."))
    claimed = [tuple(int(part) for part in match.groups())
               for classifier in project["classifiers"]
               for match in [re.fullmatch(r"Programming Language :: Python :: (\d+)\.(\d+)",
                                          classifier)] if match]
    assert claimed, "the classifiers should name the supported minor versions"
    below = [version for version in claimed if version < floor]
    assert not below, f"classifiers promise {below}, below {floor}"


def test_the_code_uses_nothing_newer_than_the_floor_admits():
    """The floor is 3.11. Anything from 3.12+ in the package would be the same
    bug again, one version up: this names the syntax and stdlib that 3.11
    does not have, so a use of one is caught here rather than by a user."""
    newer = {
        "type statements (3.12)": re.compile(r"^\s*type\s+\w+\s*=", re.MULTILINE),
        "PEP 695 generics (3.12)": re.compile(r"^\s*(?:def|class)\s+\w+\[[^\]]+\]\s*[(:]",
                                              re.MULTILINE),
        "itertools.batched (3.12)": re.compile(
            r"\bitertools\.batched\(|from itertools import[^\n]*\bbatched\b"),
        "warnings.deprecated (3.13)": re.compile(r"\bwarnings\.deprecated\("),
        "copy.replace (3.13)": re.compile(r"\bcopy\.replace\("),
    }
    found = []
    for path in sorted((ROOT / "src" / "comodor").rglob("*.py")):
        # Code, not commentary: a comment that names `copy.replace` to say
        # why it is *not* used must not read as a use of it.
        text = "\n".join(line.split("#", 1)[0]
                         for line in path.read_text(encoding="utf-8").splitlines())
        for what, pattern in newer.items():
            if pattern.search(text):
                found.append(f"{path.relative_to(ROOT).as_posix()}: {what}")
    assert not found, "\n".join(found)
