"""Taking it back off the machine.

The dangerous half of this feature is not the deleting, it is the deciding:
which of these files are Comodor's, and which belong to the person whose home
directory they are sitting in. So most of what is tested here is restraint —
the profile line left alone because another program needs the directory, the
source checkout left alone because it is not ours, the block removed from a
shell profile without taking a neighbouring line with it.

Nothing here runs the real uninstaller against the real machine, and that is
enforced rather than intended. `survey()` reaches for the home directory, the
launcher directory and `sys.prefix` on its own, so a test that only redirects
the config is still pointed at whoever is running it — and `apply()` deletes
what `survey()` found. The autouse fixture below moves all three somewhere
temporary before any test runs.

It is not a hypothetical: without it, this file deleted the `comodor` command
off the machine running it, and the continuous integration job that installs
Comodor and then checks it starts failed with "command not found".
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from comodor.config import Config
from comodor.paths import Paths
from comodor.uninstall import (
    PROFILE_MARKER,
    Installation,
    Survey,
    apply,
    detect_installation,
    profile_edits,
    project_directories,
    strip_profile,
    survey,
)


@pytest.fixture(autouse=True)
def nowhere_near_the_real_machine(tmp_path, monkeypatch):
    """Point every path this module can reach at the temporary tree."""
    home = tmp_path / "elsewhere"
    (home / ".local" / "bin").mkdir(parents=True)

    monkeypatch.delenv("COMODOR_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr("comodor.uninstall.BIN_DIR", home / ".local" / "bin")
    # Found by scanning real directories, including sys.prefix. A test that
    # wants launchers says so.
    monkeypatch.setattr("comodor.uninstall._launchers", list)
    # Nothing here may spawn the detached Windows deleter.
    monkeypatch.setattr("comodor.uninstall._schedule",
                        lambda paths: (_ for _ in ()).throw(
                            AssertionError(f"a test tried to schedule {paths}")))
    return home


def make_config(tmp_path: Path) -> Config:
    """A config whose data root and project root are both temporary."""
    user = tmp_path / "data"
    project = tmp_path / "project"
    (user / "logs").mkdir(parents=True)
    project.mkdir(parents=True)
    return Config(paths=Paths(user=user, project=project))


def furnish(user: Path) -> None:
    """A data directory that looks like one that has been used."""
    (user / "config.json").write_text('{"provider": "x"}', encoding="utf-8")
    (user / "brain.db").write_bytes(b"0" * 4096)
    (user / "skills").mkdir(exist_ok=True)
    (user / "skills" / "review.md").write_text("# review", encoding="utf-8")
    (user / "sessions").mkdir(exist_ok=True)


def record_session(user: Path, session_id: str, cwd: Path) -> None:
    sessions = user / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / f"{session_id}.jsonl").write_text("", encoding="utf-8")
    (sessions / f"{session_id}.meta.json").write_text(
        json.dumps({"id": session_id, "cwd": str(cwd)}), encoding="utf-8")


# --------------------------------------------------------------------------- #
# what it finds
# --------------------------------------------------------------------------- #


def test_the_data_directory_is_found_with_what_is_in_it(tmp_path):
    config = make_config(tmp_path)
    furnish(config.paths.user)

    found = survey(config)
    data = [item for item in found.items if item.kind == "data"]

    assert len(data) == 1
    assert data[0].path == config.paths.user
    assert data[0].size >= 4096
    # The report has to name the things a person would regret losing.
    assert "API key" in data[0].detail
    assert "1 skill" in data[0].detail


def test_a_machine_it_was_never_installed_on_offers_nothing_to_delete(tmp_path):
    config = make_config(tmp_path)
    # No data directory at all.
    (config.paths.user / "logs").rmdir()
    config.paths.user.rmdir()

    found = survey(config)

    assert not [item for item in found.items if item.kind == "data"]
    assert any("no data directory" in note for note in found.notes)


def test_projects_come_from_the_sessions_rather_than_from_a_disk_walk(tmp_path):
    """A `.comodor` folder is only found because a session says it was used."""
    config = make_config(tmp_path)
    used = tmp_path / "used"
    (used / ".comodor" / "checkpoints").mkdir(parents=True)
    unused = tmp_path / "unused"
    (unused / ".comodor").mkdir(parents=True)

    record_session(config.paths.user, "20260101-000000", used)

    directories, had_history = project_directories(config.paths.user)

    assert had_history
    assert used / ".comodor" in directories
    # Never used from there, so nothing claims it. Walking the disk would have
    # picked it up and deleted somebody else's folder.
    assert unused / ".comodor" not in directories


def test_the_project_you_are_standing_in_counts_even_with_no_session(tmp_path):
    config = make_config(tmp_path)
    here = tmp_path / "here"
    (here / ".comodor").mkdir(parents=True)

    directories, _ = project_directories(config.paths.user, here)

    assert directories == [here / ".comodor"]


def test_a_missing_session_history_is_reported_as_a_gap(tmp_path):
    """Silence and "none" are different answers, and must read differently."""
    config = make_config(tmp_path)
    furnish(config.paths.user)
    (config.paths.user / "sessions").rmdir()

    found = survey(config)

    assert any("cannot be named here" in note for note in found.notes)


# --------------------------------------------------------------------------- #
# the shell profile
# --------------------------------------------------------------------------- #


def test_only_the_installers_own_block_leaves_the_profile(tmp_path):
    profile = tmp_path / ".bashrc"
    profile.write_text(
        "export EDITOR=vim\n"
        "\n"
        f"{PROFILE_MARKER}\n"
        'export PATH="/home/x/.local/bin:$PATH"\n'
        "\n"
        "alias ll='ls -l'\n",
        encoding="utf-8",
    )

    strip_profile(profile)
    text = profile.read_text(encoding="utf-8")

    assert PROFILE_MARKER not in text
    assert ".local/bin" not in text
    # Everything that was not ours is still exactly where it was.
    assert "export EDITOR=vim" in text
    assert "alias ll='ls -l'" in text


def test_a_profile_without_the_marker_is_not_touched(tmp_path, monkeypatch):
    (Path.home() / ".bashrc").write_text(
        'export PATH="/home/x/.local/bin:$PATH"\n', encoding="utf-8")

    # The directory is named, but nothing says the installer put it there, so
    # the line is somebody else's.
    assert profile_edits(Path("/home/x/.local/bin")) == []


def test_a_shared_bin_directory_keeps_its_place_on_path(tmp_path, monkeypatch):
    """The line is ours; the directory is not."""
    home = Path.home()
    bin_dir = home / ".local" / "bin"
    (bin_dir / "comodor").write_text("#!/bin/sh\n", encoding="utf-8")
    (bin_dir / "ruff").write_text("#!/bin/sh\n", encoding="utf-8")
    (home / ".bashrc").write_text(
        f"{PROFILE_MARKER}\nexport PATH=\"{bin_dir}:$PATH\"\n", encoding="utf-8")

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr("comodor.uninstall.BIN_DIR", bin_dir)

    config = make_config(tmp_path)
    furnish(config.paths.user)
    found = survey(config)

    assert not [item for item in found.items if item.kind == "path"]
    # Named, so the reader can judge whether the line is worth keeping.
    assert any("ruff" in note for note in found.notes)


def test_a_directory_that_was_only_ours_gives_the_path_line_back(tmp_path,
                                                                 monkeypatch):
    monkeypatch.delenv("COMODOR_HOME", raising=False)
    home = tmp_path / "home"
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "comodor").write_text("#!/bin/sh\n", encoding="utf-8")
    (home / ".bashrc").write_text(
        f"{PROFILE_MARKER}\nexport PATH=\"{bin_dir}:$PATH\"\n", encoding="utf-8")

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr("comodor.uninstall.BIN_DIR", bin_dir)

    config = make_config(tmp_path)
    furnish(config.paths.user)
    found = survey(config)

    assert [item.path for item in found.items if item.kind == "path"] \
        == [home / ".bashrc"]


# --------------------------------------------------------------------------- #
# how it was installed
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("prefix, expected", [
    ("/home/x/.local/pipx/venvs/comodor", "pipx"),
    ("/home/x/.local/share/uv/tools/comodor", "uv"),
])
def test_the_install_method_is_read_from_the_prefix(prefix, expected, monkeypatch):
    """A tool that manages its own environments has to be asked to remove it.

    Deleting a pipx or uv environment behind their backs leaves them with an
    entry for a thing that is not there any more.
    """
    monkeypatch.setattr("sys.prefix", prefix)
    assert detect_installation().method == expected


def test_a_source_checkout_is_never_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr("comodor.uninstall.detect_installation",
                        lambda: Installation("source", None, "from a checkout"))
    config = make_config(tmp_path)
    furnish(config.paths.user)

    found = survey(config)

    assert not [item for item in found.items if item.kind == "program"]
    assert any("left alone" in note for note in found.notes)


# --------------------------------------------------------------------------- #
# doing it
# --------------------------------------------------------------------------- #


def test_everything_it_listed_is_gone_afterwards(tmp_path, monkeypatch):
    monkeypatch.setattr("comodor.uninstall.detect_installation",
                        lambda: Installation("source", None, "from a checkout"))
    config = make_config(tmp_path)
    furnish(config.paths.user)
    used = tmp_path / "used"
    (used / ".comodor" / "checkpoints").mkdir(parents=True)
    record_session(config.paths.user, "20260101-000000", used)

    found = apply(survey(config))

    assert not found.failed
    assert not config.paths.user.exists()
    assert not (used / ".comodor").exists()
    # The project itself is not ours; only the folder inside it was.
    assert used.exists()


def test_the_command_itself_goes_too(tmp_path, monkeypatch):
    """Whatever else survives, `comodor` must stop being a word that works."""
    launcher = Path.home() / ".local" / "bin" / "comodor"
    launcher.write_text("#!/bin/sh", encoding="utf-8")
    monkeypatch.setattr("comodor.uninstall._launchers", lambda: [launcher])
    monkeypatch.setattr("comodor.uninstall.detect_installation",
                        lambda: Installation("source", None, "from a checkout"))

    config = make_config(tmp_path)
    furnish(config.paths.user)
    found = apply(survey(config))

    assert not found.failed
    assert not launcher.exists()


def test_a_tool_manager_off_the_path_is_still_found(tmp_path, monkeypatch):
    """`curl | sh` bootstraps uv into ~/.local/bin and never reads a profile.

    So the shell that installed Comodor frequently has uv installed and not on
    PATH at the same time, and `shutil.which` says it is not there at all.
    """
    from comodor.uninstall import find_tool

    tool = Path.home() / ".local" / "bin" / ("uv.exe" if os.name == "nt" else "uv")
    tool.write_text("#!/bin/sh", encoding="utf-8")
    monkeypatch.setattr("comodor.uninstall.TOOL_DIRS", (tool.parent,))
    monkeypatch.setattr("shutil.which", lambda name: None)

    assert find_tool("uv") == str(tool)
    assert find_tool("pipx") is None


def test_a_missing_tool_manager_does_not_leave_the_environment_behind(tmp_path,
                                                                     monkeypatch):
    """Reported honestly and left on disk is still left on disk.

    Deleting it directly leaves uv with an entry for something that is gone.
    Seventy megabytes of environment is the worse of the two.
    """
    from comodor.uninstall import _run_uninstaller

    environment = tmp_path / "uv" / "tools" / "comodor"
    (environment / "bin").mkdir(parents=True)
    monkeypatch.setattr("comodor.uninstall.find_tool", lambda name: None)

    outcome = _run_uninstaller("uv", environment)

    assert not environment.exists()
    assert "removed directly" in outcome


def test_a_removal_that_fails_is_reported_rather_than_raised(tmp_path):
    """One thing that will not go must not stop the rest from going."""
    def explode() -> str:
        raise PermissionError("in use by another process")

    from comodor.uninstall import Item

    found = Survey(items=[
        Item(kind="data", label="the data", path=tmp_path / "gone", remove=explode),
    ])

    apply(found)

    assert found.removed == []
    assert len(found.failed) == 1
    assert "in use by another process" in found.failed[0]


def test_the_program_is_removed_last(tmp_path, monkeypatch):
    """If it stops halfway, what survives is the thing that can finish the job."""
    from comodor.uninstall import Item

    order: list[str] = []

    def note(kind: str):
        def remove() -> str:
            order.append(kind)
            return kind
        return remove

    found = Survey(items=[
        Item(kind="program", label="p", remove=note("program")),
        Item(kind="data", label="d", remove=note("data")),
        Item(kind="launcher", label="l", remove=note("launcher")),
        Item(kind="project", label="j", remove=note("project")),
    ])

    apply(found)

    assert order == ["data", "project", "launcher", "program"]


def test_the_data_directory_is_not_also_listed_as_a_project(tmp_path):
    """Run the agent in your home folder - which people do - and the project
    root resolves to it, so `~/.comodor` is both the data directory and the
    project's. It was listed twice on the screen that asks whether to delete
    it, and counted twice in the total, which is the one screen where an
    inflated number does the most harm."""
    root = tmp_path / ".comodor"
    root.mkdir()
    (root / "config.json").write_text("{}", encoding="utf-8")

    directories, _ = project_directories(root, tmp_path)

    assert directories == []


def test_a_real_project_is_still_listed(tmp_path):
    root = tmp_path / ".comodor"
    root.mkdir()
    project = tmp_path / "work"
    (project / ".comodor").mkdir(parents=True)

    directories, _ = project_directories(root, project)

    assert directories == [project / ".comodor"]
