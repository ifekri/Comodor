"""The brain: storage, ranking, reinforcement, and the improvement it produces."""

from __future__ import annotations

import json
import time

import pytest

from comodor.agent import AgentLoop, Conversation
from comodor.learning import BrainStore, LearningEngine
from comodor.learning.bm25 import BM25Index, similarity, tokenize
from comodor.learning.reflect import extract_json, parse_reflection
from comodor.learning.store import Lesson, score
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry


# --------------------------------------------------------------------------- #
# ranking primitives
# --------------------------------------------------------------------------- #


def test_bm25_ranks_the_relevant_document_first():
    index = BM25Index()
    index.add("a", "run the test suite with pytest and check coverage")
    index.add("b", "deploy the container image to production")
    index.add("c", "pytest fixtures live in conftest")

    ranked = index.search("how do I run pytest")
    assert ranked[0][0] in ("a", "c")
    assert "b" not in [doc for doc, _ in ranked]


def test_bm25_removal_keeps_the_index_consistent():
    index = BM25Index()
    index.add("a", "alpha beta")
    index.add("b", "beta gamma")
    index.remove("a")
    assert len(index) == 1
    assert [doc for doc, _ in index.search("alpha")] == []


def test_tokenizer_keeps_identifiers_whole_and_drops_stopwords():
    tokens = tokenize("The read_file tool is in src/tools/fs.py")
    assert "read_file" in tokens
    assert "the" not in tokens


def test_similarity_detects_a_restatement():
    left = "always run pytest -q instead of unittest"
    right = "run pytest -q rather than unittest always"
    assert similarity(left, right) > 0.6
    assert similarity(left, "deploy with docker compose up") < 0.2


# --------------------------------------------------------------------------- #
# confidence
# --------------------------------------------------------------------------- #


def test_confidence_rises_with_wins_and_falls_with_losses():
    neutral = Lesson(confidence=0.5)
    winner = Lesson(confidence=0.5, wins=8, losses=0)
    loser = Lesson(confidence=0.5, wins=0, losses=8)

    assert winner.effective_confidence() > neutral.effective_confidence()
    assert loser.effective_confidence() < neutral.effective_confidence()
    assert winner.effective_confidence() == pytest.approx(0.7, abs=0.01)
    assert loser.effective_confidence() == pytest.approx(0.3, abs=0.01)


def test_confidence_decays_with_age():
    fresh = Lesson(confidence=0.8, updated_at=time.time())
    stale = Lesson(confidence=0.8, updated_at=time.time() - 90 * 86400)
    assert stale.effective_confidence(half_life_days=45) < fresh.effective_confidence() / 2


def test_pinned_lessons_never_decay():
    pinned = Lesson(confidence=0.2, pinned=True,
                    updated_at=time.time() - 400 * 86400)
    assert pinned.effective_confidence() == 1.0


def test_score_prefers_a_trusted_lesson_over_a_slightly_better_match():
    trusted = Lesson(confidence=0.9, wins=10)
    doubted = Lesson(confidence=0.2, losses=10)
    assert score(3.0, trusted, 45.0) > score(4.0, doubted, 45.0)


# --------------------------------------------------------------------------- #
# store
# --------------------------------------------------------------------------- #


def test_store_round_trip_and_search(tmp_path):
    store = BrainStore(tmp_path / "brain.db")
    store.add_lesson(Lesson(kind="pitfall", trigger="running pip on windows",
                            guidance="Use python -m pip so the right interpreter runs."))
    store.add_lesson(Lesson(kind="fact", trigger="the database",
                            guidance="Migrations live in alembic/versions."))

    hits = store.search_lessons("pip install on windows")
    assert hits
    assert "python -m pip" in hits[0][0].guidance
    store.close()


def test_credit_updates_win_and_loss_counts(tmp_path):
    store = BrainStore(tmp_path / "brain.db")
    lesson = store.add_lesson(Lesson(guidance="something useful"))
    store.credit([lesson.id], won=True)
    store.credit([lesson.id], won=False)
    store.flush()                       # reinforcement is queued, not inline

    stored = store.all_lessons()[0]
    assert (stored.wins, stored.losses, stored.uses) == (1, 1, 2)
    store.close()


def test_consolidate_prunes_decayed_lessons_but_spares_new_ones(tmp_path):
    store = BrainStore(tmp_path / "brain.db")
    doomed = store.add_lesson(Lesson(guidance="a belief that never worked out"))
    fresh = store.add_lesson(Lesson(guidance="brand new observation"))

    # Age the first one and give it a losing record, directly in the database so
    # the test does not depend on how the dataclass defaults are ordered.
    long_ago = time.time() - 200 * 86400
    store.connection.execute(
        "UPDATE lessons SET updated_at=?, created_at=?, uses=6, losses=6, "
        "confidence=0.2 WHERE id=?", (long_ago, long_ago, doomed.id))
    store.connection.commit()

    removed = store.consolidate(min_confidence=0.15, half_life_days=45)
    remaining = {lesson.id for lesson in store.all_lessons()}

    assert removed == 1
    assert doomed.id not in remaining
    assert fresh.id in remaining, "a lesson with no track record yet gets a grace period"
    store.close()


@pytest.mark.parametrize("reply", [
    'sure!\n```json\n{"lessons": [], "skill": null}\n```',
    '{"lessons": [], "skill": null}',
    'Here is the result:\n{"lessons": [], "skill": null}\nHope that helps.',
])
def test_reflection_json_survives_however_the_model_wraps_it(reply):
    assert extract_json(reply) == {"lessons": [], "skill": None}


def test_reflection_returns_nothing_when_the_reply_is_not_json():
    assert extract_json("I did not learn anything useful this time.") == {}


def test_reflection_rejects_vague_lessons_and_one_step_skills():
    raw = json.dumps({
        "lessons": [
            {"kind": "heuristic", "trigger": "always", "guidance": "be good"},
            {"kind": "pitfall", "trigger": "editing config",
             "guidance": "Restart the process after editing config.toml."},
        ],
        "skill": {"name": "x", "description": "d", "steps": ["only one"]},
    })
    result = parse_reflection(raw, scope="global")

    assert len(result.lessons) == 1                 # "be good" is too vague
    assert result.skill is None                     # one step is not a procedure


def test_reflection_caps_the_number_of_lessons():
    raw = json.dumps({"lessons": [
        {"kind": "fact", "trigger": f"case {i}", "guidance": f"do the thing number {i}"}
        for i in range(9)
    ], "skill": None})
    assert len(parse_reflection(raw, scope="global").lessons) == 4


# --------------------------------------------------------------------------- #
# the engine
# --------------------------------------------------------------------------- #


def test_taught_lessons_are_pinned_and_always_recalled(config, bus):
    engine = LearningEngine(config, bus)
    engine.teach("writing commits: use imperative mood, no trailing period")

    recalled = engine.recall("something entirely unrelated to commits")
    assert any("imperative" in lesson.guidance for lesson in recalled)
    engine.close()


def test_playbook_respects_the_token_budget(config, bus):
    engine = LearningEngine(config, bus)
    for index in range(20):
        engine.store.add_lesson(Lesson(
            scope=engine.write_scope, trigger=f"situation {index}",
            guidance="a fairly long piece of guidance " * 12, confidence=0.8))
    lessons = engine.store.all_lessons()

    generous = engine.render_playbook(lessons, max_tokens=800)
    assert generous.count("\n- ") >= 1
    assert len(generous) // 4 <= 800

    tight = engine.render_playbook(lessons, max_tokens=300)
    assert len(tight) // 4 <= 300
    assert tight.count("\n- ") < generous.count("\n- ")

    # Below the cost of the header itself, nothing is emitted at all — a
    # truncated lesson could say the opposite of what it means.
    assert engine.render_playbook(lessons, max_tokens=20) == ""


def test_duplicate_lessons_merge_instead_of_accumulating(config, bus):
    engine = LearningEngine(config, bus)
    first = Lesson(scope=engine.write_scope, trigger="running the suite",
                   guidance="Use pytest -q rather than unittest.", confidence=0.5)
    engine.store.add_lesson(first)

    restated = Lesson(scope=engine.write_scope, trigger="running tests",
                      guidance="Prefer pytest -q over unittest when running tests.")
    stored, merged = engine._absorb([restated])

    assert stored == []
    assert merged == 1
    assert len(engine.store.all_lessons()) == 1
    assert engine.store.all_lessons()[0].confidence > 0.5
    engine.close()


def test_feedback_moves_confidence(config, bus):
    engine = LearningEngine(config, bus)
    lesson = engine.store.add_lesson(Lesson(scope=engine.write_scope,
                                            guidance="a claim about the code"))
    before = engine.store.all_lessons()[0].effective_confidence()
    engine.feedback([lesson], good=True)
    engine.store.flush()
    after = engine.store.all_lessons()[0].effective_confidence()

    assert after > before
    engine.close()


# --------------------------------------------------------------------------- #
# the proof: does it actually improve?
# --------------------------------------------------------------------------- #


REFLECTION = json.dumps({
    "lessons": [{
        "kind": "pitfall",
        "trigger": "running the test suite in this project",
        "guidance": "Run pytest from the repository root; running it from src/ "
                    "cannot import the package.",
        "confidence": 0.8,
    }],
    "skill": None,
})


def test_a_task_teaches_a_lesson_that_the_next_task_recalls(config, bus):
    """End to end: reflect after run one, recall before run two."""
    scripts = [
        Script(text="I ran the tests from the root and they passed."),
        Script(text=f"```json\n{REFLECTION}\n```"),      # the reflection pass
        Script(text="Running them again."),
    ]
    gateway = Gateway(config, scripts=scripts)
    memory = LearningEngine(config, bus, gateway)
    agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation(), memory)

    agent.run("run the test suite")
    memory.wait_for_reflection(timeout=10.0)

    lessons = memory.store.all_lessons()
    assert len(lessons) == 1, "reflection should have stored exactly one lesson"
    assert "repository root" in lessons[0].guidance

    # A fresh conversation, so nothing but the brain can carry the knowledge over.
    agent.conversation = Conversation()
    agent.run("run the test suite again")

    provider = gateway.provider("fake")
    system_prompts = [
        f"{message.content} {message.briefing}"
        for call in provider.calls
        for message in call
    ]
    assert any("repository root" in prompt for prompt in system_prompts), \
        "the learned lesson should appear in the next turn's playbook"

    # And the lesson should be credited for the successful second run.
    memory.store.flush()
    assert memory.store.all_lessons()[0].uses >= 1
    memory.close()


def test_a_failed_task_penalises_the_lessons_it_relied_on(config, bus):
    config.learning.reflect = False
    gateway = Gateway(config, scripts=[Script(error="provider down")])
    memory = LearningEngine(config, bus, gateway)
    memory.store.add_lesson(Lesson(
        scope=memory.write_scope, trigger="deploying the service",
        guidance="Deploy with the makefile target, not the raw docker command."))
    agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation(), memory)
    agent.run("deploy the service")
    memory.store.flush()

    stored = memory.store.all_lessons()[0]
    assert stored.losses == 1
    assert stored.wins == 0
    memory.close()
