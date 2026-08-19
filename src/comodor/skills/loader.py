"""Reading skills off disk.

A skill is Markdown with a small front-matter header. That format was chosen
because it is the one a person will actually maintain: it opens in any editor,
diffs cleanly in review, and needs no schema to look at.

Two layouts are read, and both are first-class:

* ``review.md`` — a single file. The shortest thing that works, and the right
  shape for a skill that is three paragraphs of house style.
* ``review/SKILL.md`` — a folder, which may also carry ``scripts/``,
  ``references/`` and ``assets/``. This is the `Agent Skills`_ open format, so a
  skill written for another agent runs here unchanged, and one written here runs
  there. Portability is the whole point of using somebody else's format rather
  than inventing a ninth one.

.. _Agent Skills: https://agentskills.io

The parser is deliberately forgiving about everything except the two fields that
make a skill usable — a name and a description. A file with a typo in an
optional field still loads, with the mistake reported, rather than vanishing
without explanation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_SKILL_BYTES = 64_000
FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

#: The file that marks a directory as a skill, per the open format.
MANIFEST = "SKILL.md"
#: Where bundled resources conventionally live, and how deep to look. One level
#: is the format's own recommendation, and it also bounds the walk.
RESOURCE_DIRS = ("references", "scripts", "assets")
MAX_RESOURCES = 40

#: Format constraints, checked so a skill that is invalid elsewhere is invalid
#: here too — a warning that only fires in the other tool is a warning nobody
#: sees until their skill has already been published.
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024


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
    #: The skill's own directory, when it has one. Resources resolve against it.
    root: Path | None = None
    #: Bundled files, relative to :attr:`root`, discovered but not read.
    resources: list[str] = field(default_factory=list)
    #: Always inject, regardless of what was asked.
    always: bool = False
    enabled: bool = True

    # -- the open format's optional fields ---------------------------------- #
    license: str = ""
    #: Environment this skill needs — a package, a network, a particular tool.
    compatibility: str = ""
    #: Arbitrary string map. The format's escape hatch for client-specific keys.
    metadata: dict[str, str] = field(default_factory=dict)
    #: Tools the skill declares as pre-approved. Advisory: Comodor still asks,
    #: because a file in a folder is not consent to run commands.
    allowed_tools: list[str] = field(default_factory=list)

    #: Anything wrong with the file that did not stop it loading.
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """What the matcher indexes."""
        return " ".join([self.name, self.description, " ".join(self.triggers)])

    @property
    def source(self) -> str:
        return str(self.path) if self.path else "(memory)"

    @property
    def bundled(self) -> bool:
        """Whether this skill carries files beyond its instructions."""
        return bool(self.resources)

    def resolve(self, relative: str) -> Path | None:
        """A bundled file's real path, or ``None`` if it is not one of them.

        Membership is checked against what discovery actually found rather than
        by joining and re-resolving, so no amount of ``../`` in a model-supplied
        string reaches outside the skill.
        """
        if self.root is None:
            return None
        wanted = str(relative).replace("\\", "/").strip().lstrip("./")
        if wanted not in self.resources:
            return None
        return self.root / Path(wanted)

    def render(self) -> str:
        """The block handed to the model."""
        parts = [f"### Skill: {self.name}\n{self.description}"]
        if self.compatibility:
            parts.append(f"*Requires:* {self.compatibility}")
        parts.append(self.instructions.strip())
        if self.resources:
            listing = "\n".join(f"- {name}" for name in self.resources)
            # Named but not inlined: that is the point of a bundled file. The
            # model asks for one when the task needs it, and the other thirty
            # never enter the context.
            parts.append(
                "**Bundled files** — read one with "
                f"`read_skill_file(skill=\"{self.name}\", path=…)` when you need it:"
                f"\n{listing}"
            )
        return "\n\n".join(parts)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name, "description": self.description,
            "triggers": self.triggers, "tools": self.tools,
            "scope": self.scope, "always": self.always,
            "enabled": self.enabled, "path": self.source,
            "resources": self.resources, "license": self.license,
            "compatibility": self.compatibility, "metadata": self.metadata,
            "allowed_tools": self.allowed_tools,
        }


class SkillError(ValueError):
    """A file that could not be loaded as a skill at all."""


def parse(text: str, path: Path | None = None, scope: str = "user",
          root: Path | None = None, resources: list[str] | None = None) -> Skill:
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
    metadata = _as_mapping(header.get("metadata"))

    name = str(header.get("name") or _default_name(path, root)).strip()
    if not name:
        raise SkillError("the front matter has no 'name'")

    description = str(header.get("description") or "").strip()
    if not description:
        warnings.append("no 'description' — matching will rely on the name alone")

    if not body:
        raise SkillError(f"skill {name!r} has a header but no instructions under it")

    _check_format(name, description, root, warnings)

    # Comodor's own fields are read from the top level, where they are easiest
    # to write, and from `metadata`, which is where the open format says a
    # client's extra keys belong. Either spelling works.
    def extra(key: str) -> object:
        value = header.get(key)
        return metadata.get(key) if value is None else value

    return Skill(
        name=name,
        description=description,
        instructions=body,
        triggers=_as_list(extra("triggers")),
        tools=_as_list(extra("tools")),
        scope=scope,
        path=path,
        root=root,
        resources=list(resources or []),
        always=_as_bool(extra("always"), default=False),
        enabled=_as_bool(extra("enabled"), default=True),
        license=str(header.get("license") or "").strip(),
        compatibility=str(header.get("compatibility") or "").strip(),
        metadata=metadata,
        # Space-separated in the format, comma-separated in most people's heads.
        allowed_tools=_as_list(str(header.get("allowed-tools") or "").replace(" ", ",")),
        warnings=warnings,
    )


def load(path: Path, scope: str = "user") -> Skill:
    """Load a skill from a single file or from a skill directory."""
    manifest, root, resources = _locate(path)

    if manifest.stat().st_size > MAX_SKILL_BYTES:
        raise SkillError(
            f"{manifest.name} is larger than {MAX_SKILL_BYTES // 1000} KB — a "
            "skill is injected into the prompt, so it has to stay short. Move "
            "the detail into references/ and let the agent read it on demand."
        )

    return parse(manifest.read_text(encoding="utf-8", errors="replace"),
                 manifest, scope, root=root, resources=resources)


def _locate(path: Path) -> tuple[Path, Path | None, list[str]]:
    """Resolve what was pointed at into (manifest, root, bundled files)."""
    if path.is_dir():
        manifest = path / MANIFEST
        if not manifest.is_file():
            raise SkillError(
                f"{path.name}/ has no {MANIFEST} — a skill directory needs one"
            )
        return manifest, path, _bundled(path)

    if path.name == MANIFEST:
        return path, path.parent, _bundled(path.parent)

    return path, None, []


def _bundled(root: Path) -> list[str]:
    """Files a skill directory carries, one level down, in a stable order."""
    found: list[str] = []
    for directory in RESOURCE_DIRS:
        folder = root / directory
        if not folder.is_dir():
            continue
        for entry in sorted(folder.iterdir()):
            if entry.is_file() and not entry.name.startswith("."):
                found.append(f"{directory}/{entry.name}")
            if len(found) >= MAX_RESOURCES:
                return found
    return found


def _default_name(path: Path | None, root: Path | None) -> str:
    """`SKILL.md` is not a name; the directory it sits in is."""
    if root is not None:
        return root.name
    return path.stem if path else ""


def _check_format(name: str, description: str, root: Path | None,
                  warnings: list[str]) -> None:
    """Report where a skill departs from the open format, without refusing it.

    Refusing would be worse than useless: the skill still describes work the
    user wants done, and Comodor can run it perfectly well. What they need to
    know is that another agent may not.
    """
    if len(name) > MAX_NAME:
        warnings.append(f"name is longer than {MAX_NAME} characters")
    elif not NAME_PATTERN.match(name):
        warnings.append(
            f"name {name!r} is not portable — the open format allows lowercase "
            "letters, digits and single hyphens, as in 'code-review'"
        )
    if root is not None and name != root.name:
        warnings.append(
            f"name {name!r} does not match the folder {root.name!r}; other "
            "agents match the two"
        )
    if len(description) > MAX_DESCRIPTION:
        warnings.append(f"description is longer than {MAX_DESCRIPTION} characters")


# --------------------------------------------------------------------------- #
# a very small YAML subset
# --------------------------------------------------------------------------- #


def _parse_header(raw: str, warnings: list[str]) -> dict[str, object]:
    """Parse ``key: value`` pairs, lists inline or as dashes, and one map level.

    Deliberately not a YAML library. Comodor has one runtime dependency and
    adding another for a dozen lines of front matter is a poor trade; the subset
    below covers what a skill header ever contains, and anything outside it is
    reported rather than silently misread.
    """
    header: dict[str, object] = {}
    current_key: str | None = None

    for number, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indented = line[:len(line) - len(line.lstrip())] != ""

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

        # An indented pair under a key that opened empty belongs to that key:
        #     metadata:
        #       author: someone
        if indented and current_key and isinstance(header.get(current_key), (dict, list)):
            nested = header[current_key]
            if isinstance(nested, list) and not nested:
                nested = header[current_key] = {}
            if isinstance(nested, dict):
                nested[key] = _scalar(value)
                continue

        current_key = key
        if not value:
            header[key] = []          # a list or a map follows on the next lines
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
    if isinstance(value, dict):
        return [str(item).strip() for item in value.values() if str(item).strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def _as_mapping(value: object) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    return {}


def _as_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "yes", "on", "1")
