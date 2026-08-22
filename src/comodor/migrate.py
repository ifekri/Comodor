"""Bringing settings over from another agent, on the first run.

Somebody arriving from OpenClaw or Hermes has already done the tedious part:
found their API keys, pasted them somewhere, and written a few skills. Asking
them to do it again is the first impression, and it is a bad one.

What is taken is what maps without guessing:

* **API keys**, which is the whole of the tedium. Both tools keep them in an
  `.env` beside their config, and OpenClaw also inlines them in its JSON.
* **The model** they had chosen, when this can host it.
* **Skills**, which both write in the same open format Comodor reads, so they
  are files to copy rather than anything to convert.

What is deliberately *not* taken, and said rather than skipped silently:

* **Their memory.** Comodor's brain is a different thing — lessons with
  confidence, evidence and decay, learned from corrections. A `MEMORY.md` is
  prose. Importing it as lessons would invent confidences nobody measured and
  poison recall with entries that were never earned.
* **Messaging, TTS, personas.** Comodor has no equivalent, and a setting
  imported into nothing is worse than no setting.

Three rules throughout, because this reads other programs' files:

* **Nothing is overwritten.** A key already configured wins; the import fills
  gaps.
* **Nothing is moved.** Every read is a read, and the other tool keeps working.
* **A malformed file is skipped, not fatal.** Half of what makes this useful is
  that it runs on machines whose other agent is in an odd state.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .catalogue import CATALOGUE

#: Where each tool keeps its things. OpenClaw was renamed twice and the older
#: directories are still on real machines, so all three are looked for.
SOURCES: dict[str, tuple[str, ...]] = {
    "OpenClaw": (".openclaw", ".clawdbot", ".moltbot"),
    "Hermes": (".hermes",),
}
#: OpenClaw's config file is named after whichever era it was written in.
OPENCLAW_CONFIGS = ("openclaw.json", "clawdbot.json", "moltbot.json")

#: A skill is prose; anything this large is not one.
MAX_SKILL_BYTES = 512_000
#: And a skill folder is prose with references beside it. The largest one this
#: project ships is under a hundred kilobytes in total.
MAX_SKILL_TREE_BYTES = 2_000_000
MAX_SKILL_FILES = 200
MAX_SKILLS = 100

#: `NAME=value`, tolerating `export `, quotes and blank lines.
_ENV_LINE = re.compile(r"""^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$""")


@dataclass
class Found:
    """What another agent has, that this one could use."""

    tool: str
    root: Path
    #: env-var name -> key, e.g. ANTHROPIC_API_KEY -> sk-...
    keys: dict[str, str] = field(default_factory=dict)
    model: str = ""
    skills: list[Path] = field(default_factory=list)
    #: Things noticed but deliberately not taken, with the reason.
    passed_over: list[str] = field(default_factory=list)

    @property
    def anything(self) -> bool:
        return bool(self.keys or self.model or self.skills)

    def summary(self) -> str:
        parts = []
        if self.keys:
            parts.append(f"{len(self.keys)} API key"
                         f"{'s' if len(self.keys) != 1 else ''}")
        if self.model:
            parts.append(f"the model ({self.model})")
        if self.skills:
            parts.append(f"{len(self.skills)} skill"
                         f"{'s' if len(self.skills) != 1 else ''}")
        return ", ".join(parts) or "nothing usable"


# --------------------------------------------------------------------------- #
# looking
# --------------------------------------------------------------------------- #


def discover(home: Path | None = None) -> list[Found]:
    """Every other agent on this machine that has something worth taking."""
    base = Path(home) if home else Path.home()
    found: list[Found] = []
    for tool, names in SOURCES.items():
        for name in names:
            root = base / name
            if not root.is_dir():
                continue
            reading = _read_openclaw(root) if tool == "OpenClaw" else _read_hermes(root)
            reading.tool, reading.root = tool, root
            if reading.anything:
                found.append(reading)
            break        # the first directory of a family is the current one
    return found


def _read_openclaw(root: Path) -> Found:
    reading = Found(tool="OpenClaw", root=root)
    reading.keys.update(_read_env(root / ".env"))

    document = {}
    for name in OPENCLAW_CONFIGS:
        document = _read_json(root / name)
        if document:
            break

    # Keys are inlined under models.providers.<name>.apiKey, and the value may
    # be a literal, an ${ENV} template, or an object naming where to find it.
    # Only a literal can be brought over; the others point at things that mean
    # something on the machine they were written for.
    providers = ((document.get("models") or {}).get("providers") or {})
    if isinstance(providers, dict):
        for name, entry in providers.items():
            if not isinstance(entry, dict):
                continue
            key = entry.get("apiKey")
            if isinstance(key, dict):
                reading.passed_over.append(
                    f"the key for {name} is stored elsewhere ("
                    f"{key.get('source', 'a reference')}) and cannot be copied")
                continue
            if not isinstance(key, str) or not key.strip() or "${" in key:
                continue
            variable = _env_name_for(str(entry.get("baseUrl") or ""),
                                     str(entry.get("api") or ""), str(name))
            if variable:
                reading.keys.setdefault(variable, key.strip())

    model = ((document.get("agents") or {}).get("defaults") or {}).get("model")
    if isinstance(model, dict):
        model = model.get("primary")
    if isinstance(model, str) and model.strip():
        reading.model = model.strip()

    reading.skills = _find_skills(root / "skills")
    _note_what_is_left(reading, root)
    return reading


def _read_hermes(root: Path) -> Found:
    reading = Found(tool="Hermes", root=root)
    reading.keys.update(_read_env(root / ".env"))

    # config.yaml is YAML, and this project has one dependency. Rather than
    # pretend to parse YAML, the one setting worth having is read with a narrow
    # line match — and anything more complicated is left alone on purpose.
    reading.model = _scalar_from_yaml(root / "config.yaml", ("model", "default_model"))

    reading.skills = _find_skills(root / "skills")
    _note_what_is_left(reading, root)
    return reading


def _note_what_is_left(reading: Found, root: Path) -> None:
    """Say what was seen and not taken. Silence reads as "there was nothing"."""
    for name, why in (
        ("MEMORY.md", "its memory is prose; this agent's is lessons with "
                      "confidence and evidence, and inventing those would "
                      "poison recall"),
        ("SOUL.md", "personas have no equivalent here"),
        ("USER.md", "there is no user profile to import into"),
    ):
        if (root / name).is_file() or (root / "workspace" / name).is_file():
            reading.passed_over.append(f"{name} — {why}")


# --------------------------------------------------------------------------- #
# reading other people's formats
# --------------------------------------------------------------------------- #


def _read_env(path: Path) -> dict[str, str]:
    """A dotenv file, as far as one can be read without a parser for it."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _ENV_LINE.match(line)
        if not match:
            continue
        name, raw = match.group(1), match.group(2).strip()
        if raw[:1] in ("'", '"') and raw[-1:] == raw[:1] and len(raw) >= 2:
            raw = raw[1:-1]
        raw = raw.split(" #", 1)[0].strip()
        if name.endswith("_API_KEY") and raw and "${" not in raw:
            values[name] = raw
    return values


def _read_json(path: Path) -> dict:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _scalar_from_yaml(path: Path, keys: tuple[str, ...]) -> str:
    """One top-level `key: value` out of a YAML file, without parsing YAML.

    Deliberately narrow. Reading a whole YAML document properly needs a
    library, and the one setting worth having here is a scalar on its own line;
    guessing at anything more would be the sort of half-working that is worse
    than not trying.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        if line[:1].isspace() or ":" not in line:
            continue
        name, _, value = line.partition(":")
        if name.strip() not in keys:
            continue
        value = value.split("#", 1)[0].strip().strip("'\"")
        if value and not value.startswith(("{", "[", "&", "*")):
            return value
    return ""


def _env_name_for(base_url: str, api: str, name: str) -> str:
    """Which of our providers a foreign provider entry corresponds to."""
    haystack = f"{base_url} {api} {name}".lower()
    for spec in CATALOGUE:
        if not spec.env_key:
            continue
        if spec.id in haystack:
            return spec.env_key
        host = spec.base_url.split("//")[-1].split("/")[0].lower()
        if host and host in haystack:
            return spec.env_key
    if "anthropic" in haystack:
        return "ANTHROPIC_API_KEY"
    return ""


def _find_skills(folder: Path) -> list[Path]:
    """Skill folders and single files, in the open format Comodor also reads."""
    if not folder.is_dir():
        return []
    found: list[Path] = []
    try:
        for entry in sorted(folder.iterdir()):
            if len(found) >= MAX_SKILLS:
                break
            if entry.is_dir() and (entry / "SKILL.md").is_file():
                found.append(entry)
            elif entry.is_file() and entry.suffix.lower() in (".md", ".markdown"):
                found.append(entry)
    except OSError:
        return found
    return found


# --------------------------------------------------------------------------- #
# taking
# --------------------------------------------------------------------------- #


@dataclass
class Outcome:
    keys: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    model: str = ""
    skipped: list[str] = field(default_factory=list)

    @property
    def anything(self) -> bool:
        return bool(self.keys or self.skills or self.model)


def apply(reading: Found, config, take_keys: bool = True,
          take_skills: bool = True, take_model: bool = True) -> Outcome:
    """Fill the gaps in this configuration from another tool's.

    Nothing already set is replaced: somebody who has configured a key here
    means it, and an import that overwrites it is a bug wearing a feature's
    clothes.
    """
    # `skipped` is what this call declined to apply; `reading.passed_over` is
    # what was seen and deliberately never imported. Seeding one from the other
    # made the wizard print every note twice under two different headings.
    outcome = Outcome()
    #: Providers a key actually landed on, in the order it happened.
    landed: list = []

    if take_keys:
        for variable, key in sorted(reading.keys.items()):
            spec = next((entry for entry in CATALOGUE
                         if entry.env_key == variable), None)
            if spec is None:
                continue
            existing = config.providers.get(spec.id)
            if existing is not None and existing.api_key:
                outcome.skipped.append(f"{spec.label}: you already have a key")
                continue
            if existing is None:
                # A configuration built by `load` has a slot for every provider
                # in the catalogue, but one assembled another way may not, and
                # dropping a key because a dict was missing a slot is the sort
                # of silent failure this exists to avoid.
                from .config import provider_from_spec

                existing = provider_from_spec(spec)
                config.providers[spec.id] = existing
            existing.api_key = key
            # It has a key and this agent will use it; that is what the flag
            # means. Left false, `doctor` reports a provider that works as one
            # that was never set up.
            existing.configured = True
            existing.enabled = True
            outcome.keys.append(spec.label)
            landed.append(spec)

    if take_model and reading.model and not config.model:
        # Only if this can actually host it — a model name from another tool's
        # namespace that nothing here can reach is worse than no model.
        if _known_model(reading.model):
            config.model = reading.model
            outcome.model = reading.model
        else:
            outcome.skipped.append(
                f"the model {reading.model} — no provider here offers it")

    if take_skills and reading.skills:
        outcome.skills = _copy_skills(reading, config.paths.skills)

    # Nothing chosen yet, and a key just arrived: choose. `active()` would
    # otherwise fall back to whichever provider happens to have a key, which is
    # right once and arbitrary as soon as there are two.
    if landed and not config.provider:
        wanted = config.model or outcome.model
        preferred = next(
            (spec for spec in landed
             if wanted and (wanted == spec.default_model or wanted in spec.models)),
            landed[0])
        config.provider = preferred.id
        entry = config.providers.get(preferred.id)
        if entry is not None and wanted and not entry.model:
            entry.model = wanted

    return outcome


def _known_model(model: str) -> bool:
    """Whether this agent could actually run that model.

    Two places know about models and they know different amounts. The setup
    catalogue lists a few well-known names per provider, for the wizard to
    offer; the pricing registry knows every model it has a rate for. Asking
    only the first refuses models the agent can perfectly well run, on the
    grounds that the wizard would not have suggested them.
    """
    lowered = model.lower().strip()
    if not lowered:
        return False

    for spec in CATALOGUE:
        if spec.default_model and spec.default_model.lower() == lowered:
            return True
        if any(known.lower() == lowered for known in spec.models):
            return True

    from .providers import registry

    return any(info.id.lower() == lowered for info in registry.known_models())


def _copy_skills(reading: Found, target: Path) -> list[str]:
    """Copy, never move. The other tool keeps working."""
    copied: list[str] = []
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        return copied

    for source in reading.skills:
        name = source.stem if source.is_file() else source.name
        # Namespaced, so an import cannot quietly replace a skill of the user's
        # own that happens to share a name.
        destination = target / f"{reading.tool.lower()}-{name}"
        if source.is_file():
            destination = destination.with_suffix(".md")
        if destination.exists():
            continue
        try:
            if source.is_dir():
                refused = _copy_tree(source, destination)
                if refused:
                    reading.passed_over.append(f"the skill {name} — {refused}")
                    continue
            else:
                if _too_big(source):
                    reading.passed_over.append(
                        f"the skill {name} — larger than a skill should be")
                    continue
                if source.is_symlink():
                    reading.passed_over.append(
                        f"the skill {name} — it is a link out of that folder")
                    continue
                shutil.copy2(source, destination)
        except OSError:
            continue
        copied.append(destination.name)
    return copied


def _copy_tree(source: Path, destination: Path) -> str:
    """Copy a skill folder. Returns why it was refused, or empty on success.

    Deliberately not `shutil.copytree`. That follows symlinks, and a skill is a
    file whose contents are read into a prompt — a link in somebody else's
    directory pointing at `~/.ssh/id_rsa` or at their own `.env` would have
    been copied in and then sent to a model. Nothing here needs to read outside
    the folder it was given, so nothing does.

    The size budget is the whole tree rather than the entry file, which is what
    the limit was always meant to mean.
    """
    plan: list[tuple[Path, Path]] = []
    total = 0
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            return "it contains a link out of that folder"
        try:
            relative = item.relative_to(source)
        except ValueError:            # cannot happen from rglob; cheap to be sure
            return "it contains a path outside itself"
        if item.is_dir():
            continue
        if not item.is_file():
            continue                  # sockets, fifos: not a skill
        try:
            size = item.stat().st_size
        except OSError:
            return "part of it could not be read"
        # The per-file rule still holds inside a folder: a skill is prose, and
        # a single file this large is not one whatever it sits next to.
        if size > MAX_SKILL_BYTES:
            return f"{item.name} in it is larger than a skill should be"
        total += size
        if total > MAX_SKILL_TREE_BYTES:
            return "it is far larger than a skill"
        plan.append((item, destination / relative))
        if len(plan) > MAX_SKILL_FILES:
            return "it holds more files than a skill should"

    if not plan:
        return "there was nothing in it"

    for origin, target in plan:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
    return ""


def _too_big(path: Path) -> bool:
    try:
        return path.stat().st_size > MAX_SKILL_BYTES
    except OSError:
        return True


def env_hint(reading: Found) -> dict[str, str]:
    """Keys found that are not already in this process's environment.

    Used by the wizard to say *which* keys it can bring, without printing any
    of them: a key on screen is a key in a scrollback buffer.
    """
    return {name: value for name, value in reading.keys.items()
            if not os.environ.get(name)}
