"""Running a phone channel without a terminal holding it open.

The complaint this answers: the bot only worked while somebody was sitting in
the terminal with `comodor telegram start` in the foreground, which is the one
situation in which nobody needs a phone.

Every test runs against both channels. The process bookkeeping is one piece of
code parameterised by which channel it is managing, so testing it once against
Telegram would leave WhatsApp asserting nothing.

Nothing here starts a real bot. What is checked is the bookkeeping around the
process — the part that goes wrong quietly: a stale pid file naming a number
the kernel has since given to somebody else, a `start` that reports success for
a child that has already died, a `stop` that kills the wrong thing.
"""

from __future__ import annotations

import os
import sys

import pytest

from comodor.channels import TELEGRAM, WHATSAPP
from comodor.channels import daemon as service
from comodor.channels import unit as unit_mod
from comodor.config import Config, Paths

#: Both, on every test. One piece of code manages both processes.
BOTH = pytest.mark.parametrize("channel", [TELEGRAM, WHATSAPP],
                               ids=lambda c: c.name)


@pytest.fixture
def config(tmp_path):
    made = Config(paths=Paths(user=tmp_path / "home", project=tmp_path / "work"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    (tmp_path / "work").mkdir(parents=True, exist_ok=True)
    made.telegram.token = "42:token"
    made.telegram.allowed = [7]
    made.whatsapp.token = "EAA-token"
    made.whatsapp.phone_number_id = "1234567890"
    made.whatsapp.allowed = ["15550001111"]
    return made


# --------------------------------------------------------------------------- #
# it refuses to start what cannot work
# --------------------------------------------------------------------------- #


@BOTH
def test_it_will_not_start_without_a_bot(channel, config):
    channel.settings(config).token = ""
    ok, why = service.start(config, channel)

    assert ok is False
    assert "connect" in why.lower()


@BOTH
def test_it_will_not_start_a_bot_that_would_answer_nobody(channel, config):
    """A bot with a token and an empty allow-list runs and ignores everybody,
    which from the outside is indistinguishable from broken."""
    channel.settings(config).allowed = []
    ok, why = service.start(config, channel)

    assert ok is False
    assert "paired" in why


# --------------------------------------------------------------------------- #
# knowing whether it is running
# --------------------------------------------------------------------------- #


@BOTH
def test_nothing_running_is_reported_as_nothing_running(channel, config):
    here = service.state(config, channel)

    assert here.running is False
    assert here.pid == 0


@BOTH
def test_a_pid_file_for_a_dead_process_is_cleaned_up(channel, config):
    """Left behind by a crash, it otherwise makes `start` refuse forever."""
    service.pid_file(config, channel).write_text("999999", encoding="utf-8")

    assert service.state(config, channel).running is False
    assert not service.pid_file(config, channel).exists(), "the stale file was kept"


@BOTH
def test_a_recycled_process_id_is_not_mistaken_for_the_bot(channel, config, monkeypatch):
    """Process ids are reused. Treating "something is alive with that number"
    as "the bot is running" is how `stop` kills an unrelated program."""
    service.pid_file(config, channel).write_text("4321", encoding="utf-8")
    monkeypatch.setattr(service, "_alive", lambda pid: True)
    monkeypatch.setattr(service, "_command_of",
                        lambda pid: "/usr/bin/postgres -D /var/lib/postgres")

    assert service.state(config, channel).running is False


@BOTH
def test_a_process_that_is_ours_is_recognised(channel, config, monkeypatch):
    service.pid_file(config, channel).write_text("4321", encoding="utf-8")
    monkeypatch.setattr(service, "_alive", lambda pid: True)
    monkeypatch.setattr(service, "_command_of",
                        lambda pid: "python -m comodor telegram start")

    here = service.state(config, channel)
    assert here.running is True
    assert here.pid == 4321


@BOTH
def test_when_the_platform_will_not_say_liveness_is_enough(channel, config, monkeypatch):
    """Weaker than we would like, and better than refusing to manage it."""
    service.pid_file(config, channel).write_text("4321", encoding="utf-8")
    monkeypatch.setattr(service, "_alive", lambda pid: True)
    monkeypatch.setattr(service, "_command_of", lambda pid: "")

    assert service.state(config, channel).running is True


@BOTH
def test_stopping_something_that_is_not_running_says_so(channel, config):
    ok, why = service.stop(config, channel)

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


@BOTH
def test_a_child_that_dies_at_once_is_not_reported_as_started(channel, config):
    """`start` waits long enough to catch a token Telegram refuses. Reporting
    success for a process that is already gone is worse than the failure."""
    channel.settings(config).token = "definitely-not-a-token"
    ok, why = service.start(config, channel)

    assert ok is False
    assert "stopped immediately" in why
    assert not service.pid_file(config, channel).exists()


# --------------------------------------------------------------------------- #
# surviving a reboot is the operating system's job
# --------------------------------------------------------------------------- #


@BOTH
def test_the_unit_names_this_interpreter_not_a_console_script(channel, config):
    """A service starts with a bare environment, and the directory `pipx` puts
    the `comodor` script in is on a login shell's PATH, not a daemon's."""
    plan = unit_mod.plan(config, channel)

    if not plan.supported:
        pytest.skip(plan.why)
    assert sys.executable in plan.body
    assert "-m comodor" in plan.body or "comodor" in plan.body


@BOTH
def test_the_unit_is_a_user_service_never_a_system_one(channel, config):
    """It runs an agent that edits a person's files with their credentials.
    More authority than the person who owns them buys nothing."""
    plan = unit_mod.plan(config, channel)

    if not plan.supported:
        pytest.skip(plan.why)
    if plan.kind == "systemd":
        assert "--user" in " ".join(" ".join(step) for step in plan.enable)
        assert str(plan.path).replace("\\", "/").endswith(
            f"systemd/user/comodor-{channel.name}.service")
    if plan.kind == "launchd":
        assert "LaunchAgents" in str(plan.path)
    if plan.kind == "schtasks":
        assert "/RU" not in " ".join(" ".join(s) for s in plan.enable), \
            "no other user account"


@BOTH
def test_planning_writes_nothing(channel, config):
    plan = unit_mod.plan(config, channel)

    if not plan.supported:
        pytest.skip(plan.why)
    assert not plan.path.exists()
    assert unit_mod.installed(config, channel) is False


@pytest.mark.skipif(os.name == "nt", reason="systemd and launchd only")
@BOTH
def test_the_unit_restarts_it_but_not_in_a_loop(channel, config):
    """A burst of restarts means the network is down or the token is wrong,
    and hammering the Telegram API helps neither."""
    plan = unit_mod.plan(config, channel)

    if plan.kind == "systemd":
        assert "Restart=on-failure" in plan.body
        assert "StartLimitBurst" in plan.body
    elif plan.kind == "launchd":
        assert "SuccessfulExit" in plan.body
