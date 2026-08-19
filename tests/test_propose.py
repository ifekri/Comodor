"""Promoting a learned procedure into a skill file the user owns.

The risk this feature carries is not that it proposes too little — it is that it
proposes too much, or writes without being asked. Most of what follows checks
that it stays quiet.
"""

from __future__ import annotations

import pytest

from comodor.learning.store import Skill as Procedure
from comodor.skills import SkillRegistry, candidates, load, parse
from comodor.skills.propose import MIN_SUCCESS, MIN_USES


def procedure(name="add-a-rest-endpoint", uses=5, wins=4, losses=1, steps=None,
              description="Add an endpoint with a test", tags=("api", "endpoint")):
    return Procedure(
        name=name, description=description,
        steps=list(steps if steps is not None else
                   ["Find the router module", "Add the route",
                    "Write a test", "Run the suite"]),
        tags=list(tags), uses=uses, wins=wins, losses=losses)


# --------------------------------------------------------------------------- #
# what earns an offer
# --------------------------------------------------------------------------- #


def test_a_proven_procedure_is_offered():
    offers = candidates([procedure()], registry=None)
    assert [offer.name for offer in offers] == ["add-a-rest-endpoint"]
    assert offers[0].uses == 5


def test_something_done_once_is_not_a_procedure():
    """Once is an anecdote. The threshold is what makes 'yes' mean something."""
    assert candidates([procedure(uses=1, wins=1, losses=0)], registry=None) == []
    assert candidates([procedure(uses=MIN_USES - 1, wins=MIN_USES - 1, losses=0)],
                      registry=None) == []


def test_a_procedure_that_usually_fails_is_not_offered():
    assert candidates([procedure(uses=10, wins=2, losses=8)], registry=None) == []


def test_a_single_step_is_not_a_procedure():
    assert candidates([procedure(steps=["Just do it"])], registry=None) == []


def test_the_success_floor_is_respected_exactly():
    low = procedure(uses=10, wins=int(MIN_SUCCESS * 10) - 1,
                    losses=10 - int(MIN_SUCCESS * 10) + 1)
    assert candidates([low], registry=None) == []


def test_offers_are_ordered_by_how_well_proven_they_are():
    offers = candidates([procedure(name="rare", uses=3, wins=3, losses=0),
                         procedure(name="common", uses=20, wins=18, losses=2)],
                        registry=None)
    assert [offer.name for offer in offers] == ["common", "rare"]


def test_the_offer_list_is_capped():
    many = [procedure(name=f"thing-{index}") for index in range(20)]
    assert len(candidates(many, registry=None)) <= 5


# --------------------------------------------------------------------------- #
# not proposing what the user already wrote
# --------------------------------------------------------------------------- #


def test_a_procedure_the_user_already_covered_is_not_offered(tmp_path):
    folder = tmp_path / "skills"
    folder.mkdir()
    (folder / "endpoints.md").write_text(
        "---\nname: add-a-rest-endpoint\n"
        "description: Add an endpoint with a test\n---\n"
        "Find the router, add the route, write a test, run the suite.",
        encoding="utf-8")

    registry = SkillRegistry()
    registry.discover(folder, tmp_path / "absent")

    assert candidates([procedure()], registry) == []


def test_an_unrelated_authored_skill_does_not_block_the_offer(tmp_path):
    folder = tmp_path / "skills"
    folder.mkdir()
    (folder / "commit.md").write_text(
        "---\nname: commit-style\ndescription: How to write commit messages\n---\n"
        "Say why, not what.", encoding="utf-8")

    registry = SkillRegistry()
    registry.discover(folder, tmp_path / "absent")

    assert candidates([procedure()], registry)


# --------------------------------------------------------------------------- #
# what gets written
# --------------------------------------------------------------------------- #


def test_the_draft_is_a_valid_skill():
    """Whatever is offered has to load, or approving it produces a broken file."""
    offer = candidates([procedure()], registry=None)[0]
    skill = parse(offer.render())

    assert skill.name == "add-a-rest-endpoint"
    assert skill.description
    assert skill.instructions
    assert skill.warnings == [], skill.warnings


def test_the_name_is_portable_or_the_offer_is_dropped():
    """A name the open format rejects would be a file other agents cannot read."""
    offer = candidates([procedure(name="Add A REST Endpoint!!")], registry=None)[0]
    assert offer.name == "add-a-rest-endpoint"

    assert candidates([procedure(name="!!!")], registry=None) == []


def test_the_description_says_when_to_use_it():
    """It is the only text matched against a request; without an occasion it never fires."""
    offer = candidates([procedure()], registry=None)[0]
    assert "Use when" in offer.description


def test_adopting_writes_a_skill_folder_that_loads(tmp_path):
    offer = candidates([procedure()], registry=None)[0]
    written = offer.write(tmp_path)

    assert written.name == "SKILL.md"
    assert written.parent.name == "add-a-rest-endpoint"

    skill = load(written.parent)
    assert skill.name == "add-a-rest-endpoint"
    assert "Run the suite" in skill.instructions


def test_the_written_file_records_where_it_came_from(tmp_path):
    """A file the agent drafted should say so, or it looks like the user's own."""
    offer = candidates([procedure()], registry=None)[0]
    skill = load(offer.write(tmp_path).parent)

    assert skill.metadata.get("origin") == "learned"
    assert skill.metadata.get("learned-on")


def test_adopting_twice_refuses_rather_than_overwriting(tmp_path):
    offer = candidates([procedure()], registry=None)[0]
    offer.write(tmp_path)

    with pytest.raises(FileExistsError):
        offer.write(tmp_path)


def test_a_hand_written_file_of_the_same_name_is_not_clobbered(tmp_path):
    offer = candidates([procedure()], registry=None)[0]
    (tmp_path / f"{offer.name}.md").write_text(
        "---\nname: add-a-rest-endpoint\ndescription: mine\n---\nMy own version.",
        encoding="utf-8")

    with pytest.raises(FileExistsError):
        offer.write(tmp_path)
    assert "My own version." in (tmp_path / f"{offer.name}.md").read_text(encoding="utf-8")


def test_a_written_skill_is_then_discovered_normally(tmp_path):
    offer = candidates([procedure()], registry=None)[0]
    offer.write(tmp_path)

    registry = SkillRegistry()
    assert registry.discover(tmp_path, tmp_path / "absent") == 1
    assert registry.match("add a rest endpoint with a test")


def test_an_adopted_skill_is_no_longer_proposed(tmp_path):
    """Otherwise the same draft is offered forever, after the user accepted it."""
    proven = procedure()
    offer = candidates([proven], registry=None)[0]
    offer.write(tmp_path)

    registry = SkillRegistry()
    registry.discover(tmp_path, tmp_path / "absent")
    assert candidates([proven], registry) == []


def test_an_adopted_skill_is_not_re_proposed_when_the_name_needed_a_slug(tmp_path):
    """The realistic case: reflection names procedures in prose, files are slugs.

    Comparing the two raw forms offers the same draft again on every start,
    immediately after the user accepted it — which is the failure that would
    make the feature actively annoying rather than merely quiet.
    """
    proven = procedure(name="Add a REST endpoint")
    offer = candidates([proven], registry=None)[0]
    assert offer.name == "add-a-rest-endpoint"
    offer.write(tmp_path)

    registry = SkillRegistry()
    registry.discover(tmp_path, tmp_path / "absent")
    assert candidates([proven], registry) == []
