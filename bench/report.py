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


def as_json(outcomes: list[Outcome], *, provider: str, model: str,
            tries: int) -> dict:
    return {
        "model": model,
        "provider": provider,
        "date": date.today().isoformat(),
        "tries_per_task": tries,
        "platform": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "totals": {
            "tasks": len(outcomes),
            "passed": sum(1 for one in outcomes if one.passed == one.tries),
            "partial": sum(1 for one in outcomes
                           if 0 < one.passed < one.tries),
            "failed": sum(1 for one in outcomes if one.passed == 0),
            "attempts_passed": sum(one.passed for one in outcomes),
            "attempts": sum(one.tries for one in outcomes),
            "cost_usd": round(sum(one.cost for one in outcomes), 4),
            "seconds": round(sum(one.seconds for one in outcomes), 1),
        },
        "tasks": [_task_record(one) for one in outcomes],
    }


def _task_record(one: Outcome) -> dict:
    """One task's row: the rate, and the cost figures the rate travels with.

    The token figures are per attempt (means), so a task run three times
    reads the same as a task run once. A rate without its cost, or a cost
    without its rate, is half a result (FR-076).
    """
    return {
        "name": one.task.name,
        "category": one.task.category,
        "passed": one.passed,
        "tries": one.tries,
        "mean_steps": round(one.steps, 1),
        "mean_tool_calls": round(one.mean("tool_calls"), 1),
        "mean_input_tokens": round(one.mean("input_tokens")),
        "mean_output_tokens": round(one.mean("output_tokens")),
        "mean_cached_tokens": round(one.mean("cached_tokens")),
        "mean_total_tokens": round(one.mean("total_tokens")),
        "cost_usd": round(one.cost, 4),
        "seconds": round(one.seconds, 1),
        "why": one.why(),
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
        "| Task | Category | Passed | Steps | Cost | Why it failed |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for task in report["tasks"]:
        why = task["why"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {task['name']} | {task['category']} | "
            f"{task['passed']}/{task['tries']} | {task['mean_steps']} | "
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
          model: str, tries: int) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    report = as_json(outcomes, provider=provider, model=model, tries=tries)

    stem = f"{_slug(model)}-{report['date']}"
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
    if not outcomes:
        return 0
    return round(sum(one.mean(name) for one in outcomes) / len(outcomes))


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
        "Tool calls (current) | Tool calls (naive) |",
        "| --- | --- | --- | --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for task in report["tasks"]:
        cur, nai = task["current"], task.get("naive")
        lines.append(
            f"| {task['name']} | {task['category']} | "
            f"{cur['passed']}/{cur['tries']} | {_rate(nai)} | "
            f"{cur['mean_total_tokens']:,} | {_num(nai, 'mean_total_tokens')} | "
            f"{_triple(cur)} | {_triple(nai)} | "
            f"{cur['mean_steps']} | {_num(nai, 'mean_steps')} | "
            f"{cur['mean_tool_calls']} | {_num(nai, 'mean_tool_calls')} |")
    totals = report["totals"]
    lines += [
        "",
        f"**Totals** — current: {totals['current']['attempts_passed']}/"
        f"{totals['current']['attempts']} attempts, mean "
        f"{totals['current']['mean_total_tokens']:,} tokens per attempt; naive: "
        f"{totals['naive']['attempts_passed']}/{totals['naive']['attempts']} "
        f"attempts, mean {totals['naive']['mean_total_tokens']:,} tokens per attempt.",
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
