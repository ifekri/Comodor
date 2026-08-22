"""Diagnostics, and the repairs that follow from them.

A repair is a program editing a user's files on their behalf, so the tests are
mostly about restraint: what it refuses to touch, and whether running it twice
is safe.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from comodor.config import Config, MCPServerConfig, load
from comodor.doctor import Status, apply_fixes, run_checks


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("COMODOR_HOME", str(tmp_path / "home"))
    (tmp_path / "project").mkdir(parents=True, exist_ok=True)
    return tmp_path


def configured(home):
    """A machine that has been set up and works.

    The model matters: it has to be one the pricing registry knows a rate for,
    or the spend-limit check quite correctly reports that the ceiling cannot be
    enforced - and a fixture meant to represent a healthy machine would be
    representing one with a real problem.
    """
    config = load(cwd=home / "project", use_environment=False)
    config.use("anthropic", api_key="sk-test", model="claude-sonnet-5")
    config.save()
    return load(cwd=home / "project", use_environment=False)


def finding(report, name):
    for entry in report.findings:
        if entry.name == name:
            return entry
    raise AssertionError(f"no check named {name!r}; got "
                         f"{[f.name for f in report.findings]}")


# --------------------------------------------------------------------------- #
# a healthy machine
# --------------------------------------------------------------------------- #


def test_a_configured_machine_reports_no_problems(home):
    report = run_checks(configured(home))
    assert report.problems == [], [(f.name, f.detail) for f in report.problems]
    assert report.worst is Status.OK


def test_checks_never_raise_on_a_bare_machine(home):
    """Doctor is what you run when things are broken; it must survive that."""
    report = run_checks(load(cwd=home / "project", use_environment=False))
    assert report.findings
    assert report.worst is Status.FAIL          # nothing is set up yet


# --------------------------------------------------------------------------- #
# what it fixes
# --------------------------------------------------------------------------- #


def test_a_missing_skills_folder_is_not_treated_as_a_fault(home):
    """It is the ordinary state before the first run, which creates it.

    Doctor is only worth reading if everything in it matters; warning about
    something that is about to fix itself trains people to skim.
    """
    config = configured(home)
    assert not config.paths.skills.exists()

    entry = finding(run_checks(config), "skills")
    assert entry.status is Status.OK
    assert entry.repair is None


def test_a_corrupt_search_index_is_deleted_and_rebuilds(home):
    config = configured(home)
    sessions = config.paths.user / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    index = sessions / "search.db"
    index.write_bytes(b"this is not a database" * 100)

    report = run_checks(config)
    assert finding(report, "session search").status is Status.WARN

    apply_fixes(report)
    assert not index.exists(), "a cache is the one thing safe to delete"
    assert finding(run_checks(config), "session search").status is Status.OK


def test_leftover_temporary_files_are_removed(home):
    config = configured(home)
    (config.paths.user / "config.json.tmp").write_text("half a write",
                                                       encoding="utf-8")
    report = run_checks(config)
    assert finding(report, "leftover files").status is Status.WARN

    apply_fixes(report)
    assert not (config.paths.user / "config.json.tmp").exists()


def test_a_selected_provider_that_does_not_exist_is_replaced(home):
    config = configured(home)
    config.provider = "a-provider-that-was-removed"

    report = run_checks(config)
    assert finding(report, "provider").status is Status.FAIL

    apply_fixes(report)
    assert config.provider == "anthropic"
    assert finding(run_checks(config), "provider").status is Status.OK


def test_a_missing_model_falls_back_to_the_provider_default(home):
    config = configured(home)
    config.model = ""
    config.providers["anthropic"].model = ""

    report = run_checks(config)
    assert finding(report, "model").status is Status.FAIL

    apply_fixes(report)
    assert config.active_model()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions only")
def test_a_world_readable_config_is_tightened(home):
    config = configured(home)
    config.paths.config_file.chmod(0o644)

    report = run_checks(config)
    assert finding(report, "config permissions").status is Status.WARN

    apply_fixes(report)
    mode = stat.S_IMODE(config.paths.config_file.stat().st_mode)
    assert mode & (stat.S_IRGRP | stat.S_IROTH) == 0


def test_fixing_twice_changes_nothing_the_second_time(home):
    """Somebody confused will run it again. That must be harmless."""
    config = configured(home)
    (config.paths.user / "stale.tmp").write_text("x", encoding="utf-8")

    apply_fixes(run_checks(config))
    first = run_checks(config)
    apply_fixes(first)
    second = run_checks(config)

    assert [f.status for f in first.findings] == [f.status for f in second.findings]
    assert second.problems == []


# --------------------------------------------------------------------------- #
# what it refuses to touch
# --------------------------------------------------------------------------- #


def test_a_corrupt_config_is_reported_but_never_overwritten(home):
    """It holds the API key. Rewriting it with defaults would destroy the one
    thing on this machine that cannot be regenerated."""
    config = configured(home)
    config.paths.config_file.write_text("{ not json at all", encoding="utf-8")

    report = run_checks(config)
    entry = finding(report, "config file")

    assert entry.status is Status.FAIL
    assert entry.repair is None, "doctor must not rewrite a file holding a key"
    assert "will not overwrite" in entry.remedy

    apply_fixes(report)
    assert config.paths.config_file.read_text(encoding="utf-8") == "{ not json at all"


def test_a_corrupt_brain_is_reported_but_never_deleted(home):
    config = configured(home)
    config.paths.brain_db.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4000)

    report = run_checks(config)
    entry = finding(report, "brain")

    assert entry.status is Status.FAIL
    assert entry.repair is None, "it holds everything the agent has learned"

    apply_fixes(report)
    assert config.paths.brain_db.exists()


def test_a_broken_skill_file_is_named_rather_than_guessed_at(home):
    config = configured(home)
    config.paths.skills.mkdir(parents=True, exist_ok=True)
    (config.paths.skills / "broken.md").write_text("no front matter here",
                                                   encoding="utf-8")

    entry = finding(run_checks(config), "skills")
    assert entry.status is Status.WARN
    assert "broken.md" in entry.detail
    assert entry.repair is None, "the user wrote it; guessing would be worse"


# --------------------------------------------------------------------------- #
# MCP
# --------------------------------------------------------------------------- #


def test_mcp_is_not_mentioned_when_no_server_is_configured(home):
    report = run_checks(configured(home))
    assert all(f.name != "mcp servers" for f in report.findings)


def test_a_configured_but_disabled_server_is_not_started(home):
    config = configured(home)
    config.mcp.servers["nope"] = MCPServerConfig(
        name="nope", command="a-command-that-does-not-exist", enabled=False)

    entry = finding(run_checks(config), "mcp servers")
    assert entry.status is Status.OK
    assert "none enabled" in entry.detail


def test_a_server_that_cannot_start_is_reported(home):
    config = configured(home)
    config.mcp.servers["nope"] = MCPServerConfig(
        name="nope", command="a-command-that-does-not-exist", enabled=True)

    entry = finding(run_checks(config), "mcp servers")
    assert entry.status is Status.WARN
    assert "nope" in entry.detail
    assert "disable" in entry.remedy


# --------------------------------------------------------------------------- #
# the command
# --------------------------------------------------------------------------- #


def test_doctor_exits_non_zero_when_something_is_broken(home, capsys):
    from comodor.cli import run_doctor

    config = configured(home)
    config.paths.config_file.write_text("{ broken", encoding="utf-8")

    assert run_doctor(config) == 1
    assert "config file" in capsys.readouterr().out


def test_doctor_exits_zero_on_a_healthy_machine(home, capsys):
    from comodor.cli import run_doctor

    assert run_doctor(configured(home)) == 0


def test_doctor_fix_repairs_and_says_what_it_did(home, capsys):
    from comodor.cli import run_doctor

    config = configured(home)
    (config.paths.user / "stale.tmp").write_text("x", encoding="utf-8")

    run_doctor(config, fix=True)
    output = capsys.readouterr().out

    assert "Repairs" in output
    assert "fixed" in output
    assert not (config.paths.user / "stale.tmp").exists()


def test_doctor_offers_the_fix_without_applying_it(home, capsys):
    from comodor.cli import run_doctor

    config = configured(home)
    (config.paths.user / "stale.tmp").write_text("x", encoding="utf-8")

    run_doctor(config)
    output = capsys.readouterr().out

    assert "doctor --fix" in output
    assert (config.paths.user / "stale.tmp").exists(), \
        "a diagnostic command must not silently change files"


def test_a_stale_provider_in_the_file_is_written_back(home):
    """Loading falls back silently, which leaves the file saying something untrue.

    Nothing is broken — but every future run repeats the guess, and doctor is
    the one place that should notice.
    """
    config = configured(home)
    document = json.loads(config.paths.config_file.read_text(encoding="utf-8"))
    document["provider"] = "a-provider-that-no-longer-exists"
    config.paths.config_file.write_text(json.dumps(document), encoding="utf-8")

    reloaded = load(cwd=home / "project", use_environment=False)
    assert reloaded.provider == "anthropic", "loading should still work"

    report = run_checks(reloaded)
    assert finding(report, "saved provider").status is Status.WARN

    apply_fixes(report)
    written = json.loads(reloaded.paths.config_file.read_text(encoding="utf-8"))
    assert written["provider"] == "anthropic"
    assert written["providers"]["anthropic"]["api_key"] == "sk-test", \
        "repairing the provider must not lose the key"


def test_a_provider_that_exists_but_is_not_selected_is_not_flagged(home):
    """Switching with --provider for one run is not a fault in the file."""
    config = configured(home)
    config.provider = "groq"

    assert all(f.name != "saved provider" for f in run_checks(config).findings)


def test_one_file_matching_two_patterns_is_counted_once(home):
    """`config.json.tmp` matches both globs; saying 2 and removing 1 is worse
    than saying nothing."""
    config = configured(home)
    (config.paths.user / "config.json.tmp").write_text("x", encoding="utf-8")

    entry = finding(run_checks(config), "leftover files")
    assert entry.detail.startswith("1 ")


# --------------------------------------------------------------------------- #
# the version check
# --------------------------------------------------------------------------- #


def test_the_version_check_is_the_only_one_that_needs_a_network(monkeypatch):
    """So a report can still be gathered from somewhere with no route out."""
    from comodor.update import Release

    monkeypatch.setattr("comodor.update.latest", lambda **_: Release("99.0.0"))
    config = Config()

    online = [f.name for f in run_checks(config).findings]
    offline = [f.name for f in run_checks(config, online=False).findings]

    assert "version" in online
    assert "version" not in offline
    assert offline == [name for name in online if name != "version"]


def test_a_newer_release_is_reported_with_the_command_that_gets_it(monkeypatch):
    """Doctor is where people look when something is wrong, and "four versions
    behind" is often the whole answer."""
    from comodor.doctor import Status, _check_version
    from comodor.update import Release

    monkeypatch.setattr("comodor.update.latest", lambda **_: Release("99.0.0"))

    finding = _check_version(Config())

    assert finding is not None
    assert finding.status is Status.WARN
    assert "99.0.0" in finding.detail
    assert finding.remedy == "comodor update"
    # Never a repair: --fix must not change what is installed unasked.
    assert finding.repair is None


def test_being_offline_is_not_a_fault_to_report(monkeypatch):
    """A diagnostic that hangs, or invents a problem, on an aeroplane."""
    from comodor.doctor import _check_version

    monkeypatch.setattr("comodor.update.latest", lambda **_: None)

    assert _check_version(Config()) is None


def test_the_current_version_passes(monkeypatch):
    from comodor import __version__
    from comodor.doctor import Status, _check_version
    from comodor.update import Release

    monkeypatch.setattr("comodor.update.latest", lambda **_: Release(__version__))

    finding = _check_version(Config())

    assert finding is not None and finding.status is Status.OK


# --------------------------------------------------------------------------- #
# a ceiling, or a decoration
# --------------------------------------------------------------------------- #


def test_a_spend_limit_that_cannot_fire_is_reported(home):
    """The loop stops a task when the cost passes `max_cost_usd`, and the cost
    comes from a table with no rate for most models. For one of those the meter
    never leaves zero and the limit never fires - silently, which is the part
    worth reporting."""
    config = load(cwd=home / "project", use_environment=False)
    config.use("openai", api_key="sk-test", model="gpt-4o")
    config.agent.max_cost_usd = 5.0

    found = finding(run_checks(config, online=False), "spend limit")

    assert found.status is Status.WARN
    assert "gpt-4o" in found.detail
    assert "max_steps" in found.remedy, "say which ceilings do work"


def test_a_spend_limit_on_a_priced_model_is_fine(home):
    config = load(cwd=home / "project", use_environment=False)
    config.use("anthropic", api_key="sk-test", model="claude-sonnet-5")
    config.agent.max_cost_usd = 5.0

    assert finding(run_checks(config, online=False),
                   "spend limit").status is Status.OK


def test_a_model_on_your_own_machine_needs_no_ceiling(home):
    config = load(cwd=home / "project", use_environment=False)
    config.use("ollama", model="qwen2.5-coder:14b")
    config.agent.max_cost_usd = 5.0

    found = finding(run_checks(config, online=False), "spend limit")

    assert found.status is Status.OK
    assert "your machine" in found.detail


def test_no_ceiling_asked_for_means_nothing_to_check(home):
    config = load(cwd=home / "project", use_environment=False)
    config.use("openai", api_key="sk-test", model="gpt-4o")
    config.agent.max_cost_usd = 0.0

    names = [f.name for f in run_checks(config, online=False).findings]
    assert "spend limit" not in names
