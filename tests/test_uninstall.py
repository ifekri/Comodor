"""Taking it back off the machine.

The dangerous half of this feature is not the deleting, it is the deciding:
which of these files are Comodor's, and which belong to the person whose home
directory they are sitting in. So most of what is tested here is restraint —
the profile line left alone because another program needs the directory, the
source checkout left alone because it is not ours, the block removed from a
shell profile without taking a neighbouring line with it.

Nothing here runs the real uninstaller against the real machine. Every path is
a temporary one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from comodor.config import Config
from comodor.paths import Paths
from comodor.uninstall import (
    Installation,
    PROFILE_MARKER,
    Survey,
    apply,
    detect_installation,
    profile_edits,
    project_directories,
    strip_profile,
    survey,
)


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


def test_the_data_directory_is_found_with_what_is_in_it(tmp_path, monkeypatch):
    monkeypatch.delenv("COMODOR_HOME", raising=False)
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


def test_a_machine_it_was_never_installed_on_offers_nothing_to_delete(tmp_path,
                                                                     monkeypatch):
    monkeypatch.delenv("COMODOR_HOME", raising=False)
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


def test_a_missing_session_history_is_reported_as_a_gap(tmp_path, monkeypatch):
    """Silence and "none" are different answers, and must read differently."""
    monkeypatch.delenv("COMODOR_HOME", raising=False)
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
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / ".bashrc").write_text(
        'export PATH="/home/x/.local/bin:$PATH"\n', encoding="utf-8")

    # The directory is named, but nothing says the installer put it there, so
    # the line is somebody else's.
    assert profile_edits(Path("/home/x/.local/bin")) == []


def test_a_shared_bin_directory_keeps_its_place_on_path(tmp_path, monkeypatch):
    """The line is ours; the directory is not."""
    monkeypatch.delenv("COMODOR_HOME", raising=False)
    home = tmp_path / "home"
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
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
    assert any("stays on your PATH" in note for note in found.notes)


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
    monkeypatch.delenv("COMODOR_HOME", raising=False)
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
    monkeypatch.delenv("COMODOR_HOME", raising=False)
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
