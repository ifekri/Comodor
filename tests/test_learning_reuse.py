"""Repeated work costs less the second time (T118; FR-067, SC-021).

The fixed N = 6 sequence of comparable tasks in one project: tasks 1–3 are
the initial window, tasks 4–6 the learned window. Two primary metrics are
counted with the same definitions T152 uses — mandatory clarifications raised
and user corrections received — and the learned window must be strictly lower
on both with no task's outcome success regressing.

The measurement is deterministic: a fixed question and a fixed correction
drive the same real learning mechanism the product uses, with no model call
and no timing. The window inputs are asserted comparable, so an incomparable
run is invalid rather than passing. A lower count obtained by skipping a
required question or by not delivering the promised style would fail the
per-task correctness assertion.
"""

from __future__ import annotations

import pytest

from comodor.agent.evidence import Ledger
from comodor.learning import LearningEngine
from comodor.safety import CheckpointStore

N = 6
INITIAL = 3
DB_QUESTION = "Which database should the project use, SQLite or PostgreSQL?"
DB_AFFECTS = ("persistence",)
DB_ANSWER = "SQLite"

#: The fixed sequence. Each task has the same shape — one request, one file,
#: one decision — differing only by index. Comparability is asserted below.
SEQUENCE = [{"request": f"update app{i}", "file": f"app{i}.py", "decision": DB_QUESTION}
            for i in range(N)]


def comparable(tasks: list[dict]) -> bool:
    """Whether the window inputs are the same shape, so the comparison is valid."""
    shapes = {(task["decision"], task["file"].split(".")[-1]) for task in tasks}
    return len(shapes) == 1 and len(tasks) == N


@pytest.fixture
def engine(config, bus, workspace):
    config.learning.reflect = False
    return LearningEngine(config, bus, gateway=None,
                          checkpoints=CheckpointStore(config.paths.checkpoints))


def _raised(engine, request: str):
    """What the ask tool's decision would be, given the learned decisions."""
    book = Ledger()
    book.known("the request, as the user stated it", material=request)
    for decision in engine.settled_decisions():
        book.knowledge(decision.trigger, f"lesson:{decision.id}", answer=decision.guidance)
    return book.open_decision(DB_QUESTION, affects=DB_AFFECTS,
                              candidates=["SQLite", "PostgreSQL"])


def _single(index):
    return "\n".join(f"v{n} = 't{n}'" for n in range(8)) + "\n"


def _double(index):
    return "\n".join(f'v{n} = "t{n}"' for n in range(8)) + "\n"


def _run_task(engine, index: int) -> dict:
    """One task: a clarification, a write, a possible correction. Returns metrics."""
    decision = _raised(engine, SEQUENCE[index]["request"])
    raised = 0 if decision.state == "answered" else 1
    if raised:
        assert decision.material, "a count only counts a *mandatory* clarification"
        engine.settle_decision(DB_QUESTION, DB_ANSWER)

    compliant = any(rule.key == "quotes.style" and rule.applies
                    for rule in engine.active_rules())
    target = engine.config.paths.project / SEQUENCE[index]["file"]
    written = _single(index) if compliant else _double(index)
    engine.detector.checkpoints.snapshot(target, action="create", tool="write_file",
                                         after=written)
    target.write_text(written, encoding="utf-8")
    if not compliant:
        target.write_text(_single(index), encoding="utf-8")

    outcome = engine.before_turn(SEQUENCE[index]["request"])
    corrections = len(outcome.corrections)
    delivered_single = "'t7'" in target.read_text(encoding="utf-8")
    return {"raised": raised, "corrections": corrections,
            "ok": delivered_single, "compliant": compliant}


def _measure(engine):
    assert comparable(SEQUENCE), "incomparable window inputs invalidate the run"
    windows = {"initial": {"raised": 0, "corrections": 0, "ok": 0},
               "learned": {"raised": 0, "corrections": 0, "ok": 0}}
    for index in range(N):
        window = "initial" if index < INITIAL else "learned"
        metrics = _run_task(engine, index)
        for key in ("raised", "corrections", "ok"):
            windows[window][key] += metrics[key]
    return windows


def test_the_learned_window_raises_fewer_clarifications(engine):
    windows = _measure(engine)
    assert windows["learned"]["raised"] < windows["initial"]["raised"]
    assert windows["learned"]["raised"] == 0


def test_the_learned_window_receives_fewer_corrections(engine):
    windows = _measure(engine)
    assert windows["learned"]["corrections"] < windows["initial"]["corrections"]


def test_no_tasks_outcome_success_regresses(engine):
    windows = _measure(engine)
    assert windows["initial"]["ok"] == INITIAL
    assert windows["learned"]["ok"] == N - INITIAL


def test_the_first_correction_is_learned_and_applied_afterwards(engine):
    windows = _measure(engine)
    assert windows["initial"]["corrections"] == 1, "learned on the first correction"
    assert windows["learned"]["corrections"] == 0, "applied without restatement"


def test_an_incomparable_window_is_invalid_not_passing():
    broken = list(SEQUENCE)
    broken[3] = {**broken[3], "decision": "Which cache should we use?"}
    assert not comparable(broken)


def test_mutation_without_the_learned_decision_it_is_asked_again(engine):
    """The seeding is what stops the repeat: without it the question re-raises."""
    engine.settle_decision(DB_QUESTION, DB_ANSWER)
    empty = Ledger()
    empty.known("the request", material="update app0")
    assert empty.open_decision(DB_QUESTION, affects=DB_AFFECTS).state != "answered"
