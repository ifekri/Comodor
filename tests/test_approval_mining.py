"""Approval mining: turning a log of human yeses into allowlist proposals —
and never proposing a stem that can destroy things."""

from __future__ import annotations

import json

import pytest

from comodor.safety.mining import (
    NEVER_PROPOSE,
    apply_proposals,
    load_approvals,
    propose,
    stem_of,
)


def write_log(tmp_path, commands, corrupt=False):
    path = tmp_path / "approvals.jsonl"
    lines = [json.dumps({"at": 1000 + i, "command": command})
             for i, command in enumerate(commands)]
    if corrupt:
        lines.insert(3, "this is not json")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# -- reading the log ----------------------------------------------------------- #

def test_the_log_is_read_oldest_first(tmp_path):
    path = write_log(tmp_path, ["make test", "make lint"])
    assert load_approvals(path) == ["make test", "make lint"]


def test_a_corrupt_line_is_skipped_not_fatal(tmp_path):
    path = write_log(tmp_path, ["make test", "make lint", "make build",
                                "make check"], corrupt=True)
    assert len(load_approvals(path)) == 4


def test_a_missing_log_means_no_evidence(tmp_path):
    assert load_approvals(tmp_path / "nope.jsonl") == []


# -- the stem, and what it must never be --------------------------------------- #

def test_the_stem_is_the_first_word_of_the_first_branch():
    assert stem_of("pytest -k slow") == "pytest"
    assert stem_of("make build && make test") == "make"
    assert stem_of("echo hi | tee log") == "echo"


def test_destructive_stems_are_never_proposed(tmp_path):
    # Twelve approved `rm`s are twelve rm commands the human read — not a
    # standing licence for the first word `rm`.
    path = write_log(tmp_path, [f"rm build/{i}.o" for i in range(12)])
    assert propose(path) == []
    assert "rm" in NEVER_PROPOSE


@pytest.mark.parametrize("stem", [
    "rm", "sh", "bash", "curl", "wget", "sudo", "dd", "mkfs", "chmod",
    "ssh", "kill", "mv", "git",
])
def test_the_never_propose_list_holds_the_dangerous_classes(stem, tmp_path):
    assert stem in NEVER_PROPOSE


def test_a_quiet_stem_that_crossed_the_threshold_is_proposed(tmp_path):
    path = write_log(tmp_path, ["make test", "make lint", "make build"])
    proposals = propose(path)
    assert [item.stem for item in proposals] == ["make"]
    assert proposals[0].approvals == 3


def test_below_the_threshold_nothing_is_proposed(tmp_path):
    path = write_log(tmp_path, ["make test", "make lint"])
    assert propose(path) == []


def test_the_threshold_can_be_moved(tmp_path):
    path = write_log(tmp_path, ["ruff check", "ruff format"])
    assert [item.stem for item in propose(path, min_approvals=2)] == ["ruff"]


def test_examples_carry_the_actual_commands(tmp_path):
    path = write_log(tmp_path, ["pytest -q", "pytest -x", "pytest -k fast"])
    proposals = propose(path)
    assert proposals[0].examples[0] == "pytest -q"
    assert "approved 3 times" in proposals[0].reason


# -- applying ------------------------------------------------------------------- #

def test_applying_writes_the_stems_into_the_config(tmp_path, workspace):
    from comodor.config import Config, Paths

    config = Config(paths=Paths(user=tmp_path / "home", project=workspace))
    config.paths.user.mkdir(parents=True, exist_ok=True)
    added = apply_proposals(config, ["make", "pytest", "make"])
    assert added == ["make", "pytest"]
    assert config.safety.allow_commands == ["make", "pytest"]
    assert (config.paths.config_file).exists()


def test_applying_keeps_what_was_already_there(tmp_path, workspace):
    from comodor.config import Config, Paths

    config = Config(paths=Paths(user=tmp_path / "home", project=workspace))
    config.paths.user.mkdir(parents=True, exist_ok=True)
    config.safety.allow_commands = ["ruff"]
    added = apply_proposals(config, ["ruff", "make"])
    assert added == ["make"]
    assert config.safety.allow_commands == ["ruff", "make"]
