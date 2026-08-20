"""Moving to the newest published version.

Two halves, and the risky one is not the download.

Comparing versions is the half that fails quietly: get it wrong by one rule and
the command either offers an upgrade that is a downgrade, or reports "up to
date" to somebody three releases behind. `hatch-vcs` puts a `.devN+ghash` on
every build between tags, so those are not an edge case here — they are what a
developer sees every day.

The other half is picking the command. `pip install --upgrade` inside a uv tool
environment appears to work and leaves uv's record pointing at a version that
is not there any more; `uv tool upgrade` against a plain pip install fails
outright. Nothing here runs a real upgrade — what is checked is that the right
command comes out for each way the thing can have been installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from comodor.uninstall import Installation
from comodor.update import (
    Release, apply, is_newer, latest, parse, plan, upgrade,
)


# --------------------------------------------------------------------------- #
# comparing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("newer, older", [
    ("0.3.0", "0.2.9"),
    ("0.3.1", "0.3.0"),
    ("1.0.0", "0.99.99"),
    ("0.10.0", "0.9.0"),                       # not a string comparison
    ("0.3.0", "0.3.0rc1"),                     # a release beats its own candidate
    ("0.3.0rc2", "0.3.0rc1"),
    ("0.3.0rc1", "0.3.0b1"),
    ("0.3.0b1", "0.3.0a9"),
    ("0.3.0a1", "0.3.0.dev9"),                 # a dev build is the earliest of all
    ("0.3.0", "0.3.0.dev1"),
    ("0.3.1.dev1", "0.3.0"),                   # ...but of the *next* version
])
def test_which_way_round_two_versions_go(newer, older):
    assert is_newer(newer, older)
    assert not is_newer(older, newer)


@pytest.mark.parametrize("a, b", [
    ("0.3", "0.3.0"),                          # padded, so these are the same point
    ("0.3.0", "0.3.0"),
    ("0.3.1.dev4+g56b14a7", "0.3.1.dev4+gabc1234"),   # the hash is not an ordering
])
def test_versions_that_are_the_same_point_in_the_sequence(a, b):
    assert not is_newer(a, b)
    assert not is_newer(b, a)


def test_a_development_build_is_behind_the_release_it_is_heading_for():
    """Which is what everybody working on it is running."""
    assert is_newer("0.3.1", "0.3.1.dev4+g56b14a7")
    # And ahead of the one it came after, so `update` says "ahead" not "behind".
    assert is_newer("0.3.1.dev4+g56b14a7", "0.3.0")


@pytest.mark.parametrize("junk", ["", "latest", "not a version", "v", "1.2.x"])
def test_something_that_is_not_a_version_is_not_treated_as_one(junk):
    assert parse(junk) is None
    # Never newer, in either direction: silence beats a wrong upgrade.
    assert not is_newer(junk, "0.3.0")
    assert not is_newer("0.3.0", junk)


def test_a_leading_v_is_a_tag_not_a_different_version():
    assert not is_newer("v0.3.0", "0.3.0")


# --------------------------------------------------------------------------- #
# asking the index
# --------------------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, text: str, status: int = 200) -> None:
        self.text = text
        self.status_code = status

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_the_newest_version_is_read_from_the_index(monkeypatch):
    body = ('{"info": {"version": "9.9.9", "summary": "a thing",'
            ' "release_url": "https://pypi.org/project/comodor/9.9.9/"}}')
    monkeypatch.setattr("comodor.update.http.get", lambda *a, **k: FakeResponse(body))

    release = latest()

    assert release is not None
    assert release.version == "9.9.9"
    assert release.url.endswith("/9.9.9/")


@pytest.mark.parametrize("body, status", [
    ("not json at all", 200),
    ('{"info": {}}', 200),                     # answered, but says nothing useful
    ('{"info": {"version": "1.0"}}', 503),
])
def test_an_index_that_cannot_be_understood_returns_nothing(body, status,
                                                            monkeypatch):
    """None means "say so", not "assume up to date"."""
    monkeypatch.setattr("comodor.update.http.get",
                        lambda *a, **k: FakeResponse(body, status))

    assert latest() is None


def test_a_network_that_is_not_there_returns_nothing(monkeypatch):
    from comodor.net import http

    def refuse(*_a, **_k):
        raise http.ConnectionFailed("no route to host")

    monkeypatch.setattr("comodor.update.http.get", refuse)

    assert latest() is None


# --------------------------------------------------------------------------- #
# choosing the command
# --------------------------------------------------------------------------- #


def test_a_uv_tool_is_upgraded_by_uv(monkeypatch):
    monkeypatch.setattr("comodor.update.find_tool", lambda name: f"/opt/{name}")

    step = plan(Installation("uv", Path("/x/uv/tools/comodor"), "installed as a uv tool"))

    assert step.command == ["/opt/uv", "tool", "upgrade", "comodor"]
    assert not step.blocked


def test_a_pipx_install_is_upgraded_by_pipx(monkeypatch):
    monkeypatch.setattr("comodor.update.find_tool", lambda name: f"/opt/{name}")

    step = plan(Installation("pipx", Path("/x/pipx/venvs/comodor"), ""))

    assert step.command == ["/opt/pipx", "upgrade", "comodor"]


def test_a_plain_install_is_upgraded_by_pip():
    step = plan(Installation("pip", None, "installed with pip"))

    assert step.command[1:] == ["-m", "pip", "install", "--upgrade", "comodor"]


def test_the_installers_environment_is_upgraded_through_its_own_python(tmp_path):
    environment = tmp_path / "venv"
    (environment / "bin").mkdir(parents=True)
    (environment / "bin" / "python").write_text("", encoding="utf-8")

    step = plan(Installation("venv", environment, "the environment the installer built"))

    assert step.command[1:] == ["-m", "pip", "install", "--upgrade", "comodor"]
    assert "pip" in " ".join(step.command)


def test_a_source_checkout_is_refused_and_told_why():
    """Overwriting a working tree with a release throws away uncommitted work."""
    step = plan(Installation("source", None, "from a checkout"))

    assert step.command == []
    assert "git pull" in step.blocked


def test_a_tool_manager_that_has_gone_is_reported_rather_than_guessed_around(
        monkeypatch):
    """Falling back to pip here would corrupt uv's record of what it manages."""
    monkeypatch.setattr("comodor.update.find_tool", lambda name: None)

    step = plan(Installation("uv", Path("/x/uv/tools/comodor"), ""))

    assert step.command == []
    assert "uv" in step.blocked


def test_a_blocked_plan_never_runs_anything():
    ok, message = apply(plan(Installation("source", None, "")))

    assert not ok
    assert "git pull" in message


# --------------------------------------------------------------------------- #
# running it
# --------------------------------------------------------------------------- #


class FakeCompleted:
    def __init__(self, code: int, out: str = "", err: str = "") -> None:
        self.returncode = code
        self.stdout = out
        self.stderr = err


@pytest.fixture
def posix(monkeypatch):
    """Run the upgrade in this process, which is what every platform but one does."""
    monkeypatch.setattr("comodor.update.sys.platform", "linux")


def test_a_successful_upgrade_says_nothing_and_means_it(posix, monkeypatch):
    monkeypatch.setattr("comodor.update.subprocess.run",
                        lambda *a, **k: FakeCompleted(0, "Successfully installed"))

    ok, message = apply(plan(Installation("pip", None, "")))

    assert ok
    assert message == ""


def test_a_failed_upgrade_comes_back_with_the_reason(posix, monkeypatch):
    monkeypatch.setattr(
        "comodor.update.subprocess.run",
        lambda *a, **k: FakeCompleted(1, "", "ERROR: no matching distribution"))

    ok, message = apply(plan(Installation("pip", None, "")))

    assert not ok
    assert "no matching distribution" in message


def test_on_windows_the_upgrade_is_handed_to_something_that_outlives_us(
        monkeypatch):
    """A running program cannot replace its own executable there."""
    monkeypatch.setattr("comodor.update.sys.platform", "win32")
    scheduled: list[list[str]] = []
    monkeypatch.setattr("comodor.update._schedule", scheduled.append)

    step = plan(Installation("pip", None, ""))
    ok, message = apply(step)

    assert step.deferred
    assert ok
    assert scheduled and "pip" in " ".join(scheduled[0])
    # Reported as started, because nothing here can see how it ends.
    assert "finishes once this one exits" in message


# --------------------------------------------------------------------------- #
# confirming it actually moved
# --------------------------------------------------------------------------- #


def test_the_version_is_asked_for_rather_than_assumed(posix, monkeypatch):
    monkeypatch.setattr("comodor.update.subprocess.run",
                        lambda *a, **k: FakeCompleted(0))
    monkeypatch.setattr("comodor.update.installed_version", lambda *a: "0.3.0")

    outcome = upgrade(plan(Installation("pip", None, "")), "0.3.0")

    assert outcome.ok
    assert outcome.version == "0.3.0"
    assert not outcome.forced


def test_a_pinned_tool_reports_success_and_moves_nothing(posix, monkeypatch):
    """`uv tool upgrade` honours the requirement recorded at install time.

    Installed as `comodor==0.2.3`, the tool is already at the newest version it
    is allowed to have, and uv says so by exiting zero. Taking that at its word
    is how somebody stays three releases behind while being told they are up to
    date — found by doing exactly this to a real installation.
    """
    monkeypatch.setattr("comodor.update.find_tool", lambda name: f"/opt/{name}")
    ran: list[list[str]] = []

    def record(command, **_):
        ran.append(command)
        return FakeCompleted(0)

    monkeypatch.setattr("comodor.update.subprocess.run", record)
    # Unmoved after the first command, moved after the second.
    answers = iter(["0.2.3", "0.3.0"])
    monkeypatch.setattr("comodor.update.installed_version",
                        lambda *a: next(answers))

    outcome = upgrade(plan(Installation("uv", Path("/x"), "")), "0.3.0")

    assert outcome.ok
    assert outcome.version == "0.3.0"
    assert outcome.forced                       # so the report can say why
    assert ran[0] == ["/opt/uv", "tool", "upgrade", "comodor"]
    assert ran[1] == ["/opt/uv", "tool", "install", "--force", "comodor"]


def test_a_version_that_will_not_move_at_all_is_a_failure(posix, monkeypatch):
    monkeypatch.setattr("comodor.update.find_tool", lambda name: f"/opt/{name}")
    monkeypatch.setattr("comodor.update.subprocess.run",
                        lambda *a, **k: FakeCompleted(0))
    monkeypatch.setattr("comodor.update.installed_version", lambda *a: "0.2.3")

    outcome = upgrade(plan(Installation("uv", Path("/x"), "")), "0.3.0")

    assert not outcome.ok
    assert "still reports 0.2.3" in outcome.message
    assert "earlier on your PATH" in outcome.message


def test_pip_needs_no_second_attempt(posix, monkeypatch):
    """`pip install --upgrade` always goes to the newest; there is no pin to beat."""
    step = plan(Installation("pip", None, ""))

    assert step.fallback == []
