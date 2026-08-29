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
        "tasks": [
            {
                "name": one.task.name,
                "category": one.task.category,
                "passed": one.passed,
                "tries": one.tries,
                "mean_steps": round(one.steps, 1),
                "cost_usd": round(one.cost, 4),
                "seconds": round(one.seconds, 1),
                "why": one.why(),
            }
            for one in outcomes
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
    json_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    markdown_file = directory / f"{stem}.md"
    markdown_file.write_text(as_markdown(report), encoding="utf-8")
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
