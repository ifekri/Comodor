"""Finding the right skill for the task in front of the agent.

Skills come from two places, and both matter for different reasons. The user
folder travels with the person — how they like commits written, which checks
they always want run. The project folder travels with the code and can be
committed, so a team's conventions arrive with a clone rather than in an
onboarding document.

Matching reuses the same index the learning brain uses, so a skill is selected
in microseconds and the cost does not grow as a collection does.
"""

from __future__ import annotations

from pathlib import Path

from ..learning.hotindex import HotIndex
from .loader import MANIFEST, Skill, SkillError, load

SKILL_SUFFIXES = (".md", ".markdown")
#: A skill must cover this share of the request's terms to be worth injecting.
#:
#: One term in three, written as the fraction rather than as 0.34. It was the
#: decimal, and the decimal quietly excluded the case it was meant to admit:
#: "build a brutalist dashboard" covers one of its three terms, scores 0.333,
#: and was rejected by seven thousandths — while ranking first.
MATCH_FLOOR = 1 / 3


class SkillRegistry:
    """Every skill available in this session, and which ones fit a request."""

    def __init__(self) -> None:
        self.skills: dict[str, Skill] = {}
        self.errors: list[tuple[Path, str]] = []
        self._index = HotIndex()
        self._next_id = 1
        self._ids: dict[int, str] = {}

    # -- discovery -------------------------------------------------------- #

    def load_from(self, directory: Path, scope: str = "user") -> int:
        """Read every skill in a directory. Returns how many loaded."""
        if not directory.is_dir():
            return 0

        found = 0
        for path in self._candidates(directory):
            try:
                skill = load(path, scope=scope)
            except (SkillError, OSError) as error:
                # Reported, never fatal: one malformed file must not take the
                # rest of somebody's collection out of service.
                self.errors.append((path, str(error)))
                continue
            self.add(skill)
            found += 1
        return found

    @staticmethod
    def _candidates(directory: Path) -> list[Path]:
        """Skill directories first, then loose files that are not part of one.

        A folder holding a SKILL.md is one skill, not one per Markdown file in
        it — otherwise every `references/REFERENCE.md` would be read as a broken
        skill and reported as an error the user cannot act on.
        """
        folders = [path for path in sorted(directory.iterdir())
                   if path.is_dir() and (path / MANIFEST).is_file()]
        claimed = {folder.resolve() for folder in folders}

        loose: list[Path] = []
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SKILL_SUFFIXES:
                continue
            if path.name.upper() in ("README.MD", "README.MARKDOWN"):
                continue
            if any(parent.resolve() in claimed for parent in path.parents):
                continue
            loose.append(path)

        return folders + loose

    def add(self, skill: Skill) -> Skill:
        """Register a skill. A project skill shadows a user one of the name."""
        existing = self.skills.get(skill.name)
        if existing is not None and existing.scope == "project" and skill.scope != "project":
            return existing

        self.skills[skill.name] = skill
        identifier = self._next_id
        self._next_id += 1
        self._ids[identifier] = skill.name
        self._index.add("skill", identifier, skill.text, skill.scope)
        return skill

    def discover(self, user_dir: Path, project_dir: Path) -> int:
        """Load user skills, then project skills, which take precedence."""
        self.skills.clear()
        self.errors.clear()
        self._index.clear()
        self._ids.clear()
        self._next_id = 1

        total = self.load_from(user_dir, scope="user")
        total += self.load_from(project_dir, scope="project")
        return total

    # -- selection -------------------------------------------------------- #

    def match(self, query: str, limit: int = 2) -> list[Skill]:
        """The skills worth spending context on for this request."""
        always = [skill for skill in self.skills.values()
                  if skill.enabled and skill.always]
        if not query.strip():
            return always[:limit]

        chosen: list[Skill] = list(always)
        seen = {skill.name for skill in chosen}

        for doc, score in self._index.coverage_scan(query, kind="skill", limit=limit * 4):
            if score < MATCH_FLOOR:
                continue
            name = self._ids.get(doc.id)
            skill = self.skills.get(name) if name else None
            if skill is None or not skill.enabled or skill.name in seen:
                continue
            chosen.append(skill)
            seen.add(skill.name)
            if len(chosen) >= limit:
                break
        return chosen[:limit]

    HEADER = ("Skills — procedures this user has written for situations like "
              "this one. Follow them unless the request says otherwise.")

    def fit(self, skills: list[Skill], max_tokens: int = 1200
            ) -> tuple[list[Skill], list[Skill]]:
        """Split a match into what the budget admits and what it cannot.

        Separated from :meth:`render` because the caller has to know. A skill
        that matched and was then discarded for space is the one case where
        saying nothing is worst: the user wrote it, it was the right skill, and
        the answer comes back as though they had never written it.

        A skill too large to fit is skipped rather than treated as the end of
        the list. Ranking puts the best match first, not the smallest, so one
        oversized skill at the top used to discard every skill behind it.
        """
        used = len(self.HEADER) // 4
        kept: list[Skill] = []
        dropped: list[Skill] = []

        for skill in skills:
            cost = len(skill.render()) // 4 + 2
            if used + cost > max_tokens:
                dropped.append(skill)
                continue
            kept.append(skill)
            used += cost
        return kept, dropped

    def render(self, skills: list[Skill], max_tokens: int = 1200) -> str:
        """The block injected for this turn, within a budget."""
        if not skills:
            return ""
        kept, _ = self.fit(skills, max_tokens)
        if not kept:
            return ""
        return "\n\n".join([self.HEADER] + [skill.render() for skill in kept])

    # -- introspection ---------------------------------------------------- #

    def get(self, name: str) -> Skill | None:
        return self.skills.get(name)

    def all(self) -> list[Skill]:
        return sorted(self.skills.values(), key=lambda skill: skill.name)

    def __len__(self) -> int:
        return len(self.skills)


def load_for(config) -> SkillRegistry:
    """The registry a session should use, given a configuration.

    Both entry points call this, so a skill applies whether the agent was
    started as an interface or invoked from a script. Skills that only worked
    interactively would be worse than no skills at all: a team convention that
    holds at a prompt and lapses in CI is a convention nobody can rely on.
    """
    from . import examples

    registry = SkillRegistry()
    if not config.skills.enabled:
        return registry

    user_dir = config.paths.skills
    if config.skills.install_examples and not user_dir.exists():
        try:
            examples.install(user_dir)
        except OSError:
            pass                      # a read-only home is not worth failing over
    registry.discover(user_dir, config.paths.project_skills)
    return registry
