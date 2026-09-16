"""The blocked single-optimization experiment (T096 harness).

Running each configuration as one long sequential batch confounds the switch
with the hour it ran. These prove the replacement: every `(task, try)` block
runs all seven configurations in a counterbalanced order, so a CURRENT-vs-
ablation pair differs by the switch and little else. No model is called — the
runner's one-attempt function is replaced with a scripted one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench import baseline, report, runner
from bench.task import Attempt, Task, Verdict


def _task(name: str, tmp_path: Path) -> Task:
    repo = tmp_path / name
    repo.mkdir(exist_ok=True)
    return Task(name=name, category="fix", prompt="p", repo=repo,
                check=lambda attempt: Verdict.ok())


@pytest.fixture
def cohort(tmp_path):
    return [_task(f"t{i:02d}", tmp_path) for i in range(16)]


def _fake_one(tokens_by_config, fail=()):
    """A stand-in for `runner._one` with per-config token figures."""
    calls: list[dict] = []

    def fake(task, provider, model, keep, strategy, learning, without):
        config = without[0] if without else "current"
        calls.append({"task": task.name, "config": config, "without": tuple(without)})
        base = tokens_by_config.get(config, tokens_by_config["current"])
        attempt = Attempt(workspace=Path("."), ok=config not in fail,
                          stopped="done", text="", steps=1,
                          input_tokens=base, output_tokens=base // 10,
                          cached_tokens=base // 2,
                          measurement={"clarifications_raised": 0, "corrections": 0})
        verdict = Verdict.no("scripted failure") if config in fail else Verdict.ok()
        return attempt, verdict, Path(".")

    return fake, calls


def test_the_experiment_has_seven_configurations():
    assert baseline.CONFIGURATIONS == (
        "current", "dedup", "delta", "budget", "ranking",
        "summary_provenance", "log_summary")
    assert baseline.switch_of("current") == ()
    assert baseline.switch_of("dedup") == ("dedup",)


def test_exactly_48_blocks_and_336_attempts(monkeypatch, tmp_path, cohort):
    fake, calls = _fake_one({"current": 100})
    monkeypatch.setattr(runner, "_one", fake)
    run = runner.run_blocked(cohort, provider="fake", model="m", tries=3,
                             say=lambda *a, **k: None)

    blocks = run.blocks()
    assert len(blocks) == 48
    assert all(len(grouped) == 7 for grouped in blocks.values())
    assert len(run.attempts) == 336 == run.planned_attempts
    assert len(calls) == 336


def test_each_block_runs_every_configuration_once(monkeypatch, tmp_path, cohort):
    fake, _ = _fake_one({"current": 100})
    monkeypatch.setattr(runner, "_one", fake)
    run = runner.run_blocked(cohort, provider="fake", model="m", tries=3,
                             say=lambda *a, **k: None)
    for grouped in run.blocks().values():
        assert set(grouped) == set(baseline.CONFIGURATIONS)


def test_the_order_rotates_and_is_deterministic():
    first = baseline.block_order(0)
    second = baseline.block_order(1)
    assert first == list(range(7))
    assert second == [6, 0, 1, 2, 3, 4, 5]
    assert baseline.block_order(1) == second, "the order is deterministic"


def test_every_configuration_sits_in_every_position_evenly(monkeypatch, tmp_path, cohort):
    fake, _ = _fake_one({"current": 100})
    monkeypatch.setattr(runner, "_one", fake)
    run = runner.run_blocked(cohort, provider="fake", model="m", tries=3,
                             say=lambda *a, **k: None)

    table = report.blocked_counterbalance(run)
    for config, positions in table.items():
        assert sum(positions) == 48, config
        assert max(positions) - min(positions) <= 1, (config, positions)
        assert all(count > 0 for count in positions), (config, positions)


def test_each_attempt_differs_only_by_the_switch(monkeypatch, tmp_path, cohort):
    fake, calls = _fake_one({"current": 100})
    monkeypatch.setattr(runner, "_one", fake)
    runner.run_blocked(cohort, provider="fake", model="m", tries=3,
                       say=lambda *a, **k: None)

    # Each task runs seven times per try, across three tries, once per switch.
    from collections import Counter

    by_task = {}
    for call in calls:
        by_task.setdefault(call["task"], []).append(call["config"])
    assert all(len(configs) == 21 for configs in by_task.values())
    for configs in by_task.values():
        assert Counter(configs) == Counter(dict.fromkeys(baseline.CONFIGURATIONS, 3))


def test_pairing_keys_are_stable_and_unique(monkeypatch, tmp_path, cohort):
    fake, _ = _fake_one({"current": 100})
    monkeypatch.setattr(runner, "_one", fake)
    run = runner.run_blocked(cohort, provider="fake", model="m", tries=3,
                             say=lambda *a, **k: None)
    keys = list(run.blocks().keys())
    assert len(keys) == len(set(keys)) == 48
    assert all(task in {c.name for c in cohort} for task, _ in keys)
    assert sorted(index for _, index in keys) == sorted([1, 2, 3] * 16)


def test_metrics_compare_block_locally(monkeypatch, tmp_path, cohort):
    """CURRENT-only and ablation-only successes are counted per block."""
    tokens = {"current": 1000, "dedup": 500}
    fail = {"dedup"}                      # every dedup attempt fails
    fake, _ = _fake_one(tokens, fail=fail)
    monkeypatch.setattr(runner, "_one", fake)
    run = runner.run_blocked(cohort, provider="fake", model="m", tries=3,
                             say=lambda *a, **k: None)

    metrics = report.blocked_metrics(run)["dedup"]
    assert metrics["paired_blocks"] == 48
    assert metrics["quality"] == {"current_only": 48, "ablation_only": 0,
                                  "both_success": 0, "both_failure": 0}
    total = metrics["tokens"]["total"]
    # total = input + cached + output: current 1000+500+100=1600,
    # dedup 500+250+50=800, so each pair is 800 lower.
    assert total["n"] == 48
    assert total["mean_delta"] == -800
    assert total["median_delta"] == -800
    assert total["median_ratio"] == pytest.approx(0.5)
    assert total["lower"] == 48 and total["higher"] == 0


def test_metrics_capture_a_mixed_contingency(monkeypatch, tmp_path, cohort):
    class Scripted:
        def __call__(self, task, provider, model, keep, strategy, learning, without):
            config = without[0] if without else "current"
            # Alternate: on even tasks the ablation wins, on odd CURRENT wins.
            index = int(task.name[-2:])
            current_ok = index % 2 == 0
            passed = current_ok if config == "current" else not current_ok
            attempt = Attempt(workspace=Path("."), ok=passed, stopped="done",
                              text="", steps=1, input_tokens=100, output_tokens=10,
                              cached_tokens=0)
            verdict = Verdict.ok() if passed else Verdict.no("x")
            return attempt, verdict, Path(".")

    monkeypatch.setattr(runner, "_one", Scripted())
    run = runner.run_blocked(cohort, provider="fake", model="m", tries=3,
                             say=lambda *a, **k: None)
    quality = report.blocked_metrics(run)["delta"]["quality"]
    assert quality["current_only"] + quality["ablation_only"] == 48
    assert quality["both_success"] == 0 and quality["both_failure"] == 0


def test_the_report_carries_order_and_pairing_identity(monkeypatch, tmp_path, cohort):
    fake, _ = _fake_one({"current": 100})
    monkeypatch.setattr(runner, "_one", fake)
    run = runner.run_blocked(cohort, provider="fake", model="m", tries=3,
                             say=lambda *a, **k: None)
    body = report.blocked_json(run)

    assert body["kind"] == "blocked-ablation"
    assert body["counts"] == {"blocks": 48, "attempts": 336,
                              "planned_attempts": 336, "attempts_passed": 336}
    assert body["configurations"] == list(baseline.CONFIGURATIONS)
    assert "counterbalanced" in body["scheme"]
    block = body["blocks"][0]
    assert block["task"] and block["attempt_index"] in (1, 2, 3)
    assert sorted(block["order"]) == sorted(baseline.CONFIGURATIONS)
    assert sorted(block["results"]) == sorted(baseline.CONFIGURATIONS)
    assert body["metrics"]["dedup"]["tokens"]["total"]["n"] == 48


def test_a_sequential_artifact_is_not_history_for_the_blocked_report(monkeypatch, tmp_path, cohort):
    """The blocked report is self-contained: it never reads a sequential file."""
    fake, _ = _fake_one({"current": 100})
    monkeypatch.setattr(runner, "_one", fake)
    run = runner.run_blocked(cohort, provider="fake", model="m", tries=3,
                             say=lambda *a, **k: None)
    body = report.blocked_json(run)
    assert body["kind"] == "blocked-ablation"
    assert "tasks" not in body, "a sequential report shape must not leak in"
    json.dumps(body)                       # serialisable, no live objects


def test_ordinary_runners_are_unchanged(cohort):
    """`--blocked` is additive: the ordinary and paired paths still exist."""
    assert callable(runner.run_task)
    assert callable(report.as_json)
    assert callable(report.as_paired_json)
    assert baseline.settings(baseline.CURRENT) == {
        "context_strategy": "current", "optimizations_off": []}


def test_blocked_refuses_a_sequence_task(tmp_path):
    from bench.task import SequenceStep

    repo = tmp_path / "seq"
    repo.mkdir()
    task = Task(name="seq", category="careful", prompt="p", repo=repo,
                check=lambda a: Verdict.ok(),
                sequence=(SequenceStep(prompt="add", expect={"path": "x", "marker": "K"}),),
                check_sequence=lambda result: Verdict.ok())
    with pytest.raises(ValueError):
        runner.run_blocked([task], provider="fake", model="m", tries=1,
                           say=lambda *a, **k: None)


# --------------------------------------------------------------------------- #
# checkpoint / resume (a 336-call run must survive an interruption)
# --------------------------------------------------------------------------- #


def test_completed_blocks_are_not_repeated(monkeypatch, tmp_path):
    cohort = [_task(f"r{i:02d}", tmp_path) for i in range(2)]
    fake, calls = _fake_one({"current": 100})
    monkeypatch.setattr(runner, "_one", fake)
    checkpoint = tmp_path / "run.checkpoint.jsonl"

    first = runner.run_blocked(cohort, provider="fake", model="m", tries=1,
                               say=lambda *a, **k: None, checkpoint=checkpoint)
    assert len(first.attempts) == 14
    assert len(calls) == 14

    calls.clear()
    second = runner.run_blocked(cohort, provider="fake", model="m", tries=1,
                                say=lambda *a, **k: None, checkpoint=checkpoint)
    assert calls == [], "a completed resume must make no new attempts"
    assert len(second.attempts) == 14


def test_resume_preserves_pairing_identity(monkeypatch, tmp_path):
    cohort = [_task(f"r{i:02d}", tmp_path) for i in range(2)]
    fake, _ = _fake_one({"current": 100})
    monkeypatch.setattr(runner, "_one", fake)
    checkpoint = tmp_path / "run.checkpoint.jsonl"
    first = runner.run_blocked(cohort, provider="fake", model="m", tries=1,
                               say=lambda *a, **k: None, checkpoint=checkpoint)
    second = runner.run_blocked(cohort, provider="fake", model="m", tries=1,
                                say=lambda *a, **k: None, checkpoint=checkpoint)

    def identity(entry):
        return (entry.block, entry.task, entry.attempt_index, entry.config,
                entry.position)

    assert [identity(e) for e in first.attempts] == [identity(e) for e in second.attempts]


def test_resume_preserves_execution_order(monkeypatch, tmp_path):
    cohort = [_task(f"r{i:02d}", tmp_path) for i in range(2)]
    fake, _ = _fake_one({"current": 100})
    monkeypatch.setattr(runner, "_one", fake)
    checkpoint = tmp_path / "run.checkpoint.jsonl"
    run = runner.run_blocked(cohort, provider="fake", model="m", tries=1,
                             say=lambda *a, **k: None, checkpoint=checkpoint)
    assert [e.block for e in run.attempts] == sorted(e.block for e in run.attempts)
    for (_task_name, _attempt_index), grouped in run.blocks().items():
        block = grouped["current"].block
        for config, entry in grouped.items():
            expected = (baseline.CONFIGURATIONS.index(config) + block) % 7
            assert entry.position == expected, (config, block)
        positions = sorted(entry.position for entry in grouped.values())
        assert positions == list(range(7))


def test_a_resumed_run_matches_an_uninterrupted_one(monkeypatch, tmp_path):
    cohort = [_task(f"r{i:02d}", tmp_path) for i in range(3)]
    fake, _ = _fake_one({"current": 100, "dedup": 500})
    monkeypatch.setattr(runner, "_one", fake)

    uninterrupted = runner.run_blocked(cohort, provider="fake", model="m",
                                       tries=1, say=lambda *a, **k: None)

    state = {"calls": 0}
    limit = {"n": 9}

    def interrupting(task, provider, model, keep, strategy, learning, without):
        state["calls"] += 1
        if state["calls"] > limit["n"]:
            raise RuntimeError("interrupted")
        return fake(task, provider, model, keep, strategy, learning, without)

    monkeypatch.setattr(runner, "_one", interrupting)
    checkpoint = tmp_path / "run.checkpoint.jsonl"
    with pytest.raises(RuntimeError):
        runner.run_blocked(cohort, provider="fake", model="m", tries=1,
                           say=lambda *a, **k: None, checkpoint=checkpoint)

    monkeypatch.setattr(runner, "_one", fake)
    resumed = runner.run_blocked(cohort, provider="fake", model="m", tries=1,
                                 say=lambda *a, **k: None, checkpoint=checkpoint)

    assert len(resumed.attempts) == len(uninterrupted.attempts) == 21
    assert (report.blocked_json(resumed)["metrics"]
            == report.blocked_json(uninterrupted)["metrics"])
    assert (report.blocked_json(resumed)["blocks"]
            == report.blocked_json(uninterrupted)["blocks"])


def test_a_changed_configuration_refuses_resume(monkeypatch, tmp_path):
    cohort = [_task(f"r{i:02d}", tmp_path) for i in range(2)]
    fake, _ = _fake_one({"current": 100})
    monkeypatch.setattr(runner, "_one", fake)
    checkpoint = tmp_path / "run.checkpoint.jsonl"
    runner.run_blocked(cohort, provider="fake", model="m", tries=1,
                       say=lambda *a, **k: None, checkpoint=checkpoint)

    with pytest.raises(ValueError):
        runner.run_blocked(cohort, provider="fake", model="other", tries=1,
                           say=lambda *a, **k: None, checkpoint=checkpoint)


def test_a_changed_fingerprint_refuses_resume(monkeypatch, tmp_path):
    cohort = [_task(f"r{i:02d}", tmp_path) for i in range(2)]
    fake, _ = _fake_one({"current": 100})
    monkeypatch.setattr(runner, "_one", fake)
    checkpoint = tmp_path / "run.checkpoint.jsonl"
    runner.run_blocked(cohort, provider="fake", model="m", tries=1,
                       say=lambda *a, **k: None, checkpoint=checkpoint)

    header = json.loads(checkpoint.read_text(encoding="utf-8").splitlines()[0])
    header["fingerprints"] = dict.fromkeys(header["fingerprints"], "changed")
    lines = checkpoint.read_text(encoding="utf-8").splitlines()[1:]
    checkpoint.write_text(json.dumps(header) + "\n" + "\n".join(lines) + "\n",
                          encoding="utf-8")

    with pytest.raises(ValueError):
        runner.run_blocked(cohort, provider="fake", model="m", tries=1,
                           say=lambda *a, **k: None, checkpoint=checkpoint)


def test_a_torn_last_line_is_dropped(monkeypatch, tmp_path):
    cohort = [_task(f"r{i:02d}", tmp_path) for i in range(2)]
    fake, calls = _fake_one({"current": 100})
    monkeypatch.setattr(runner, "_one", fake)
    checkpoint = tmp_path / "run.checkpoint.jsonl"
    runner.run_blocked(cohort, provider="fake", model="m", tries=1,
                       say=lambda *a, **k: None, checkpoint=checkpoint)

    whole = checkpoint.read_text(encoding="utf-8").splitlines()
    checkpoint.write_text("\n".join(whole[:-1]) + "\n" + '{"kind": "att',
                          encoding="utf-8")

    calls.clear()
    resumed = runner.run_blocked(cohort, provider="fake", model="m", tries=1,
                                 say=lambda *a, **k: None, checkpoint=checkpoint)
    assert len(calls) == 1, "only the torn line's attempt is repeated"
    assert len(resumed.attempts) == 14
