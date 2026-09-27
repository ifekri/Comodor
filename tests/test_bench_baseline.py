"""The naive comparison strategy and the paired report (T014, T015; SC-011, SC-036).

The naive strategy is the product with its context work switched off, chosen
by a setting the runtime already reads. These prove that the setting is what
the runner writes, that the runtime honours it — every sweep stays off — and
that the paired report carries both halves of every number.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench import baseline, report
from bench.report import sc012_comparison, scenario_fingerprints
from bench.runner import Outcome, _settings
from bench.task import Attempt, Task, Verdict
from comodor.agent import AgentLoop, Conversation
from comodor.providers.base import Message, ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry


def a_task(name="fix-it", category="fix", writes=True):
    return Task(name=name, category=category, prompt="fix it",
                repo=Path("/nowhere"), check=lambda attempt: Verdict.ok(),
                max_steps=10, timeout=60.0, writes=writes)


def test_the_naive_settings_switch_every_sweep_off():
    naive = baseline.settings(baseline.NAIVE)
    assert naive["context_strategy"] == "naive"
    assert naive["max_tool_chars"] >= 1_000_000
    assert naive["keep_screenshots"] >= 1_000
    assert naive["compact_at"] >= 0.9
    assert baseline.settings(baseline.CURRENT) == {"context_strategy": "current",
                                                   "optimizations_off": []}
    assert baseline.settings(baseline.CURRENT, ["dedup"])["optimizations_off"] == ["dedup"]
    with pytest.raises(ValueError):
        baseline.settings("clever")


def test_the_runner_writes_the_strategy_into_the_attempts_own_config(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    _settings(home, a_task(), strategy=baseline.NAIVE)
    written = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert written["agent"]["context_strategy"] == "naive"
    assert written["agent"]["max_tool_chars"] >= 1_000_000
    # The budgets are the task's, whatever the strategy.
    assert written["agent"]["max_steps"] == 10
    assert written["learning"]["enabled"] is False

    _settings(home, a_task(), strategy=baseline.CURRENT)
    written = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert written["agent"]["context_strategy"] == "current"
    assert "max_tool_chars" not in written["agent"]


def test_the_runtime_reads_the_strategy_from_config_not_from_the_harness(config):
    """`bench/` is never imported by the product; the setting is the contract."""
    import re

    source = Path(__file__).resolve().parents[1] / "src" / "comodor"
    importing = re.compile(r"^\s*(from\s+bench(?:\s|\.)|import\s+bench(?:\s|\.|$))", re.M)
    for path in source.rglob("*.py"):
        assert not importing.search(path.read_text(encoding="utf-8", errors="replace")), path
    assert config.agent.context_strategy == "current"


def _big(marker):
    return "\n".join(f"{n:6d}\t{marker} = {n}" for n in range(1, 900))


def _agent(config, bus, scripts):
    gateway = Gateway(config, scripts=scripts)
    return AgentLoop(config, gateway, ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation())


def _seed_a_superseded_read(agent):
    """A read, an edit to the same file, a newer read — the sweep's trigger."""
    conversation = agent.conversation
    read = Message.tool(call_id="r1", name="read_file", content=_big("x"))
    read.meta["path"] = "a.py"
    edit_call = ToolCall(id="e1", name="edit_file",
                         arguments={"path": "a.py", "old_string": "a", "new_string": "b"})
    edit = Message.tool(call_id="e1", name="edit_file", content="Edited a.py.")
    edit.meta["path"] = "a.py"
    newer = Message.tool(call_id="r2", name="read_file", content=_big("y"))
    newer.meta["path"] = "a.py"
    conversation.add(Message.user("start"))
    conversation.add(Message.assistant("Reading.", [ToolCall(id="r1", name="read_file",
                                                             arguments={"path": "a.py"})]))
    conversation.add(read)
    conversation.add(Message.assistant("Editing.", [edit_call]))
    conversation.add(edit)
    conversation.add(Message.assistant("Reading again.", [ToolCall(id="r2", name="read_file",
                                                                   arguments={"path": "a.py"})]))
    conversation.add(newer)
    return read


def test_under_the_naive_strategy_a_superseded_read_is_never_swept(config, bus):
    config.agent.context_strategy = "naive"
    config.agent.compact_at = 0.0          # under pressure at once
    agent = _agent(config, bus, [Script(text="ok")])
    agent._window = lambda: 10_000_000
    stale = _seed_a_superseded_read(agent)
    original = stale.content

    agent._maybe_compact("HEAD", [])

    assert stale.content == original
    assert "superseded" not in stale.meta


def test_under_the_current_strategy_the_same_read_is_swept(config, bus):
    config.agent.compact_at = 0.0
    agent = _agent(config, bus, [Script(text="ok")])
    agent._window = lambda: 10_000_000
    stale = _seed_a_superseded_read(agent)

    agent._maybe_compact("HEAD", [])

    assert stale.meta.get("superseded") is True


def test_under_the_naive_strategy_screenshots_are_kept(config, bus):
    config.agent.context_strategy = "naive"
    config.agent.keep_screenshots = 1
    agent = _agent(config, bus, [Script(text="ok")])
    agent._window = lambda: 10_000_000
    for index in range(4):
        agent.conversation.add(Message.user(f"look {index}", images=["aGVsbG8="]))

    agent._maybe_compact("HEAD", [])

    assert all(message.images for message in agent.conversation.messages)


# --------------------------------------------------------------------------- #
# the paired report
# --------------------------------------------------------------------------- #


def _outcome(task, strategy, passed, tokens):
    outcome = Outcome(task=task, strategy=strategy)
    for index in range(3):
        outcome.attempts.append(Attempt(
            workspace=Path("/nowhere"), ok=index < passed, stopped="done", text="",
            steps=4, tool_calls=6, input_tokens=tokens, output_tokens=tokens // 10,
            cached_tokens=tokens // 2))
        outcome.verdicts.append(Verdict.ok() if index < passed else Verdict.no("wrong"))
    return outcome


def test_the_paired_report_carries_rate_and_tokens_for_both_strategies():
    task = a_task()
    document = report.as_paired_json(
        [_outcome(task, "current", 3, 10_000)], [_outcome(task, "naive", 2, 40_000)],
        provider="fake", model="fake-1", tries=3)

    assert document["kind"] == "paired-baseline"
    row = document["tasks"][0]
    assert row["current"]["passed"] == 3 and row["naive"]["passed"] == 2
    for half in ("current", "naive"):
        for key in ("mean_input_tokens", "mean_output_tokens", "mean_cached_tokens",
                    "mean_total_tokens", "mean_steps", "mean_tool_calls", "tries"):
            assert key in row[half], key
    assert row["current"]["mean_total_tokens"] == 10_000 + 1_000 + 5_000
    assert document["totals"]["naive"]["outcome_rate"] == pytest.approx(2 / 3, abs=1e-3)


def test_the_paired_markdown_puts_every_token_figure_beside_its_rate():
    task = a_task()
    document = report.as_paired_json(
        [_outcome(task, "current", 3, 10_000)], [_outcome(task, "naive", 2, 40_000)],
        provider="fake", model="fake-1", tries=3)
    text = report.as_paired_markdown(document)
    assert "| fix-it | fix | 3/3 | 2/3 | 16,000 | 64,000 |" in text
    assert "SC-011" in text


def test_a_task_the_naive_strategy_never_ran_is_reported_as_absent_not_zero():
    task = a_task()
    document = report.as_paired_json([_outcome(task, "current", 3, 10_000)], [],
                                     provider="fake", model="fake-1", tries=3)
    assert document["tasks"][0]["naive"] is None
    assert "| — |" in report.as_paired_markdown(document)


def test_the_paired_files_are_named_as_a_baseline(tmp_path):
    task = a_task()
    json_file, md_file = report.write_paired(
        [_outcome(task, "current", 3, 10)], [_outcome(task, "naive", 3, 20)],
        tmp_path, provider="fake", model="fake-1", tries=3)
    assert json_file.name.startswith("baseline-fake-1-")
    assert md_file.suffix == ".md"
    assert json.loads(json_file.read_text(encoding="utf-8"))["kind"] == "paired-baseline"


def test_an_all_invalid_outcome_does_not_drag_the_paired_mean_down():
    """A task whose every run the harness could not measure has no token
    figure; averaging it in as zero halves the strategy mean (review
    4045800942)."""
    task = a_task()
    broken = Outcome(task=a_task(name="broken"), strategy="current")
    broken.invalid.append("invalid run — the judge raised OSError: gone")

    document = report.as_paired_json(
        [_outcome(task, "current", 3, 10_000), broken],
        [_outcome(task, "naive", 3, 40_000)],
        provider="fake", model="fake-1", tries=3)

    totals = document["totals"]["current"]
    assert totals["attempts"] == 3
    assert totals["mean_input_tokens"] == 10_000, "one measured task, not two"
    assert totals["mean_total_tokens"] == 10_000 + 1_000 + 5_000
    assert document["tasks"][1]["current"]["invalid_runs"] == 1


def test_a_strategy_with_nothing_measured_reports_zero_not_an_error():
    broken = Outcome(task=a_task(name="broken"), strategy="current")
    broken.invalid.append("invalid run — hook failed")
    document = report.as_paired_json([broken], [], provider="fake", model="fake-1", tries=3)
    assert document["totals"]["current"]["mean_total_tokens"] == 0
    assert document["totals"]["current"]["attempts"] == 0


def test_the_paired_markdown_flags_an_outcome_rate_fall_as_a_regression():
    """FR-077: a change that reduces tokens while reducing any task's outcome
    rate must be reportable as a regression, and the comparison says so."""
    task = a_task()
    document = report.as_paired_json(
        [_outcome(task, "current", 2, 10_000)], [_outcome(task, "naive", 3, 40_000)],
        provider="fake", model="fake-1", tries=3)

    text = report.as_paired_markdown(document)

    assert "Regression" in text
    assert "**yes**" in text


def test_the_paired_markdown_leaves_a_non_regression_blank():
    task = a_task()
    document = report.as_paired_json(
        [_outcome(task, "current", 3, 10_000)], [_outcome(task, "naive", 2, 40_000)],
        provider="fake", model="fake-1", tries=3)

    text = report.as_paired_markdown(document)

    assert "**yes**" not in text


def test_the_paired_run_interleaves_and_counterbalances(monkeypatch):
    """Both strategies run close together in a block, and which goes first
    alternates, so the strategy is not confounded with the hour it ran."""
    from bench import runner

    order = []

    def fake(task, provider, model, keep, strategy, learning, without):
        order.append((task.name, strategy))
        attempt = Attempt(workspace=Path("."), ok=True, stopped="done", text="",
                          steps=1, input_tokens=10, output_tokens=1, cached_tokens=0)
        return attempt, Verdict.ok(), Path(".")

    monkeypatch.setattr(runner, "_one", fake)
    tasks = [a_task(name="t1"), a_task(name="t2")]
    current, naive = runner.run_paired(tasks, provider="fake", model="m", tries=2,
                                       say=lambda *a, **k: None)

    assert order[0] == ("t1", "current") and order[1] == ("t1", "naive")
    assert order[2] == ("t1", "naive") and order[3] == ("t1", "current")
    assert order[4] == ("t2", "current") and order[5] == ("t2", "naive")
    assert len(current) == 2 and len(naive) == 2
    assert current[0].task.name == "t1" and naive[0].strategy == "naive"


# --------------------------------------------------------------------------- #
# recorded scenario provenance in the paired baseline (T209; D12)
# --------------------------------------------------------------------------- #

REAL = ("fix-off-by-one", "careful-unknowable")


def _fake_one(task, provider, model, keep, strategy, learning, without):
    attempt = Attempt(workspace=Path("."), ok=True, stopped="done", text="",
                      steps=1, input_tokens=10, output_tokens=1, cached_tokens=0)
    return attempt, Verdict.ok(), Path(".")


@pytest.fixture
def counted(monkeypatch):
    """`integrity.fingerprint_all`, counting its calls."""
    from bench import integrity, runner

    calls = []
    real = integrity.fingerprint_all

    def spy(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(integrity, "fingerprint_all", spy)
    monkeypatch.setattr(runner, "_one", _fake_one)
    return calls


def _paired(checkpoint=None):
    from bench import runner

    tasks = [a_task(name=name) for name in REAL]
    current, naive = runner.run_paired(tasks, provider="fake", model="m", tries=1,
                                       say=lambda *a, **k: None, checkpoint=checkpoint)
    return current, naive, report.as_paired_json(current, naive, provider="fake",
                                                  model="m", tries=1)


def test_a_paired_report_records_each_tasks_scenario_fingerprint(counted):
    from bench import integrity

    _, _, document = _paired()
    for row in document["tasks"]:
        assert row["scenario_fingerprint"] == integrity.fingerprint(
            integrity.TASKS / row["name"]), row["name"]


def test_the_scenarios_are_fingerprinted_once_per_run_and_never_at_write_time(counted, tmp_path):
    checkpoint = tmp_path / "paired.checkpoint.jsonl"
    _paired(checkpoint)
    assert len(counted) == 1, "fresh run: one fingerprint computation, run start only"

    counted.clear()
    _paired(checkpoint)
    assert len(counted) == 1, "resumed run: one fingerprint computation, run start only"


def test_the_recorded_fingerprints_are_the_checkpoint_headers(counted, tmp_path):
    checkpoint = tmp_path / "paired.checkpoint.jsonl"
    _, _, document = _paired(checkpoint)
    header = json.loads(checkpoint.read_text(encoding="utf-8").splitlines()[0])
    assert {row["name"]: row["scenario_fingerprint"] for row in document["tasks"]} \
        == header["fingerprints"]


def test_both_arms_of_a_task_carry_the_one_run_start_fingerprint(counted):
    current, naive, _ = _paired()
    for one, other in zip(current, naive, strict=True):
        assert one.scenario_fingerprint is not None
        assert one.scenario_fingerprint == other.scenario_fingerprint


def test_arms_judged_by_different_scenarios_are_refused():
    task = a_task()
    one, other = _outcome(task, "current", 3, 10), _outcome(task, "naive", 3, 10)
    one.scenario_fingerprint = {"task.md": "a"}
    other.scenario_fingerprint = {"task.md": "b"}
    with pytest.raises(ValueError, match="not a pair"):
        report.as_paired_json([one], [other], provider="fake", model="m", tries=3)
    other.scenario_fingerprint = None
    with pytest.raises(ValueError, match="not a pair"):
        report.as_paired_json([one], [other], provider="fake", model="m", tries=3)


def test_outcomes_without_a_fingerprint_publish_no_key():
    task = a_task()
    document = report.as_paired_json(
        [_outcome(task, "current", 3, 10_000)], [_outcome(task, "naive", 2, 40_000)],
        provider="fake", model="fake-1", tries=3)
    assert "scenario_fingerprint" not in document["tasks"][0]


def test_the_other_reports_are_unchanged_by_a_recorded_fingerprint(monkeypatch):
    """Markdown, single-strategy and blocked-ablation documents gain nothing."""
    from bench import runner

    monkeypatch.setattr(report, "_commit", lambda: "abc1234")
    task = a_task()
    plain = [_outcome(task, "current", 3, 10_000)], [_outcome(task, "naive", 2, 40_000)]
    marked = [_outcome(task, "current", 3, 10_000)], [_outcome(task, "naive", 2, 40_000)]
    for one in (*marked[0], *marked[1]):
        one.scenario_fingerprint = {"task.md": "a"}

    def documents(current, naive):
        paired = report.as_paired_json(current, naive, provider="f", model="m", tries=3)
        single = report.as_json(current, provider="f", model="m", tries=3)
        run = runner.BlockedRun(provider="f", model="m", tries=1, cohort=[task.name])
        return (report.as_paired_markdown(paired), single, report.as_markdown(single),
                report.blocked_json(run))

    with_fp, without_fp = documents(*marked), documents(*plain)
    assert with_fp == without_fp
    assert "scenario_fingerprint" not in json.dumps(with_fp)


# --------------------------------------------------------------------------- #
# SC-012: the per-task reference rule and reading provenance (T210–T212)
# --------------------------------------------------------------------------- #

HISTORICAL = Path(__file__).resolve().parents[1] / "bench" / "results" \
    / "paired-baseline-2026-09-20.json"


def fp(**changes):
    """A scenario fingerprint, the shape `bench.integrity.fingerprint` returns."""
    record = {"task.md": "prompt-1", "check.py": "judge-1", "repo": {"a.py": "a-1"},
              "hidden": {}, "budgets": {"CATEGORY": "fix", "MAX_STEPS": "25"}}
    record.update(changes)
    return record


def arm(passed, tries=3):
    return {"passed": passed, "tries": tries}


def row(name, current=arm(3), naive=arm(3), fingerprint=None, *, recorded=True):
    entry = {"name": name, "category": "fix", "current": current, "naive": naive}
    if recorded:
        entry["scenario_fingerprint"] = fingerprint if fingerprint is not None else fp()
    return entry


def paired(*rows, commit="abc1234", kind="paired-baseline"):
    return {"kind": kind, "commit": commit, "tasks": list(rows)}


def compare(candidate, baseline):
    return sc012_comparison(candidate, baseline, candidate_file="candidate.json",
                            baseline_file="baseline.json")


def only(result):
    (task,) = result["tasks"]
    return task


# -- reference selection ----------------------------------------------------- #


def test_an_unchanged_scenario_is_compared_with_the_published_rate():
    result = compare(paired(row("t", current=arm(3), naive=arm(0))),
                     paired(row("t", current=arm(3), naive=arm(3))))
    task = only(result)
    assert task["scenario_status"] == "UNCHANGED"
    assert task["reference_kind"] == "PUBLISHED_BASELINE"
    assert task["reference_rate"] == {"passed": 3, "tries": 3}
    assert result["result"] == "PASS"


@pytest.mark.parametrize("part", [
    {"check.py": "judge-2"},                          # the judge
    {"task.md": "prompt-2"},                          # the prompt
    {"repo": {"a.py": "a-2"}},                        # the starting repository
    {"hidden": {"test_hidden.py": "h-1"}},            # the hidden files
    {"budgets": {"CATEGORY": "fix", "MAX_STEPS": "60"}},  # a declared budget
], ids=["judge", "prompt", "repo", "hidden", "budget"])
def test_a_changed_scenario_is_compared_with_the_same_runs_naive_rate(part):
    candidate = paired(row("t", current=arm(2), naive=arm(2), fingerprint=fp(**part)))
    baseline = paired(row("t", current=arm(3), naive=arm(3)))
    task = only(compare(candidate, baseline))
    assert task["scenario_status"] == "CHANGED"
    assert task["reference_kind"] == "SAME_RUN_NAIVE"
    assert task["reference_rate"] == {"passed": 2, "tries": 3}
    assert task["result"] == "PASS", "2/3 against its own naive 2/3, not the old 3/3"
    assert task["reference_fingerprint"] == task["candidate_fingerprint"]


def test_a_harness_only_change_leaves_the_scenario_unchanged():
    """Equal fingerprints under different commits: the harness moved, the
    scenario did not."""
    task = only(compare(paired(row("t"), commit="1111111"),
                        paired(row("t"), commit="2222222")))
    assert task["scenario_status"] == "UNCHANGED"
    assert task["reference_kind"] == "PUBLISHED_BASELINE"


def test_the_task_name_never_decides_comparability():
    changed = only(compare(paired(row("careful-unknowable", fingerprint=fp(**{"check.py": "x"}))),
                           paired(row("careful-unknowable"))))
    assert changed["scenario_status"] == "CHANGED"
    unchanged = only(compare(paired(row("careful-unknowable")),
                             paired(row("careful-unknowable"))))
    assert unchanged["scenario_status"] == "UNCHANGED"
    assert unchanged["reference_kind"] == "PUBLISHED_BASELINE"


# -- task-set completeness --------------------------------------------------- #


def test_a_task_new_to_the_candidate_is_changed_and_uses_its_own_naive_rate():
    result = compare(paired(row("old"), row("new", current=arm(1), naive=arm(2))),
                     paired(row("old")))
    new = next(task for task in result["tasks"] if task["task"] == "new")
    assert new["scenario_status"] == "CHANGED"
    assert new["reference_kind"] == "SAME_RUN_NAIVE"
    assert new["result"] == "FAIL"
    assert result["result"] == "FAIL"


def test_a_baseline_task_missing_from_the_candidate_is_undecidable():
    result = compare(paired(row("kept")), paired(row("kept"), row("gone")))
    assert result["result"] == "UNDECIDABLE"
    assert result["baseline_only_tasks"] == ["gone"]
    assert [task["task"] for task in result["tasks"]] == ["kept"]


def test_a_missing_candidate_current_arm_is_undecidable():
    for current in (None, arm(0, 0)):
        result = compare(paired(row("t", current=current)), paired(row("t")))
        assert only(result)["result"] == "UNDECIDABLE"
        assert result["result"] == "UNDECIDABLE"


def test_a_missing_naive_arm_for_a_changed_task_is_undecidable():
    for naive in (None, arm(0, 0)):
        result = compare(paired(row("t", naive=naive, fingerprint=fp(**{"task.md": "x"}))),
                         paired(row("t")))
        task = only(result)
        assert task["reference_kind"] == "SAME_RUN_NAIVE"
        assert task["result"] == "UNDECIDABLE", naive
        assert result["result"] == "UNDECIDABLE"


def test_a_missing_published_arm_for_an_unchanged_task_is_undecidable():
    for published in (None, arm(0, 0)):
        result = compare(paired(row("t")), paired(row("t", current=published)))
        task = only(result)
        assert task["reference_kind"] == "PUBLISHED_BASELINE"
        assert task["result"] == "UNDECIDABLE", published
        assert result["result"] == "UNDECIDABLE"


def test_every_task_stays_in_the_denominator():
    """A task that cannot be decided is reported, never dropped: the verdict
    cannot improve by losing a row."""
    result = compare(paired(row("a"), row("b", naive=None, fingerprint=fp(**{"task.md": "x"}))),
                     paired(row("a"), row("b")))
    assert [task["task"] for task in result["tasks"]] == ["a", "b"]
    assert result["result"] == "UNDECIDABLE"


def test_a_document_that_is_not_a_paired_baseline_is_undecidable():
    for candidate, published in ((paired(row("t"), kind="blocked-ablation"), paired(row("t"))),
                                 (paired(row("t")), {"model": "m", "tasks": []})):
        assert compare(candidate, published)["result"] == "UNDECIDABLE"


def test_undecidable_outranks_a_failing_task():
    result = compare(paired(row("a", current=arm(0)), row("b", current=None)),
                     paired(row("a"), row("b")))
    assert [task["result"] for task in result["tasks"]] == ["FAIL", "UNDECIDABLE"]
    assert result["result"] == "UNDECIDABLE"


# -- rate comparison --------------------------------------------------------- #


def test_an_equal_rate_passes_and_a_lower_rate_fails():
    assert only(compare(paired(row("t", current=arm(2))),
                        paired(row("t", current=arm(2)))))["result"] == "PASS"
    assert only(compare(paired(row("t", current=arm(4, 6))),
                        paired(row("t", current=arm(2)))))["result"] == "PASS"
    assert only(compare(paired(row("t", current=arm(1))),
                        paired(row("t", current=arm(2)))))["result"] == "FAIL"


def test_rates_are_compared_as_exact_fractions():
    # 2/3 < 6667/10000 exactly; to four decimals (or as a rounded
    # correctness figure) they look equal and would pass.
    boundary = only(compare(paired(row("t", current=arm(2, 3))),
                            paired(row("t", current=arm(6667, 10000)))))
    assert boundary["result"] == "FAIL"
    # 1/3 < 333333333333333334/10**18 exactly, yet both are the same double.
    assert 1 / 3 == 333333333333333334 / 10**18
    tiny = only(compare(paired(row("t", current=arm(1, 3))),
                        paired(row("t", current=arm(333333333333333334, 10**18)))))
    assert tiny["result"] == "FAIL"


def test_the_result_passes_only_when_every_task_passes():
    passing = compare(paired(row("a"), row("b")), paired(row("a"), row("b")))
    assert passing["result"] == "PASS"
    one_fall = compare(paired(row("a"), row("b", current=arm(2))), paired(row("a"), row("b")))
    assert one_fall["result"] == "FAIL"
    assert [task["result"] for task in one_fall["tasks"]] == ["PASS", "FAIL"]


# -- evidence ---------------------------------------------------------------- #


def test_every_evidence_field_is_present():
    from bench import integrity

    result = compare(paired(row("same"), row("moved", fingerprint=fp(**{"task.md": "x"}))),
                     paired(row("same"), row("moved"), commit="be9cf6f"))
    assert result["kind"] == "sc012-comparison"
    assert result["candidate"] == {"file": "candidate.json", "commit": "abc1234",
                                   "fingerprint_source": "recorded"}
    assert result["baseline"] == {"file": "baseline.json", "commit": "be9cf6f",
                                  "fingerprint_source": "recorded"}
    assert result["baseline_only_tasks"] == [] and result["undecidable_reasons"] == []
    same, moved = result["tasks"]
    for task in (same, moved):
        assert set(task) == {"task", "candidate_fingerprint", "reference_fingerprint",
                             "scenario_status", "reference_kind", "candidate_rate",
                             "reference_rate", "result", "reason"}
        assert task["reason"]
    assert same["candidate_fingerprint"] == integrity.digest(fp())
    assert moved["candidate_fingerprint"] == integrity.digest(fp(**{"task.md": "x"}))
    text = report.as_sc012_markdown(result)
    assert "| moved | CHANGED | SAME_RUN_NAIVE | 3/3 | 3/3 |" in text
    assert "| same | UNCHANGED | PUBLISHED_BASELINE | 3/3 | 3/3 |" in text


def test_the_comparison_is_deterministic():
    candidate = paired(row("a"), row("b", fingerprint=fp(**{"task.md": "x"})))
    baseline = paired(row("a"), row("b"))
    assert json.dumps(compare(candidate, baseline)) == json.dumps(compare(candidate, baseline))


# -- reading provenance ------------------------------------------------------ #


def _git(repo, *args):
    import subprocess

    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


def _scenario(tasks, name, prompt):
    (tasks / name / "repo").mkdir(parents=True, exist_ok=True)
    (tasks / name / "task.md").write_text(prompt, encoding="utf-8")
    (tasks / name / "check.py").write_text("CATEGORY = 'fix'\nMAX_STEPS = 25\n",
                                           encoding="utf-8")
    (tasks / name / "repo" / "a.py").write_text("x = 1\n", encoding="utf-8")


@pytest.fixture
def history(tmp_path, monkeypatch):
    """A throwaway repository: `first` has `a` and `b`; `second` edits `a` and
    adds `c`; the working tree edits `b` and adds `d`, uncommitted."""
    import subprocess

    from bench import integrity

    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    tasks = repo / "bench" / "tasks"
    _scenario(tasks, "a", "first a\n")
    _scenario(tasks, "b", "first b\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "first")
    first = _git(repo, "rev-parse", "--short", "HEAD")
    at_first = integrity.fingerprint_all(tasks)
    _scenario(tasks, "a", "second a\n")
    _scenario(tasks, "c", "second c\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "second")
    second = _git(repo, "rev-parse", "--short", "HEAD")
    _scenario(tasks, "b", "uncommitted b\n")
    _scenario(tasks, "d", "uncommitted d\n")
    monkeypatch.setattr(integrity, "REPO", repo)
    return {"first": first, "second": second, "at_first": at_first}


def test_a_fully_recorded_report_is_read_as_recorded_without_history(monkeypatch):
    from bench import integrity

    def refuse(*args, **kwargs):
        raise AssertionError("recorded provenance must not read history")

    monkeypatch.setattr(integrity, "fingerprint_at", refuse)
    fingerprints, source = scenario_fingerprints(
        paired(row("a", fingerprint=fp()), row("b", fingerprint=fp(**{"task.md": "x"}))))
    assert source == "recorded"
    assert fingerprints == {"a": fp(), "b": fp(**{"task.md": "x"})}


def test_a_report_without_fingerprints_is_reconstructed_from_its_own_commit(history):
    fingerprints, source = scenario_fingerprints(
        paired(row("a", recorded=False), row("b", recorded=False), commit=history["first"]))
    assert source == f"reconstructed:{history['first']}"
    # The first commit's scenarios: not HEAD's `a`, not the working tree's `b`.
    assert fingerprints == {"a": history["at_first"]["a"], "b": history["at_first"]["b"]}


def test_a_partly_recorded_report_is_reconstructed_in_full_never_mixed(history):
    forged = fp(**{"task.md": "recorded but not trusted"})
    fingerprints, source = scenario_fingerprints(
        paired(row("a", fingerprint=forged), row("b", recorded=False),
               commit=history["first"]))
    assert source == f"reconstructed:{history['first']}"
    assert fingerprints["a"] == history["at_first"]["a"] != forged


def test_a_report_with_no_usable_commit_is_undecidable(history):
    for commit in ("", None, "0000000000000000000000000000000000000000"):
        with pytest.raises(report.Undecidable):
            scenario_fingerprints(paired(row("a", recorded=False), commit=commit))
        result = compare(paired(row("a")), paired(row("a", recorded=False), commit=commit))
        assert result["result"] == "UNDECIDABLE"
        assert result["baseline"]["fingerprint_source"] == ""


def test_a_task_missing_at_the_reports_own_commit_is_undecidable(history):
    """`c` exists at a later commit and `d` in the working tree; neither is
    borrowed for a report made at `first`."""
    for missing in ("c", "d"):
        with pytest.raises(report.Undecidable, match=f"task\\(s\\) {missing} "):
            scenario_fingerprints(paired(row("a", recorded=False),
                                         row(missing, recorded=False),
                                         commit=history["first"]))
    result = compare(paired(row("a"), row("c")),
                     paired(row("a", recorded=False), row("c", recorded=False),
                            commit=history["first"]))
    assert result["result"] == "UNDECIDABLE"
    assert any("c" in reason and history["first"] in reason
               for reason in result["undecidable_reasons"])


def test_reading_a_result_never_rewrites_it(history, tmp_path, monkeypatch):
    from bench import __main__ as cli

    monkeypatch.setattr(cli, "HERE", tmp_path)
    published = tmp_path / "published.json"
    published.write_text(json.dumps(paired(row("a", recorded=False), row("b", recorded=False),
                                           commit=history["first"]), indent=2) + "\n",
                         encoding="utf-8")
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(paired(row("a", fingerprint=history["at_first"]["a"]),
                                           row("b", fingerprint=history["at_first"]["b"]))),
                         encoding="utf-8")
    before = published.read_bytes()
    assert cli.main(["--sc012", str(candidate), "--against", str(published)]) == 0
    assert published.read_bytes() == before


def test_the_2026_09_20_baseline_is_read_from_its_own_commit_unchanged():
    import subprocess

    from bench import integrity

    if subprocess.run(["git", "cat-file", "-e", "be9cf6f^{commit}"], cwd=integrity.REPO,
                      capture_output=True).returncode != 0:
        pytest.skip("needs full history (be9cf6f)")
    before = HISTORICAL.read_bytes()
    document = json.loads(before)
    fingerprints, source = scenario_fingerprints(document)
    assert source == "reconstructed:be9cf6f"
    assert set(fingerprints) == {task["name"] for task in document["tasks"]}
    assert compare(document, document)["result"] == "PASS"
    assert HISTORICAL.read_bytes() == before


# -- the command line -------------------------------------------------------- #


@pytest.fixture
def offline_cli(tmp_path, monkeypatch):
    """`python -m bench` with every route to a provider or task run cut."""
    from bench import __main__ as cli

    def forbidden(*args, **kwargs):
        raise AssertionError("--sc012 must not load tasks, check drift or run a model")

    monkeypatch.delenv("BENCH_PROVIDER", raising=False)
    monkeypatch.delenv("BENCH_MODEL", raising=False)
    for name in ("load_tasks", "run_paired", "run_task", "run_blocked", "_load_env"):
        monkeypatch.setattr(cli, name, forbidden)
    monkeypatch.setattr(cli.integrity, "check", forbidden)
    monkeypatch.setattr(cli, "HERE", tmp_path)

    def run(candidate, baseline, *extra):
        files = []
        for name, document in (("candidate", candidate), ("baseline", baseline)):
            path = tmp_path / f"{name}.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            files.append(str(path))
        return cli.main(["--sc012", files[0], "--against", files[1], *extra])

    return cli, run, tmp_path


def test_the_sc012_command_exits_by_result_and_needs_no_provider(offline_cli):
    cli, run, tmp_path = offline_cli
    assert run(paired(row("t")), paired(row("t")), "--label", "pass") == 0
    assert run(paired(row("t", current=arm(1))), paired(row("t")), "--label", "fail") == 1
    assert run(paired(row("t")), paired(row("t"), row("u")), "--label", "undecided") == 2
    written = json.loads((tmp_path / "results" / "sc012-fail.json").read_text(encoding="utf-8"))
    assert written["result"] == "FAIL"
    assert (tmp_path / "results" / "sc012-fail.md").read_text(encoding="utf-8") \
        .startswith("# SC-012 comparison — FAIL")


def test_the_sc012_label_defaults_to_the_candidate_file(offline_cli):
    _, run, tmp_path = offline_cli
    assert run(paired(row("t")), paired(row("t"))) == 0
    assert (tmp_path / "results" / "sc012-candidate.json").is_file()


def test_sc012_without_a_baseline_is_a_usage_error(offline_cli, tmp_path):
    cli, _, _ = offline_cli
    assert cli.main(["--sc012", str(tmp_path / "candidate.json")]) == 2
    assert cli.main(["--against", str(tmp_path / "baseline.json")]) == 2
    assert cli.main(["--sc012", str(tmp_path / "absent.json"),
                     "--against", str(tmp_path / "absent.json")]) == 2
