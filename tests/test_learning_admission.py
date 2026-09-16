"""The admission gate: nothing durable without an admissible provenance
(T102; FR-056, FR-057, SC-018; contracts/learning-record.md §L1).

Six classes may enter. A model's own assertion is none of them, so a
reflected lesson or a reviewed fact is stored only once the transcript it
came from corroborates it — the person said it, or an observing tool showed
it. The gate is the store's own door, so no caller reaches durable storage
around it; and it is mutation-checked: with corroboration stubbed to always
succeed, an uncorroborated proposal lands, which is what the gate prevents.
"""

from __future__ import annotations

import json

import pytest

from comodor.learning import BrainStore, LearningEngine
from comodor.learning import memory as memory_module
from comodor.learning.facts import FactService
from comodor.learning.review import Reviewer
from comodor.learning.store import PROVENANCES, Fact, InadmissibleRecord, Lesson
from comodor.providers.base import Message


class FakeGateway:
    """Answers every pass with the next scripted reply."""

    model = ""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)

    def stream(self, messages, **kwargs):
        from comodor.providers.base import EventType, StreamEvent
        from comodor.providers.fake import Usage

        reply = self.replies.pop(0) if self.replies else "{}"
        yield StreamEvent(type=EventType.TEXT, text=reply)
        yield StreamEvent(type=EventType.USAGE, usage=Usage(input_tokens=10, output_tokens=5))


def _reflection(guidance: str) -> str:
    return "```json\n" + json.dumps({
        "lessons": [{"kind": "heuristic", "trigger": "generally",
                     "guidance": guidance, "confidence": 0.8}],
        "skill": None,
    }) + "\n```"


@pytest.fixture
def store(tmp_path):
    store = BrainStore(tmp_path / "brain.db", async_writes=False)
    yield store
    store.close()


# --------------------------------------------------------------------------- #
# the store is the door
# --------------------------------------------------------------------------- #


def test_the_six_classes_are_exactly_the_contract(store):
    assert set(PROVENANCES) == {"user_correction", "user_statement", "settled_decision",
                                "counted_convention", "validated_outcome", "tool_confirmed"}


@pytest.mark.parametrize("provenance", ["", "model_assertion", "reflection", "guess"])
def test_a_lesson_without_an_admissible_provenance_is_not_storable(store, provenance):
    with pytest.raises(InadmissibleRecord):
        store.add_lesson(Lesson(guidance="a thing the model believes", provenance=provenance))
    assert store.all_lessons() == []


@pytest.mark.parametrize("provenance", ["", "model_assertion"])
def test_a_fact_without_an_admissible_provenance_is_not_storable(store, provenance):
    with pytest.raises(InadmissibleRecord):
        store.add_fact(Fact(text="the database is MySQL", provenance=provenance))
    assert store.all_facts(settled_only=False) == []


@pytest.mark.parametrize("provenance", ["", "model_assertion"])
def test_a_rule_without_an_admissible_provenance_is_not_storable(store, provenance):
    with pytest.raises(InadmissibleRecord):
        store.observe_rule(key="x.y", scope="global", statement="Do it this way.",
                           provenance=provenance)
    assert store.all_rules() == []


def test_a_derived_item_must_name_its_source(store):
    with pytest.raises(InadmissibleRecord):
        store.add_fact(Fact(text="config sets DEBUG", provenance="tool_confirmed"))
    stored = store.add_fact(Fact(text="config sets DEBUG", provenance="tool_confirmed",
                                 source_ref="read_file:config.py"))
    assert stored is not None and stored.provenance == "tool_confirmed"


def test_the_service_turns_the_refusal_into_its_own_error(store):
    from comodor.learning.facts import FactError

    service = FactService(store, scopes=["global"], write_scope="global")
    with pytest.raises(FactError):
        service.add("the database is MySQL", provenance="model_assertion")
    assert service.entries() == []


# --------------------------------------------------------------------------- #
# model-driven passes go through the gate (T101)
# --------------------------------------------------------------------------- #


def test_reflection_refuses_a_lesson_nothing_in_the_episode_backs(config, bus, store):
    config.learning.review = False
    engine = LearningEngine(config, bus, FakeGateway([_reflection(
        "Deploy with the makefile target, never the raw docker command.")]), store=store)
    seen = []
    bus.subscribe(lambda event: seen.append(event))
    try:
        engine.record_outcome(goal="fix the parser",
                              messages=[Message.user("fix the parser"),
                                        Message.assistant("Fixed the parser.")],
                              recalled=[], success=True, stopped="done", steps=1, elapsed=0.1)
        engine.wait_for_reflection(timeout=10.0)
        assert store.all_lessons() == [], "a model assertion on its own is not storable"
        learned = [event for event in seen if event.payload.get("action") == "learned"]
        assert learned and learned[-1].payload.get("refused") == 1
    finally:
        engine.close()


def test_reflection_stores_a_lesson_the_person_stated(config, bus, store):
    config.learning.review = False
    engine = LearningEngine(config, bus, FakeGateway([_reflection(
        "Deploy with the makefile target, never the raw docker command.")]), store=store)
    try:
        engine.record_outcome(
            goal="deploy", recalled=[], success=True, stopped="done", steps=1, elapsed=0.1,
            messages=[Message.user("deploy — with the makefile target, never the raw "
                                   "docker command")])
        engine.wait_for_reflection(timeout=10.0)
        lessons = store.all_lessons()
        assert [lesson.provenance for lesson in lessons] == ["user_statement"]
    finally:
        engine.close()


def test_the_review_refuses_a_fact_nothing_in_the_transcript_backs(store):
    service = FactService(store, scopes=["global"], write_scope="global")
    reviewer = Reviewer(service, FakeGateway([json.dumps(
        {"facts": [{"kind": "memory", "text": "The CI runner is Linux only"}]})]))
    result = reviewer.review([Message.user("make the tests pass")], "done")
    assert service.entries() == []
    assert [fact.text for fact in result.refused] == ["The CI runner is Linux only"]


def test_the_review_keeps_a_fact_a_tool_showed_as_tool_confirmed(store, tmp_path):
    target = tmp_path / "ci.yml"
    target.write_text("runs-on: ubuntu-latest\n", encoding="utf-8")
    shown = Message.tool("c1", "read_file", "runs-on: ubuntu-latest — the CI runner is Linux only")
    shown.meta["path"] = str(target)
    service = FactService(store, scopes=["global"], write_scope="global")
    reviewer = Reviewer(service, FakeGateway([json.dumps(
        {"facts": [{"kind": "memory", "text": "The CI runner is Linux only"}]})]))
    reviewer.review([Message.user("check the CI"), shown], "done")
    [fact] = service.entries()
    assert fact.provenance == "tool_confirmed"
    assert fact.source_ref.startswith("read_file:")
    assert fact.fingerprint and fact.fingerprint != "runs-on"


def test_assistant_text_corroborates_nothing():
    assert memory_module.corroborate(
        "the database is MySQL",
        [Message.assistant("I am sure the database is MySQL")]) == ("", "", "")


# --------------------------------------------------------------------------- #
# after an episode with learning on, nothing model-only exists (SC-018)
# --------------------------------------------------------------------------- #


def test_after_a_learning_episode_every_stored_item_has_an_admissible_origin(
        config, bus, store):
    engine = LearningEngine(config, bus, FakeGateway([
        _reflection("Run the linter before finishing."),
        json.dumps({"facts": [{"kind": "memory", "text": "Lint with ruff before finishing"}]}),
    ]), store=store)
    try:
        engine.teach("linting: run ruff before finishing")
        engine.record_outcome(
            goal="lint", recalled=[], success=True, stopped="done", steps=1, elapsed=0.1,
            messages=[Message.user("lint with ruff before finishing")])
        engine.wait_for_reflection(timeout=10.0)
    finally:
        engine.close()
    everything = ([("lesson", item.provenance) for item in store.all_lessons()]
                  + [("rule", item.provenance) for item in store.all_rules()]
                  + [("fact", item.provenance) for item in store.all_facts(settled_only=False)])
    assert everything, "the episode stored something"
    assert all(provenance in PROVENANCES for _, provenance in everything), everything


# --------------------------------------------------------------------------- #
# mutation check: corroboration is what holds the door
# --------------------------------------------------------------------------- #


def test_mutation_stubbing_corroboration_lets_the_assertion_through(
        config, bus, store, monkeypatch):
    config.learning.review = False
    real = memory_module.corroborate
    monkeypatch.setattr(memory_module, "corroborate",
                        lambda text, messages: ("user_statement", "stub", ""))
    engine = LearningEngine(config, bus, FakeGateway([_reflection(
        "Deploy with the makefile target.")]), store=store)
    try:
        engine.record_outcome(goal="deploy", messages=[Message.user("deploy")],
                              recalled=[], success=True, stopped="done", steps=1, elapsed=0.1)
        engine.wait_for_reflection(timeout=10.0)
    finally:
        engine.close()
    assert len(store.all_lessons()) == 1, "with the gate stubbed, the assertion lands"

    monkeypatch.setattr(memory_module, "corroborate", real)
    fresh = BrainStore(store.path.parent / "fresh.db", async_writes=False)
    engine = LearningEngine(config, bus, FakeGateway([_reflection(
        "Deploy with the makefile target.")]), store=fresh)
    try:
        engine.record_outcome(goal="deploy", messages=[Message.user("deploy")],
                              recalled=[], success=True, stopped="done", steps=1, elapsed=0.1)
        engine.wait_for_reflection(timeout=10.0)
        assert fresh.all_lessons() == [], "with the gate restored, it is refused"
    finally:
        engine.close()
