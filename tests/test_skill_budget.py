"""A matched skill that never travels, and never says it did not.

The published library is a dozen authored skills running from two to ten
thousand tokens each. The budget that decided which of them reached the model
was 1,200 — the size of the sample skill and nothing else — so eleven of
thirteen matched the right question, were selected, and were then thrown away
before the request was built. Nothing anywhere said so, and the interface
announced them as being in play while it did it.

These are the three separate defects that produced that, each checked on its
own, because each of them alone is enough to lose a skill silently.
"""

from __future__ import annotations

from comodor.agent import AgentLoop, Conversation
from comodor.config import SkillsConfig
from comodor.events import Kind
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.skills.loader import Skill
from comodor.skills.registry import SkillRegistry
from comodor.tools import ToolRegistry


def skill(name: str, tokens: int) -> Skill:
    """A skill of roughly the requested size, in tokens."""
    return Skill(name=name, description=f"about {name}",
                 instructions="word " * (tokens * 4 // 5),
                 triggers=[name])


def registry_of(*skills: Skill) -> SkillRegistry:
    registry = SkillRegistry()
    for item in skills:
        registry.add(item)          # add(), so the matcher's index is built too
    return registry


# --------------------------------------------------------------------------- #
# one oversized skill used to discard every skill behind it
# --------------------------------------------------------------------------- #


def test_a_skill_too_large_to_fit_is_skipped_not_treated_as_the_end():
    """Ranking puts the best match first, not the smallest. Stopping at the
    first one that does not fit throws away everything after it."""
    big, small = skill("big", 5_000), skill("small", 200)

    kept, dropped = registry_of(big, small).fit([big, small], max_tokens=1_000)

    assert [item.name for item in kept] == ["small"]
    assert [item.name for item in dropped] == ["big"]


def test_what_fits_is_rendered_and_what_does_not_is_absent():
    big, small = skill("big", 5_000), skill("small", 200)

    block = registry_of(big, small).render([big, small], max_tokens=1_000)

    assert "small" in block
    assert "big" not in block


def test_a_budget_nothing_fits_in_renders_nothing_at_all():
    """Not a bare header claiming skills that are not there."""
    big = skill("big", 5_000)

    assert registry_of(big).render([big], max_tokens=100) == ""


def test_everything_fits_when_the_budget_allows_it():
    one, two = skill("one", 400), skill("two", 400)

    kept, dropped = registry_of(one, two).fit([one, two], max_tokens=12_000)

    assert len(kept) == 2 and dropped == []


# --------------------------------------------------------------------------- #
# the drop was silent
# --------------------------------------------------------------------------- #


def test_a_dropped_skill_says_so(config, bus):
    """The one case where saying nothing is worst: the user wrote the skill, it
    was the right skill, and the answer comes back as if they never had."""
    config.skills.max_tokens = 500
    registry = registry_of(skill("huge", 5_000))
    notices: list[str] = []
    bus.subscribe(lambda event: notices.append(event.text)
                  if event.kind is Kind.NOTICE else None)

    gateway = Gateway(config, scripts=[Script(text="ok")])
    AgentLoop(config, gateway, ToolRegistry(), bus, PermissionEngine(config, bus),
              Conversation(), skills=registry).run("huge")

    assert any("huge" in text and "skills.max_tokens" in text for text in notices), \
        f"nothing told the user the skill was discarded: {notices}"


def test_the_announcement_is_of_what_travelled_not_what_matched(config, bus):
    """Announcing the match tells the user a skill is shaping the answer when
    it has already been thrown away."""
    config.skills.max_tokens = 500
    registry = registry_of(skill("huge", 5_000))
    announced: list[list] = []
    bus.subscribe(lambda event: announced.append(event.get("items"))
                  if event.kind is Kind.MEMORY
                  and event.get("action") == "skills" else None)

    gateway = Gateway(config, scripts=[Script(text="ok")])
    agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation(),
                      skills=registry)
    agent.run("huge")

    assert announced == [], "a discarded skill was announced as being in play"
    assert agent._skills_used == []


def test_a_skill_that_fits_is_still_announced(config, bus):
    config.skills.max_tokens = 12_000
    registry = registry_of(skill("small", 200))
    announced: list[list] = []
    bus.subscribe(lambda event: announced.append(event.get("items"))
                  if event.kind is Kind.MEMORY
                  and event.get("action") == "skills" else None)

    gateway = Gateway(config, scripts=[Script(text="ok")])
    AgentLoop(config, gateway, ToolRegistry(), bus, PermissionEngine(config, bus),
              Conversation(), skills=registry).run("small")

    assert announced and announced[0][0]["name"] == "small"


# --------------------------------------------------------------------------- #
# the budget was sized for the sample skill
# --------------------------------------------------------------------------- #


def test_the_default_budget_admits_a_real_authored_skill():
    """Every skill in the published library is between two and ten thousand
    tokens. A budget under that is a library nobody can use."""
    assert SkillsConfig().max_tokens >= 10_000


def test_a_ten_thousand_token_skill_reaches_the_model(config, bus):
    """The largest in the library, end to end through the real loop."""
    config.skills.max_tokens = SkillsConfig().max_tokens
    registry = registry_of(skill("enormous", 10_000))

    gateway = Gateway(config, scripts=[Script(text="ok")])
    AgentLoop(config, gateway, ToolRegistry(), bus, PermissionEngine(config, bus),
              Conversation(), skills=registry).run("enormous")

    sent = "".join(message.briefing for call in gateway.provider("fake").calls
                   for message in call)
    assert "enormous" in sent


# --------------------------------------------------------------------------- #
# a skill's folder and the name it calls itself are not the same string
# --------------------------------------------------------------------------- #


def test_the_version_is_read_from_the_folder_not_the_declared_name(tmp_path):
    """A skill in `brutalist/` may announce itself as `industrial-brutalist-ui`.
    Looking the install stamp up by the declared name simply misses, and a
    managed skill then shows no version and reads as one written by hand."""
    import json

    from comodor.skills import catalogue as library
    from comodor.skills.commands import _folder_of

    root = tmp_path / "skills"
    folder = root / "brutalist"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: industrial-brutalist-ui\ndescription: Raw interfaces\n---\n\nUse grids.\n",
        encoding="utf-8")
    (folder / library.STAMP).write_text(
        json.dumps({"id": "brutalist", "version": "1.0.0", "files": ["SKILL.md"]}),
        encoding="utf-8")

    registry = SkillRegistry()
    registry.discover(root, root)
    loaded = registry.all()[0]

    assert loaded.name == "industrial-brutalist-ui"
    assert _folder_of(loaded, root) == "brutalist"
    assert library.installed(root, _folder_of(loaded, root)).version == "1.0.0"
    assert library.installed(root, loaded.name).version == "", \
        "this is the lookup that used to be made, and it finds nothing"


def test_a_single_file_skill_still_resolves_to_something(tmp_path):
    """`~/.comodor/skills/mine.md` has no folder of its own."""
    from comodor.skills.commands import _folder_of

    root = tmp_path / "skills"
    root.mkdir(parents=True)
    (root / "mine.md").write_text(
        "---\nname: mine\ndescription: Something of my own\n---\n\nDo it my way.\n",
        encoding="utf-8")

    registry = SkillRegistry()
    registry.discover(root, root)

    assert _folder_of(registry.all()[0], root) == "mine"


def test_a_paragraph_of_description_is_cut_to_a_line_or_two():
    from comodor.skills.commands import DESCRIPTION_CHARS, _trim

    long = "word " * 200
    trimmed = _trim(long)

    assert len(trimmed) <= DESCRIPTION_CHARS + 1
    assert trimmed.endswith("…")
    assert _trim("short enough") == "short enough"
    assert _trim("") == ""
