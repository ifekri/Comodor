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
