"""Running the bot without a terminal holding it open.

The complaint this answers: the bot only worked while somebody was sitting in
the terminal with `comodor telegram start` in the foreground, which is the one
situation in which nobody needs a phone.

Nothing here starts a real bot. What is checked is the bookkeeping around the
process — the part that goes wrong quietly: a stale pid file naming a number
the kernel has since given to somebody else, a `start` that reports success for
a child that has already died, a `stop` that kills the wrong thing.
"""

from __future__ import annotations

import os
import sys

import pytest

from comodor.config import Config, Paths
from comodor.telegram import service
from comodor.telegram import unit as unit_mod


@pytest.fixture
def config(tmp_path):
    made = Config(paths=Paths(user=tmp_path / "home", project=tmp_path / "work"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    (tmp_path / "work").mkdir(parents=True, exist_ok=True)
    made.telegram.token = "42:token"
    made.telegram.allowed = [7]
    return made


# --------------------------------------------------------------------------- #
# it refuses to start what cannot work
# --------------------------------------------------------------------------- #


def test_it_will_not_start_without_a_bot(config):
    config.telegram.token = ""
    ok, why = service.start(config)

    assert ok is False
    assert "connect" in why


def test_it_will_not_start_a_bot_that_would_answer_nobody(config):
    """A bot with a token and an empty allow-list runs and ignores everybody,
    which from the outside is indistinguishable from broken."""
    config.telegram.allowed = []
    ok, why = service.start(config)

    assert ok is False
    assert "paired" in why


# --------------------------------------------------------------------------- #
# knowing whether it is running
# --------------------------------------------------------------------------- #


def test_nothing_running_is_reported_as_nothing_running(config):
    here = service.state(config)

    assert here.running is False
    assert here.pid == 0


def test_a_pid_file_for_a_dead_process_is_cleaned_up(config):
    """Left behind by a crash, it otherwise makes `start` refuse forever."""
    service.pid_file(config).write_text("999999", encoding="utf-8")

    assert service.state(config).running is False
    assert not service.pid_file(config).exists(), "the stale file was kept"


def test_a_recycled_process_id_is_not_mistaken_for_the_bot(config, monkeypatch):
    """Process ids are reused. Treating "something is alive with that number"
    as "the bot is running" is how `stop` kills an unrelated program."""
    service.pid_file(config).write_text("4321", encoding="utf-8")
    monkeypatch.setattr(service, "_alive", lambda pid: True)
    monkeypatch.setattr(service, "_command_of",
                        lambda pid: "/usr/bin/postgres -D /var/lib/postgres")

    assert service.state(config).running is False


def test_a_process_that_is_ours_is_recognised(config, monkeypatch):
    service.pid_file(config).write_text("4321", encoding="utf-8")
    monkeypatch.setattr(service, "_alive", lambda pid: True)
    monkeypatch.setattr(service, "_command_of",
                        lambda pid: "python -m comodor telegram start")

    here = service.state(config)
    assert here.running is True
    assert here.pid == 4321


def test_when_the_platform_will_not_say_liveness_is_enough(config, monkeypatch):
    """Weaker than we would like, and better than refusing to manage it."""
    service.pid_file(config).write_text("4321", encoding="utf-8")
    monkeypatch.setattr(service, "_alive", lambda pid: True)
    monkeypatch.setattr(service, "_command_of", lambda pid: "")

    assert service.state(config).running is True


def test_stopping_something_that_is_not_running_says_so(config):
    ok, why = service.stop(config)

    assert ok is False
    assert "not running" in why


@pytest.mark.parametrize("seconds,expected", [(5, "5s"), (90, "1m"),
                                              (7200, "2h 0m")])
def test_uptime_reads_as_a_duration(seconds, expected):
    import time

    here = service.State(pid=1, since=time.time() - seconds)
    assert here.uptime() == expected


# --------------------------------------------------------------------------- #
# the real thing, once
# --------------------------------------------------------------------------- #


def test_a_child_that_dies_at_once_is_not_reported_as_started(config):
    """`start` waits long enough to catch a token Telegram refuses. Reporting
    success for a process that is already gone is worse than the failure."""
    config.telegram.token = "42:definitely-not-a-token"
    ok, why = service.start(config)

    assert ok is False
    assert "stopped immediately" in why
    assert not service.pid_file(config).exists()


# --------------------------------------------------------------------------- #
# surviving a reboot is the operating system's job
# --------------------------------------------------------------------------- #


def test_the_unit_names_this_interpreter_not_a_console_script(config):
    """A service starts with a bare environment, and the directory `pipx` puts
    the `comodor` script in is on a login shell's PATH, not a daemon's."""
    plan = unit_mod.plan(config)

    if not plan.supported:
        pytest.skip(plan.why)
    assert sys.executable in plan.body
    assert "-m comodor" in plan.body or "comodor" in plan.body


def test_the_unit_is_a_user_service_never_a_system_one(config):
    """It runs an agent that edits a person's files with their credentials.
    More authority than the person who owns them buys nothing."""
    plan = unit_mod.plan(config)

    if not plan.supported:
        pytest.skip(plan.why)
    if plan.kind == "systemd":
        assert "--user" in " ".join(" ".join(step) for step in plan.enable)
        assert str(plan.path).replace("\\", "/").endswith(
            "systemd/user/comodor-telegram.service")
    if plan.kind == "launchd":
        assert "LaunchAgents" in str(plan.path)
    if plan.kind == "schtasks":
        assert "/RU" not in " ".join(" ".join(s) for s in plan.enable), \
            "no other user account"


def test_planning_writes_nothing(config):
    plan = unit_mod.plan(config)

    if not plan.supported:
        pytest.skip(plan.why)
    assert not plan.path.exists()
    assert unit_mod.installed(config) is False


@pytest.mark.skipif(os.name == "nt", reason="systemd and launchd only")
def test_the_unit_restarts_it_but_not_in_a_loop(config):
    """A burst of restarts means the network is down or the token is wrong,
    and hammering the Telegram API helps neither."""
    plan = unit_mod.plan(config)

    if plan.kind == "systemd":
        assert "Restart=on-failure" in plan.body
        assert "StartLimitBurst" in plan.body
    elif plan.kind == "launchd":
        assert "SuccessfulExit" in plan.body
