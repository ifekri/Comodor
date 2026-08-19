"""Authored skills: parsing the files, and picking the right one.

A skill only earns its place if it arrives when it is relevant and stays out of
the way when it is not, so most of these tests are about what *does not* get
injected.
"""

from __future__ import annotations

import pytest

from comodor.skills import SkillError, SkillRegistry, parse
from comodor.skills import examples

MINIMAL = """\
---
name: review
description: Review a change for correctness
---

Read the whole diff first.
"""


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #


def test_a_minimal_skill_parses():
    skill = parse(MINIMAL)
    assert skill.name == "review"
    assert skill.description == "Review a change for correctness"
    assert skill.instructions == "Read the whole diff first."
    assert skill.enabled and not skill.always


def test_lists_parse_inline_and_as_dashes():
    inline = parse("---\nname: a\ndescription: d\ntriggers: [one, two]\n---\nbody")
    dashed = parse("---\nname: a\ndescription: d\ntriggers:\n  - one\n  - two\n---\nbody")

    assert inline.triggers == ["one", "two"]
    assert dashed.triggers == ["one", "two"]


def test_flags_parse():
    skill = parse("---\nname: a\ndescription: d\nalways: true\nenabled: false\n---\nbody")
    assert skill.always is True
    assert skill.enabled is False


def test_quotes_are_stripped_from_values():
    skill = parse("---\nname: \"review\"\ndescription: 'Check it'\n---\nbody")
    assert skill.name == "review"
    assert skill.description == "Check it"


def test_a_file_without_front_matter_is_rejected_with_an_example():
    with pytest.raises(SkillError) as error:
        parse("Just some notes with no header.")
    assert "front matter" in str(error.value)
    assert "name:" in str(error.value), "the error should show the format"


def test_a_skill_with_no_instructions_is_rejected():
    with pytest.raises(SkillError, match="no instructions"):
        parse("---\nname: a\ndescription: d\n---\n")


def test_a_skill_with_no_name_is_rejected():
    with pytest.raises(SkillError, match="no 'name'"):
        parse("---\ndescription: d\n---\nbody")


def test_a_missing_description_warns_but_still_loads():
    skill = parse("---\nname: a\n---\nbody")
    assert skill.name == "a"
    assert any("description" in warning for warning in skill.warnings)


def test_an_unparseable_header_line_is_reported_not_fatal():
    skill = parse("---\nname: a\ndescription: d\nthis line is nonsense\n---\nbody")
    assert skill.name == "a"
    assert any("expected 'key: value'" in warning for warning in skill.warnings)


# --------------------------------------------------------------------------- #
# discovery
# --------------------------------------------------------------------------- #


def test_the_starter_skills_are_written_and_all_load(tmp_path):
    written = examples.install(tmp_path / "skills")
    assert written

    registry = SkillRegistry()
    count = registry.discover(tmp_path / "skills", tmp_path / "absent")

    assert count == len(written) - 1, "the README is documentation, not a skill"
    assert registry.errors == []
    assert {"review", "explain", "commit-style"} <= set(registry.skills)


def test_installing_twice_does_not_overwrite_edits(tmp_path):
    directory = tmp_path / "skills"
    examples.install(directory)
    (directory / "review.md").write_text(
        "---\nname: review\ndescription: mine\n---\nMy own version.", encoding="utf-8")

    examples.install(directory)
    assert "My own version." in (directory / "review.md").read_text(encoding="utf-8")


def test_one_broken_file_does_not_hide_the_others(tmp_path):
    directory = tmp_path / "skills"
    directory.mkdir()
    (directory / "good.md").write_text(MINIMAL, encoding="utf-8")
    (directory / "broken.md").write_text("no header here", encoding="utf-8")

    registry = SkillRegistry()
    count = registry.discover(directory, tmp_path / "absent")

    assert count == 1
    assert "review" in registry.skills
    assert len(registry.errors) == 1
    assert registry.errors[0][0].name == "broken.md"


def test_a_project_skill_wins_over_a_user_one_of_the_same_name(tmp_path):
    user = tmp_path / "user"
    project = tmp_path / "project"
    user.mkdir()
    project.mkdir()
    (user / "review.md").write_text(
        "---\nname: review\ndescription: the personal one\n---\nyours", encoding="utf-8")
    (project / "review.md").write_text(
        "---\nname: review\ndescription: the team one\n---\ntheirs", encoding="utf-8")

    registry = SkillRegistry()
    registry.discover(user, project)

    assert len(registry) == 1
    assert registry.get("review").description == "the team one"
    assert registry.get("review").scope == "project"


def test_discovery_is_idempotent(tmp_path):
    examples.install(tmp_path / "skills")
    registry = SkillRegistry()
    first = registry.discover(tmp_path / "skills", tmp_path / "absent")
    second = registry.discover(tmp_path / "skills", tmp_path / "absent")

    assert first == second
    assert len(registry) == first


def test_a_missing_folder_is_simply_empty(tmp_path):
    registry = SkillRegistry()
    assert registry.discover(tmp_path / "nope", tmp_path / "also-nope") == 0


# --------------------------------------------------------------------------- #
# matching
# --------------------------------------------------------------------------- #


@pytest.fixture
def loaded(tmp_path):
    examples.install(tmp_path / "skills")
    registry = SkillRegistry()
    registry.discover(tmp_path / "skills", tmp_path / "absent")
    return registry


@pytest.mark.parametrize("request_text,expected", [
    ("review this diff before I merge it", "review"),
    ("explain how the router works", "explain"),
    ("write the commit message for this", "commit-style"),
])
def test_the_right_skill_is_selected(loaded, request_text, expected):
    assert [skill.name for skill in loaded.match(request_text)][:1] == [expected]


def test_an_unrelated_request_selects_nothing(loaded):
    """Injecting a skill that does not apply costs tokens and misleads."""
    assert loaded.match("add two numbers together") == []
    assert loaded.match("what is the capital of France") == []


def test_matching_respects_the_limit(loaded):
    assert len(loaded.match("review and explain this commit diff", limit=1)) == 1


def test_a_disabled_skill_is_never_selected(tmp_path):
    directory = tmp_path / "skills"
    directory.mkdir()
    (directory / "off.md").write_text(
        "---\nname: review\ndescription: Review a diff\nenabled: false\n---\nbody",
        encoding="utf-8")

    registry = SkillRegistry()
    registry.discover(directory, tmp_path / "absent")
    assert registry.match("review this diff") == []


def test_an_always_skill_applies_to_anything(tmp_path):
    directory = tmp_path / "skills"
    directory.mkdir()
    (directory / "house.md").write_text(
        "---\nname: house\ndescription: House rules\nalways: true\n---\nAlways this.",
        encoding="utf-8")

    registry = SkillRegistry()
    registry.discover(directory, tmp_path / "absent")
    assert [skill.name for skill in registry.match("anything at all")] == ["house"]


def test_triggers_widen_what_matches(tmp_path):
    directory = tmp_path / "skills"
    directory.mkdir()
    (directory / "deploy.md").write_text(
        "---\nname: deploy\ndescription: Ship it\ntriggers: [release, publish, rollout]\n"
        "---\nSteps.", encoding="utf-8")

    registry = SkillRegistry()
    registry.discover(directory, tmp_path / "absent")
    assert registry.match("time to publish") != []


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #


def test_the_rendered_block_carries_the_instructions(loaded):
    block = loaded.render(loaded.match("review this diff"))
    assert "### Skill: review" in block
    assert "Read the whole change" in block


def test_nothing_matched_renders_nothing(loaded):
    assert loaded.render([]) == ""


def test_the_block_respects_its_token_budget(loaded):
    everything = loaded.all()
    generous = loaded.render(everything, max_tokens=4000)
    tight = loaded.render(everything, max_tokens=120)

    assert len(tight) < len(generous)
    assert len(tight) // 4 <= 200


# --------------------------------------------------------------------------- #
# in the agent
# --------------------------------------------------------------------------- #


def test_a_matching_skill_reaches_the_system_prompt(config, bus, tmp_path):
    """The whole point: a skill the user wrote governs the next answer."""
    from comodor.agent import AgentLoop, Conversation
    from comodor.providers.base import Role
    from comodor.providers.fake import Script
    from comodor.providers.gateway import Gateway
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry

    directory = tmp_path / "skills"
    directory.mkdir()
    (directory / "review.md").write_text(
        "---\nname: review\ndescription: Review a diff for correctness\n---\n"
        "Read the whole diff before commenting on any of it.", encoding="utf-8")

    registry = SkillRegistry()
    registry.discover(directory, tmp_path / "absent")

    gateway = Gateway(config, scripts=[Script(text="Looks fine.")])
    agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation(),
                      memory=None, skills=registry)
    agent.run("review this diff please")

    prompts = [message.content for call in gateway.provider("fake").calls
               for message in call if message.role is Role.SYSTEM]
    assert any("Read the whole diff before commenting" in prompt for prompt in prompts)


def test_an_unrelated_request_leaves_the_prompt_alone(config, bus, tmp_path):
    from comodor.agent import AgentLoop, Conversation
    from comodor.providers.base import Role
    from comodor.providers.fake import Script
    from comodor.providers.gateway import Gateway
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry

    directory = tmp_path / "skills"
    directory.mkdir()
    (directory / "review.md").write_text(
        "---\nname: review\ndescription: Review a diff for correctness\n---\n"
        "Read the whole diff first.", encoding="utf-8")

    registry = SkillRegistry()
    registry.discover(directory, tmp_path / "absent")

    gateway = Gateway(config, scripts=[Script(text="42")])
    agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation(),
                      memory=None, skills=registry)
    agent.run("what is six times seven")

    prompts = [message.content for call in gateway.provider("fake").calls
               for message in call if message.role is Role.SYSTEM]
    assert not any("Read the whole diff" in prompt for prompt in prompts)


def test_skills_work_with_the_learning_brain_switched_off(config, bus, tmp_path):
    """The two systems are independent; one being off must not disable the other."""
    from comodor.agent import AgentLoop, Conversation
    from comodor.providers.base import Role
    from comodor.providers.fake import Script
    from comodor.providers.gateway import Gateway
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry

    config.learning.enabled = False
    directory = tmp_path / "skills"
    directory.mkdir()
    (directory / "always.md").write_text(
        "---\nname: house\ndescription: House rules\nalways: true\n---\n"
        "Keep answers under three sentences.", encoding="utf-8")

    registry = SkillRegistry()
    registry.discover(directory, tmp_path / "absent")

    gateway = Gateway(config, scripts=[Script(text="ok")])
    agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation(),
                      memory=None, skills=registry)
    agent.run("anything")

    prompts = [message.content for call in gateway.provider("fake").calls
               for message in call if message.role is Role.SYSTEM]
    assert any("under three sentences" in prompt for prompt in prompts)


def test_a_headless_run_loads_skills_too(tmp_path, monkeypatch, capsys):
    """A convention that holds at a prompt and lapses in CI is not a convention."""
    import argparse

    from comodor import cli
    from comodor.config import ProviderConfig, load
    from comodor.providers.base import Role
    from comodor.providers.fake import Script
    from comodor.providers.gateway import Gateway

    home = tmp_path / "home"
    project = tmp_path / "project"
    (project / ".comodor" / "skills").mkdir(parents=True)
    (project / ".comodor" / "skills" / "review.md").write_text(
        "---\nname: review\ndescription: Review a change for correctness\n---\n"
        "Read the whole diff before commenting.", encoding="utf-8")
    monkeypatch.setenv("COMODOR_HOME", str(home))

    config = load(cwd=project, use_environment=False)
    config.providers["fake"] = ProviderConfig(
        name="fake", kind="fake", base_url="offline", api_key="demo",
        model="scripted", configured=True)
    config.provider = "fake"

    # Hold the provider itself: `run_headless` closes the gateway when it is
    # done, which drops its instances, so asking for it afterwards would build
    # a fresh one that has recorded nothing.
    recorded = []

    def scripted(configuration, scripts=None):
        gateway = Gateway(configuration, scripts=[Script(text="Looks fine.")])
        recorded.append(gateway.provider("fake"))
        return gateway

    monkeypatch.setattr("comodor.providers.gateway.Gateway", scripted)

    args = argparse.Namespace(task="review this diff", yes=True, json=False,
                              max_steps=2)
    cli.run_headless(config, args)

    assert recorded, "the run should have built a gateway"
    prompts = [message.content for call in recorded[0].calls
               for message in call if message.role is Role.SYSTEM]
    assert any("Read the whole diff before commenting" in prompt for prompt in prompts)


def test_the_shared_loader_writes_the_examples_once(tmp_path, monkeypatch):
    from comodor.config import load
    from comodor.skills import load_for

    monkeypatch.setenv("COMODOR_HOME", str(tmp_path / "home"))
    config = load(cwd=tmp_path, use_environment=False)

    first = load_for(config)
    assert len(first) >= 3, "a first run should arrive with something to read"

    (config.paths.skills / "review.md").write_text(
        "---\nname: review\ndescription: mine\n---\nMy own version.", encoding="utf-8")
    load_for(config)
    assert "My own version." in (config.paths.skills / "review.md").read_text(encoding="utf-8")


def test_skills_switched_off_load_nothing_and_touch_no_disk(tmp_path, monkeypatch):
    from comodor.config import load
    from comodor.skills import load_for

    monkeypatch.setenv("COMODOR_HOME", str(tmp_path / "home"))
    config = load(cwd=tmp_path, use_environment=False)
    config.skills.enabled = False

    assert len(load_for(config)) == 0
    assert not config.paths.skills.exists(), "a disabled feature should not create folders"
