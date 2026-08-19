"""Reading skills off disk.

A skill is a Markdown file with a small front-matter header. That format was
chosen because it is the one a person will actually maintain: it opens in any
editor, diffs cleanly in review, and needs no schema to look at.

The parser is deliberately forgiving about everything except the two fields
that make a skill usable — a name and a description. A file with a typo in an
optional field still loads, with the mistake reported, rather than vanishing
without explanation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_SKILL_BYTES = 64_000
FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@dataclass
class Skill:
    """One authored skill."""

    name: str
    description: str
    instructions: str
    #: Extra words that should match this skill, beyond its name and text.
    triggers: list[str] = field(default_factory=list)
    #: Restrict the tools the model may use while this skill is in play.
    tools: list[str] = field(default_factory=list)
    #: "user" or "project" — where it was found.
    scope: str = "user"
    path: Path | None = None
    #: Always inject, regardless of what was asked.
    always: bool = False
    enabled: bool = True
    #: Anything wrong with the file that did not stop it loading.
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """What the matcher indexes."""
        return " ".join([self.name, self.description, " ".join(self.triggers)])

    @property
    def source(self) -> str:
        return str(self.path) if self.path else "(memory)"

    def render(self) -> str:
        """The block handed to the model."""
        header = f"### Skill: {self.name}\n{self.description}"
        return f"{header}\n\n{self.instructions.strip()}"

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name, "description": self.description,
            "triggers": self.triggers, "tools": self.tools,
            "scope": self.scope, "always": self.always,
            "enabled": self.enabled, "path": self.source,
        }


class SkillError(ValueError):
    """A file that could not be loaded as a skill at all."""


def parse(text: str, path: Path | None = None, scope: str = "user") -> Skill:
    """Turn a skill file's contents into a :class:`Skill`."""
    warnings: list[str] = []
    match = FRONT_MATTER.match(text)

    if match is None:
        raise SkillError(
            "no front matter — a skill starts with a --- block naming it, "
            "for example:\n---\nname: review\ndescription: Review a diff\n---"
        )

    header = _parse_header(match.group(1), warnings)
    body = text[match.end():].strip()

    name = str(header.get("name") or (path.stem if path else "")).strip()
    if not name:
        raise SkillError("the front matter has no 'name'")

    description = str(header.get("description") or "").strip()
    if not description:
        warnings.append("no 'description' — matching will rely on the name alone")

    if not body:
        raise SkillError(f"skill {name!r} has a header but no instructions under it")

    return Skill(
        name=name,
        description=description,
        instructions=body,
        triggers=_as_list(header.get("triggers")),
        tools=_as_list(header.get("tools")),
        scope=scope,
        path=path,
        always=_as_bool(header.get("always"), default=False),
        enabled=_as_bool(header.get("enabled"), default=True),
        warnings=warnings,
    )


def load(path: Path, scope: str = "user") -> Skill:
    if path.stat().st_size > MAX_SKILL_BYTES:
        raise SkillError(
            f"{path.name} is larger than {MAX_SKILL_BYTES // 1000} KB — a skill "
            "is injected into the prompt, so it has to stay short"
        )
    return parse(path.read_text(encoding="utf-8", errors="replace"), path, scope)


# --------------------------------------------------------------------------- #
# a very small YAML subset
# --------------------------------------------------------------------------- #


def _parse_header(raw: str, warnings: list[str]) -> dict[str, object]:
    """Parse ``key: value`` pairs, lists inline or as dashes.

    Deliberately not a YAML library. Comodor has two runtime dependencies and
    adding a third for a dozen lines of front matter is a poor trade; the subset
    below covers what a skill header ever contains, and anything outside it is
    reported rather than silently misread.
    """
    header: dict[str, object] = {}
    current_key: str | None = None

    for number, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- ") and current_key:
            value = header.setdefault(current_key, [])
            if isinstance(value, list):
                value.append(_scalar(stripped[2:]))
            continue

        if ":" not in stripped:
            warnings.append(f"line {number}: ignored, expected 'key: value'")
            continue

        key, _, value = stripped.partition(":")
        key = key.strip().lower()
        value = value.strip()
        current_key = key

        if not value:
            header[key] = []          # a list follows on the next lines
        elif value.startswith("[") and value.endswith("]"):
            header[key] = [_scalar(item) for item in value[1:-1].split(",")
                           if item.strip()]
        else:
            header[key] = _scalar(value)

    return header


def _scalar(value: str) -> str:
    return value.strip().strip("'\"").strip()


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def _as_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "yes", "on", "1")
