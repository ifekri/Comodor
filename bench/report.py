"""Writing down what happened, in two forms.

A JSON file, because a result that cannot be diffed against last week's is an
anecdote. A Markdown table, because a result nobody reads is one nobody acts on.

Both carry the same four facts about every task — whether it passed, how often,
what it cost and why it failed — and both name the model and the date at the
top. A number without the model beside it is not a number about anything.
"""

from __future__ import annotations

import json
import platform
import subprocess
import time
from datetime import date
from pathlib import Path

from .runner import Outcome

#: The token-accounting contract these reports obey.
#:
#: A `total_tokens` figure is only comparable with another one that was
#: counted the same way, and the counting changed. Bumping this number is how
#: a reader tells a result from before the change from one after it, without
#: rewriting any historical artifact.
#:
#: * **1 — historical.** The committed T015 (`paired-baseline-2026-09-14`) and
#:   T096 (`blocked-ablation-2026-09-16`) artifacts predate this field, so a
#:   document with no `token_accounting_version` is version 1. They counted
#:   `input + cached + output` per attempt; `written_tokens` was not reported,
#:   and the compaction-summary provider call was not counted at all. They are
#:   historical evidence and are not retroactively altered.
#: * **2 — end-to-end.** `total = input + cached + written + output`, and
#:   every provider call the task made is counted, including the compaction
#:   summary (`AgentLoop._summarise`). `written_tokens` is the prompt stored
#:   for the next request — a separate, non-overlapping part of the prompt —
#:   and is part of what the model read. `reasoning_tokens` is a subset of
#:   `output_tokens` for the supported providers and is not added again.
#:   `cost_usd` remains provider-reported and is `0.0` when the model has no
#:   price mapping: unavailable pricing, never equal economic cost.
TOKEN_ACCOUNTING_VERSION = 2


def as_json(outcomes: list[Outcome], *, provider: str, model: str,
            tries: int) -> dict:
    # A task with no valid run (`tries == 0`, every attempt invalid) is neither
    # a pass nor a fail: it is excluded from both classifications, or it would
    # count as `passed == tries` and `passed == 0` at once.
    valid = [one for one in outcomes if one.tries > 0]
    return {
        "model": model,
        "provider": provider,
        "token_accounting_version": TOKEN_ACCOUNTING_VERSION,
        "date": date.today().isoformat(),
        "tries_per_task": tries,
        "platform": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "totals": {
            "tasks": len(valid),
            "invalid": sum(1 for one in outcomes if one.tries == 0),
            "passed": sum(1 for one in valid if one.passed == one.tries),
            "partial": sum(1 for one in valid
                           if 0 < one.passed < one.tries),
            "failed": sum(1 for one in valid if one.passed == 0),
            "attempts_passed": sum(one.passed for one in valid),
            "attempts": sum(one.tries for one in valid),
            "cost_usd": round(sum(one.cost for one in valid), 4),
            "seconds": round(sum(one.seconds for one in valid), 1),
        },
        "tasks": [_task_record(one) for one in outcomes],
    }


def _task_record(one: Outcome) -> dict:
    """One task's row: the rate, and the cost figures the rate travels with.

    The token figures are per attempt (means), so a task run three times
    reads the same as a task run once. A rate without its cost, or a cost
    without its rate, is half a result (FR-076).
    """
    record = {
        "name": one.task.name,
        "category": one.task.category,
        "result": one.rate,
        "correctness": round(one.passed / one.tries, 3) if one.tries else 0.0,
        "passed": one.passed,
        "tries": one.tries,
        "mean_steps": round(one.steps, 1),
        "mean_tool_calls": round(one.mean("tool_calls"), 1),
        "mean_input_tokens": round(one.mean("input_tokens")),
        "mean_output_tokens": round(one.mean("output_tokens")),
        "mean_cached_tokens": round(one.mean("cached_tokens")),
        "mean_written_tokens": round(one.mean("written_tokens")),
        "mean_total_tokens": round(one.mean("total_tokens")),
        "clarifications": one.clarifications,
        "corrections": one.corrections,
        "validation": one.validations,
        "cost_usd": round(one.cost, 4),
        "seconds": round(one.seconds, 1),
        "why": one.why(),
        # Runs the harness could not measure, kept beside the scored ones:
        # excluded from every rate and mean, never from the record.
        "invalid_runs": len(one.invalid),
        "invalid_reasons": list(one.invalid),
    }
    sequence = one.sequence_result
    if sequence is None and one.invalid and (one.sequence or one.task.sequence):
        # Every run was invalid: no steps to describe, but the block still
        # says so rather than vanishing with the diagnosis.
        record["sequence"] = {
            "comparable": False,
            "invalid_reason": one.invalid[0],
            "windows": {},
            "verdict": "invalid",
            "reason": one.invalid[0],
            "runs": 0,
            "invalid_runs": len(one.invalid),
            "invalid_reasons": list(one.invalid),
            "passed_runs": 0,
            "steps": [],
        }
    if sequence is not None:
        runs = one.sequence_runs()
        # A sequence's attempts are its steps, so the per-try figures are per
        # whole sequence run, not per step.
        record["result"] = one.rate
        record["correctness"] = round(one.passed / one.tries, 3) if one.tries else 0.0
        for key, attribute in (("mean_steps", "steps"),
                               ("mean_tool_calls", "tool_calls"),
                               ("mean_input_tokens", "input_tokens"),
                               ("mean_output_tokens", "output_tokens"),
                               ("mean_cached_tokens", "cached_tokens"),
                               ("mean_written_tokens", "written_tokens"),
                               ("mean_total_tokens", "total_tokens")):
            record[key] = round(_mean_over_runs(runs, attribute), 1)
        record["sequence"] = _sequence_record(sequence, one, runs=len(runs))
    return record


def _mean_over_runs(runs, attribute: str) -> float:
    """The per-run mean of one attempt field, summed over each run's steps."""
    if not runs:
        return 0.0
    return (sum(sum(getattr(step, attribute) for step in run.attempts)
                for run in runs) / len(runs))


def _sequence_record(sequence, one: Outcome, runs: int = 1) -> dict:
    """The six-task sequence's record: per-step rows, windows, SC-021 verdict.

    The two primary metrics are the clarification and correction totals; the
    window comparison and the comparability flag decide the verdict, and an
    incomparable run says so rather than passing or failing.
    """
    # This block describes the first run; the task-level `result` carries the
    # aggregate over runs, so a mixed set of runs is not reported as a pass.
    first = one.verdicts[0] if one.verdicts else None
    invalid = ("" if sequence.comparable
               else sequence.invalid_reason
               or "the task inputs are not comparable — the run is invalid")
    return {
        "comparable": sequence.comparable,
        "invalid_reason": invalid,
        "windows": sequence.windows(),
        "verdict": "pass" if (first is not None and first.passed) else "fail",
        "reason": first.reason if first is not None else "",
        "runs": runs,
        "invalid_runs": len(one.invalid),
        "invalid_reasons": list(one.invalid),
        "passed_runs": one.passed,
        "steps": [
            {"index": index + 1,
             "prompt": step.prompt,
             "stopped": attempt.stopped,
             "outcome": attempt.outcome,
             # Whether the step produced the artifact it had to, not merely
             # whether its process exited cleanly.
             "success": attempt.success,
             "tools": attempt.tools,
             "clarifications": attempt.clarifications_raised,
             "corrections": attempt.corrections,
             "input_tokens": attempt.input_tokens,
             "output_tokens": attempt.output_tokens,
             "written_tokens": attempt.written_tokens,
             "diagnostics": attempt.measurement}
            for index, (step, attempt) in enumerate(
                zip(sequence.steps, sequence.attempts, strict=False))
        ],
    }


def as_markdown(report: dict) -> str:
    totals = report["totals"]
    share = (totals["attempts_passed"] / totals["attempts"] * 100
             if totals["attempts"] else 0.0)

    lines = [
        f"# Comodor benchmark — {report['model']}",
        "",
        f"`{report['provider']}` · {report['date']} · "
        f"{report['tries_per_task']} attempts per task · "
        f"{report['platform']}, Python {report['python']}",
        "",
        f"**{totals['passed']} of {totals['tasks']} tasks passed every "
        f"attempt**, {totals['partial']} passed some, {totals['failed']} "
        f"passed none — {totals['attempts_passed']}/{totals['attempts']} "
        f"attempts ({share:.0f}%).",
        "",
        f"{totals['seconds'] / 60:.0f} minutes. {_money(totals['cost_usd'])}.",
        "",
        "| Task | Category | Result | In/Out tokens | Steps | Clarif | "
        "Corr | Cost | Why it failed |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for task in report["tasks"]:
        why = task["why"].replace("|", "\\|").replace("\n", " ")
        tokens = f"{task['mean_input_tokens']}/{task['mean_output_tokens']}"
        invalid = int(task.get("invalid_runs", 0) or 0)
        result = task["result"] + (f" (+{invalid} invalid)" if invalid else "")
        lines.append(
            f"| {task['name']} | {task['category']} | "
            f"{result} | {tokens} | {task['mean_steps']} | "
            f"{task.get('clarifications', 0)} | {task.get('corrections', 0)} | "
            f"{_cell(task['cost_usd'])} | {why[:120]} |")

    lines += [
        "",
        "Every row is a real run against the model named above. The judges are "
        "programs, not models — `bench/tasks/*/check.py` is what decided each "
        "one, and `python -m bench --model ...` reproduces the table.",
        "",
    ]
    return "\n".join(lines)


def write(outcomes: list[Outcome], directory: Path, *, provider: str,
          model: str, tries: int, label: str = "") -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    report = as_json(outcomes, provider=provider, model=model, tries=tries)
    report["commit"] = _commit()
    if label:
        report["label"] = label
    if outcomes and outcomes[0].without:
        report["without"] = list(outcomes[0].without)
    if outcomes:
        report["strategy"] = outcomes[0].strategy
        report["learning"] = outcomes[0].learning

    stem = f"{_slug(model)}-{report['date']}" + (f"-{_slug(label)}" if label else "")
    if (directory / f"{stem}.json").exists():
        stem = f"{stem}-{int(time.time()) % 100000}"

    json_file = directory / f"{stem}.json"
    _write_lf(json_file, json.dumps(report, indent=2) + "\n")

    markdown_file = directory / f"{stem}.md"
    _write_lf(markdown_file, as_markdown(report))
    return json_file, markdown_file


def _write_lf(path: Path, text: str) -> None:
    """LF regardless of platform: results are committed and diffed."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _commit() -> str:
    """The commit the run measured, or an empty string outside a checkout."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
            cwd=Path(__file__).resolve().parent, timeout=5).stdout.strip()
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# the paired baseline: the product beside the naive strategy (SC-036)
# --------------------------------------------------------------------------- #


def as_paired_json(current: list[Outcome], naive: list[Outcome], *,
                   provider: str, model: str, tries: int) -> dict:
    """Both strategies, task by task, in one document.

    This is the baseline every efficiency figure in spec 002 is measured
    against, and the source the SC-011 threshold is set from. It carries,
    per task and per strategy: the outcome rate over the attempts, and the
    input, output and cached tokens, model turns and tool calls behind it.
    """
    by_name = {one.task.name: one for one in naive}
    tasks = []
    for one in current:
        other = by_name.get(one.task.name)
        tasks.append({
            "name": one.task.name,
            "category": one.task.category,
            "current": _strategy_record(one),
            "naive": _strategy_record(other) if other is not None else None,
        })
    return {
        "kind": "paired-baseline",
        "model": model,
        "provider": provider,
        "token_accounting_version": TOKEN_ACCOUNTING_VERSION,
        "date": date.today().isoformat(),
        # Which code was measured. A baseline is a statement about one
        # commit; without this it is a statement about a date.
        "commit": _commit(),
        "tries_per_task": tries,
        "platform": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "strategies": {
            "current": "the product as shipped",
            "naive": ("full history, full files and full tool output re-sent "
                      "every turn; no sweep, no pruning, no optimization"),
        },
        "totals": {
            "current": _strategy_totals(current),
            "naive": _strategy_totals(naive),
        },
        "tasks": tasks,
    }


def _strategy_record(one: Outcome) -> dict:
    record = _task_record(one)
    record.pop("name")
    record.pop("category")
    return record


def _mean_over(outcomes: list[Outcome], name: str) -> int:
    """The per-task mean of one attempt figure, over the tasks that were
    measured: an outcome with no valid run has no figure, and counting it as
    zero would halve the mean of a strategy the harness failed once."""
    measured = [one for one in outcomes if one.tries]
    if not measured:
        return 0
    return round(sum(one.mean(name) for one in measured) / len(measured))


def _strategy_totals(outcomes: list[Outcome]) -> dict:
    attempts = sum(one.tries for one in outcomes)
    passed = sum(one.passed for one in outcomes)
    return {
        "attempts_passed": passed,
        "attempts": attempts,
        "outcome_rate": round(passed / attempts, 4) if attempts else 0.0,
        "mean_total_tokens": _mean_over(outcomes, "total_tokens"),
        "mean_input_tokens": _mean_over(outcomes, "input_tokens"),
        "mean_output_tokens": _mean_over(outcomes, "output_tokens"),
        "mean_cached_tokens": _mean_over(outcomes, "cached_tokens"),
        "mean_written_tokens": _mean_over(outcomes, "written_tokens"),
        "cost_usd": round(sum(one.cost for one in outcomes), 4),
        "seconds": round(sum(one.seconds for one in outcomes), 1),
    }


def as_paired_markdown(report: dict) -> str:
    lines = [
        f"# Comodor paired baseline — {report['model']}",
        "",
        f"`{report['provider']}` · {report['date']} · "
        f"{report['tries_per_task']} attempts per task per strategy · "
        f"{report['platform']}, Python {report['python']}"
        + (f" · commit `{report['commit']}`" if report.get("commit") else ""),
        "",
        "`current` is the product as shipped. `naive` re-sends full history, "
        "full files and full tool output every turn with no sweep, pruning or "
        "optimization. Every token figure is a per-attempt mean and travels "
        "with the outcome rate it was measured beside.",
        "",
        "| Task | Category | Passed (current) | Passed (naive) | Total tokens "
        "(current) | Total tokens (naive) | In / Out / Cached (current) | "
        "In / Out / Cached (naive) | Turns (current) | Turns (naive) | "
        "Tool calls (current) | Tool calls (naive) | Regression |",
        "| --- | --- | --- | --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for task in report["tasks"]:
        cur, nai = task["current"], task.get("naive")
        lines.append(
            f"| {task['name']} | {task['category']} | "
            f"{cur['passed']}/{cur['tries']} | {_rate(nai)} | "
            f"{cur['mean_total_tokens']:,} | {_num(nai, 'mean_total_tokens')} | "
            f"{_triple(cur)} | {_triple(nai)} | "
            f"{cur['mean_steps']} | {_num(nai, 'mean_steps')} | "
            f"{cur['mean_tool_calls']} | {_num(nai, 'mean_tool_calls')} | "
            f"{_regression(cur, nai)} |")
    totals = report["totals"]
    lines += [
        "",
        f"**Totals** — current: {totals['current']['attempts_passed']}/"
        f"{totals['current']['attempts']} attempts, mean "
        f"{totals['current']['mean_total_tokens']:,} tokens per attempt; naive: "
        f"{totals['naive']['attempts_passed']}/{totals['naive']['attempts']} "
        f"attempts, mean {totals['naive']['mean_total_tokens']:,} tokens per attempt.",
        "",
        f"Token accounting version {report.get('token_accounting_version', 1)}. "
        "A total from one accounting version is not directly comparable with a "
        "total from another: version 2 adds `written_tokens` and every auxiliary "
        "provider call, including the compaction summary.",
        "",
        "The SC-011 threshold is set from these figures and recorded in "
        "`specs/002-grounded-agent-quality/spec.md`; no efficiency work is "
        "accepted against a target that predates this file.",
        "",
    ]
    return "\n".join(lines)


def _rate(record: dict | None) -> str:
    return f"{record['passed']}/{record['tries']}" if record else "—"


def _num(record: dict | None, key: str) -> str:
    if not record:
        return "—"
    value = record[key]
    return f"{value:,}" if isinstance(value, int) else str(value)


def _triple(record: dict | None) -> str:
    if not record:
        return "—"
    return (f"{record['mean_input_tokens']:,} / {record['mean_output_tokens']:,} / "
            f"{record['mean_cached_tokens']:,}")


def _regression(current: dict, naive: dict | None) -> str:
    """`yes` when the current strategy's outcome rate falls below naive's.

    FR-077: a change that reduces tokens while reducing any task's outcome rate
    must be reportable as a regression. The two rates sit in adjacent columns
    already; this names the fall so it cannot be read past. A task the naive
    strategy never ran has nothing to fall against and is left blank.
    """
    if not naive or not current.get("tries") or not naive.get("tries"):
        return ""
    if current["passed"] / current["tries"] < naive["passed"] / naive["tries"]:
        return "**yes**"
    return ""


def write_paired(current: list[Outcome], naive: list[Outcome], directory: Path, *,
                 provider: str, model: str, tries: int) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    report = as_paired_json(current, naive, provider=provider, model=model, tries=tries)
    stem = f"baseline-{_slug(model)}-{report['date']}"
    if (directory / f"{stem}.json").exists():
        stem = f"{stem}-{int(time.time()) % 100000}"
    json_file = directory / f"{stem}.json"
    _write_lf(json_file, json.dumps(report, indent=2) + "\n")
    markdown_file = directory / f"{stem}.md"
    _write_lf(markdown_file, as_paired_markdown(report))
    return json_file, markdown_file


def _money(total: float) -> str:
    """What it cost, or plainly that we do not know.

    A run against a provider with no published rate reports zero, because the
    meter has nothing to multiply by. Printing that as `$0.00` says the run was
    free, which is a different claim and one nothing here established.
    """
    if total > 0:
        return f"Cost ${total:.2f}"
    return "Cost not metered — no published rate is known for this model"


def _cell(cost: float) -> str:
    return f"${cost:.3f}" if cost > 0 else "—"


def _slug(text: str) -> str:
    kept = [character if character.isalnum() else "-"
            for character in text.lower()]
    return "".join(kept).strip("-").replace("--", "-") or "unknown"


# --------------------------------------------------------------------------- #
# the blocked single-optimization experiment (T096)
# --------------------------------------------------------------------------- #

#: Fixed so the paired bootstrap interval is reproducible. A result that moves
#: between two identical runs is not a result.
BOOTSTRAP_SEED = 20260916
BOOTSTRAP_RESAMPLES = 2000


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n % 2:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2


def _bootstrap_ci(deltas: list[float]) -> list[float] | None:
    """A 95% percentile interval for the mean paired delta. Deterministic.

    Only meaningful with enough pairs; a handful gives an interval that says
    "roughly this, maybe", which is honest, and is reported as-is rather than
    dressed up.
    """
    if len(deltas) < 8:
        return None
    import random

    rng = random.Random(BOOTSTRAP_SEED)
    n = len(deltas)
    means = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        means.append(sum(deltas[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    low = means[int(0.025 * BOOTSTRAP_RESAMPLES)]
    high = means[min(BOOTSTRAP_RESAMPLES - 1, int(0.975 * BOOTSTRAP_RESAMPLES))]
    return [round(low, 1), round(high, 1)]


def _summarise_pairs(pairs: list[tuple[float, float]]) -> dict:
    """Paired `(current, other)` values as delta and ratio summaries."""
    if not pairs:
        return {"n": 0}
    deltas = [other - current for current, other in pairs]
    ratios = [other / current for current, other in pairs if current]
    return {
        "n": len(pairs),
        "mean_delta": round(sum(deltas) / len(deltas), 1),
        "median_delta": round(_median(deltas), 1),
        "median_ratio": round(_median(ratios), 4) if ratios else None,
        "lower": sum(1 for delta in deltas if delta < 0),
        "equal": sum(1 for delta in deltas if delta == 0),
        "higher": sum(1 for delta in deltas if delta > 0),
        "mean_delta_ci95": _bootstrap_ci(deltas),
    }


def blocked_metrics(run) -> dict:
    """Paired CURRENT-vs-ablation metrics, computed block-local.

    Quality is a contingency, not a percentage: how often only CURRENT passed,
    only the ablation passed, both did, or neither did, over the same blocks.
    Tokens are paired deltas per block, summarised by mean, median and median
    ratio with the lower/equal/higher counts, so a skewed distribution is not
    hidden behind one grand total.
    """
    blocks = run.blocks()
    current = run.configurations[0]
    metrics: dict[str, dict] = {}
    metric_keys = {
        "input_tokens": "input",
        "output_tokens": "output",
        "cached_tokens": "cached",
        "written_tokens": "written",
        "total_tokens": "total",
        "cost_usd": "cost",
    }
    for config in run.configurations:
        if config == current:
            continue
        contingency = {"current_only": 0, "ablation_only": 0,
                       "both_success": 0, "both_failure": 0}
        pairs: dict[str, list] = {name: [] for name in metric_keys.values()}
        by_task: dict[str, dict[str, list]] = {}
        for (task, _), grouped in blocks.items():
            cur, abl = grouped.get(current), grouped.get(config)
            if cur is None or abl is None:
                continue
            if cur.passed and abl.passed:
                contingency["both_success"] += 1
            elif cur.passed:
                contingency["current_only"] += 1
            elif abl.passed:
                contingency["ablation_only"] += 1
            else:
                contingency["both_failure"] += 1
            task_pairs = by_task.setdefault(
                task, {name: [] for name in metric_keys.values()})
            for attribute, name in metric_keys.items():
                current_value = float(getattr(cur.attempt, attribute))
                other_value = float(getattr(abl.attempt, attribute))
                pairs[name].append((current_value, other_value))
                task_pairs[name].append((current_value, other_value))
        metrics[config] = {
            "paired_blocks": sum(1 for grouped in blocks.values()
                                 if current in grouped and config in grouped),
            "quality": contingency,
            "tokens": {name: _summarise_pairs(values)
                       for name, values in pairs.items()},
            "by_task": {task: {name: _summarise_pairs(values)
                               for name, values in names.items()}
                        for task, names in by_task.items()},
        }
    return metrics


def blocked_counterbalance(run) -> dict:
    """How often each configuration ran in each position of a block."""
    size = len(run.configurations)
    table = {config: [0] * size for config in run.configurations}
    for entry in run.attempts:
        table[entry.config][entry.position] += 1
    return table


def _block_record(key: tuple[str, int], grouped: dict, configurations) -> dict:
    task, attempt_index = key
    ordered = sorted(grouped.values(), key=lambda entry: entry.position)
    results = {}
    for config in configurations:
        entry = grouped.get(config)
        if entry is None:
            continue
        results[config] = {
            "passed": entry.passed,
            "stopped": entry.attempt.stopped,
            "outcome": entry.attempt.outcome,
            "input_tokens": entry.attempt.input_tokens,
            "output_tokens": entry.attempt.output_tokens,
            "cached_tokens": entry.attempt.cached_tokens,
            "written_tokens": entry.attempt.written_tokens,
            "total_tokens": entry.attempt.total_tokens,
            "cost_usd": round(entry.attempt.cost_usd, 6),
            "validation": entry.attempt.validation_outcome,
        }
    return {
        "task": task,
        "attempt_index": attempt_index,
        "order": [entry.config for entry in ordered],
        "results": results,
    }


def blocked_json(run) -> dict:
    blocks = run.blocks()
    passed = sum(1 for entry in run.attempts if entry.passed)
    return {
        "kind": "blocked-ablation",
        "provider": run.provider,
        "model": run.model,
        "token_accounting_version": TOKEN_ACCOUNTING_VERSION,
        "date": date.today().isoformat(),
        "commit": _commit(),
        "platform": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "tries_per_task": run.tries,
        "cohort": list(run.cohort),
        "configurations": list(run.configurations),
        "scheme": run.scheme,
        "counts": {
            "blocks": len(blocks),
            "attempts": len(run.attempts),
            "planned_attempts": run.planned_attempts,
            "attempts_passed": passed,
        },
        "counterbalance": blocked_counterbalance(run),
        "metrics": blocked_metrics(run),
        "blocks": [_block_record(key, grouped, run.configurations)
                   for key, grouped in sorted(blocks.items())],
    }


def blocked_markdown(report: dict) -> str:
    counts = report["counts"]
    lines = [
        f"# Comodor blocked optimization experiment — {report['model']}",
        "",
        f"`{report['provider']}` · {report['date']} · "
        f"{counts['blocks']} blocks · {counts['attempts']} attempts · "
        f"{report['platform']}, Python {report['python']}",
        "",
        "Every `(task, try)` block ran all seven configurations in a "
        "counterbalanced order, so a CURRENT-vs-ablation pair differs by the "
        "switch and little else.",
        "",
        f"**{counts['attempts_passed']}/{counts['attempts']} attempts passed.**",
        "",
        "| Ablation | Cur-only | Abl-only | Both | Neither | mean total delta "
        "| median total delta | median ratio | lower/eq/higher |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for config, metric in report["metrics"].items():
        quality = metric["quality"]
        total = metric["tokens"]["total"]
        lines.append(
            f"| {config} | {quality['current_only']} | {quality['ablation_only']} "
            f"| {quality['both_success']} | {quality['both_failure']} "
            f"| {total.get('mean_delta', 0)} | {total.get('median_delta', 0)} "
            f"| {total.get('median_ratio', '-')} "
            f"| {total.get('lower', 0)}/{total.get('equal', 0)}/{total.get('higher', 0)} |")
    lines += [
        "",
        "`total_tokens = input + cached + written + output` (what the model "
        "read plus what it wrote; cached and written are additive, not subsets "
        "of input). "
        "`cost_usd` is 0.00 for a model with no price mapping — it is not "
        "evidence of equal cost.",
        "",
    ]
    return "\n".join(lines)


def write_blocked(run, directory: Path, *, label: str = "") -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    report = blocked_json(run)
    stem = f"blocked-{_slug(run.model)}-{report['date']}"
    if label:
        stem = f"{stem}-{_slug(label)}"
    if (directory / f"{stem}.json").exists():
        stem = f"{stem}-{int(time.time()) % 100000}"
    json_file = directory / f"{stem}.json"
    _write_lf(json_file, json.dumps(report, indent=2) + "\n")
    markdown_file = directory / f"{stem}.md"
    _write_lf(markdown_file, blocked_markdown(report))
    return json_file, markdown_file
