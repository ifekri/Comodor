"""Promoting a procedure the agent worked out into a skill you own.

Reflection already distils a reusable procedure from a multi-step task and
stores it in the brain. That procedure is invisible: it lives in a SQLite row,
it cannot be edited, and it cannot be committed alongside the code it describes.

This is the bridge. When a stored procedure has proved itself — used several
times, mostly successfully, and not already covered by something you wrote — it
becomes a *proposal*: a real `SKILL.md`, in the open format, shown to you in
full before anything is written.

**Nothing is written without a person saying yes.** That is not caution for its
own sake. A skill is an instruction that will shape every future answer it
matches, so an agent that quietly authored its own instructions would be
changing its behaviour in a way the user never agreed to and cannot easily
find. Announced and approved is the same rule Reflex follows for rules, applied
to the larger thing.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .loader import MANIFEST, NAME_PATTERN

#: How much evidence a procedure needs before it is worth offering. A procedure
#: seen twice is a coincidence; the threshold is what keeps the offer rare
#: enough that saying yes still means something.
MIN_USES = 3
MIN_SUCCESS = 0.6
#: Skip anything already covered — measured the same way skills are matched, so
#: "covered" means the same thing here as it does at recall time.
OVERLAP_FLOOR = 0.5

STOPWORDS = frozenset("""
a an and are as at be by for from how in into is it of on or that the then to
use used using was were what when which with you your
""".split())


@dataclass
class Proposal:
    """A learned procedure, ready to become a file the user owns."""

    name: str
    description: str
    instructions: str
    triggers: list[str] = field(default_factory=list)
    #: Why it is being offered, in the user's terms.
    evidence: str = ""
    uses: int = 0
    success_rate: float = 0.0

    def render(self) -> str:
        """The `SKILL.md` this proposal would write."""
        header = [
            "---",
            f"name: {self.name}",
            f"description: {self.description}",
        ]
        if self.triggers:
            header.append(f"triggers: [{', '.join(self.triggers)}]")
        header.append("metadata:")
        header.append("  origin: learned")
        header.append(f"  learned-on: {time.strftime('%Y-%m-%d')}")
        header.append("---")

        return "\n".join(header) + "\n\n" + self.instructions.rstrip() + "\n"

    def write(self, directory: Path) -> Path:
        """Write it as a skill folder. Never overwrites."""
        folder = Path(directory) / self.name
        manifest = folder / MANIFEST
        if manifest.exists() or (Path(directory) / f"{self.name}.md").exists():
            raise FileExistsError(
                f"a skill named {self.name!r} already exists — rename or remove it first")
        folder.mkdir(parents=True, exist_ok=True)
        manifest.write_text(self.render(), encoding="utf-8")
        return manifest


def candidates(procedures, registry, limit: int = 5) -> list[Proposal]:
    """Learned procedures worth offering as skills, best first.

    ``procedures`` is what :meth:`BrainStore.all_skills` returns; ``registry``
    is the authored skills already loaded, so nothing is proposed twice.
    """
    offers: list[Proposal] = []

    for procedure in procedures:
        if procedure.uses < MIN_USES or procedure.success_rate < MIN_SUCCESS:
            continue
        if len(procedure.steps) < 2:
            continue                       # one step is not a procedure
        name = _slug(procedure.name)
        if not name:
            continue
        # The slug is what a file is named, so it is what must be compared. The
        # stored procedure is called "Add a REST endpoint"; the skill it became
        # is `add-a-rest-endpoint`, and comparing the two raw would offer the
        # same draft again every time the user accepted one.
        if _already_covered(procedure, name, registry):
            continue

        offers.append(Proposal(
            name=name,
            description=_describe(procedure),
            instructions=_instructions(procedure),
            triggers=_triggers(procedure),
            evidence=(f"worked {procedure.wins} of {procedure.uses} times"
                      if procedure.uses else ""),
            uses=procedure.uses,
            success_rate=procedure.success_rate,
        ))

    offers.sort(key=lambda offer: (offer.uses, offer.success_rate), reverse=True)
    return offers[:limit]


def _already_covered(procedure, name: str, registry) -> bool:
    """True when an authored skill is about the same thing."""
    if registry is None:
        return False
    if name in registry.skills or procedure.name in registry.skills:
        return True
    try:
        matched = registry.match(f"{procedure.name} {procedure.description}", limit=1)
    except Exception:
        return False
    if not matched:
        return False
    return _overlap(procedure.text, matched[0].text) >= OVERLAP_FLOOR


def _overlap(left: str, right: str) -> float:
    first, second = _words(left), _words(right)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def _words(text: str) -> set[str]:
    return {word for word in re.split(r"\W+", text.lower())
            if len(word) > 2 and word not in STOPWORDS}


def _slug(name: str) -> str:
    """A name the open format accepts, since that is what gets written."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:64].strip("-")
    return slug if NAME_PATTERN.match(slug) else ""


def _describe(procedure) -> str:
    """A description that says what it does *and when to use it*.

    The format asks for both, and it is not a formality: the description is the
    only thing matched against a request, so one that omits the occasion never
    fires.
    """
    described = (procedure.description or "").strip().rstrip(".")
    if not described:
        described = procedure.name.replace("_", " ").replace("-", " ")
    subject = ", ".join(procedure.tags[:3]) or procedure.name.replace("-", " ")
    return f"{described}. Use when the task involves {subject}."[:1024]


def _instructions(procedure) -> str:
    steps = "\n".join(f"{number}. {step}"
                      for number, step in enumerate(procedure.steps, start=1))
    return (
        f"{steps}\n\n"
        "*(Drafted from a task Comodor completed this way. Edit it freely — it "
        "is your file now, and nothing rewrites it.)*"
    )


def _triggers(procedure) -> list[str]:
    """Tags make good triggers; the name's own words fill in when there are none."""
    tags = [tag.strip().lower() for tag in procedure.tags if tag.strip()]
    if tags:
        return tags[:6]
    return list(_words(procedure.name))[:4]
