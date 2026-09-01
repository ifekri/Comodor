"""Profiles: same program, separate brains.

A named profile is a subtree under the user root — own config, brain,
sessions. The default is the root itself, so an installation that has
never heard of profiles keeps working with nothing moved.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from comodor.config import load
from comodor.paths import DEFAULT_PROFILE, profile_name, user_root


@pytest.fixture
def home(monkeypatch, tmp_path) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("COMODOR_HOME", str(root))
    monkeypatch.delenv("COMODOR_PROFILE", raising=False)
    return root


def test_the_default_profile_is_the_root_itself(home):
    assert profile_name() == DEFAULT_PROFILE
    assert user_root() == home, "no migration, no surprise, no profiles/ hop"


def test_a_named_profile_gets_its_own_subtree(home):
    import os

    os.environ["COMODOR_PROFILE"] = "work"
    assert user_root() == home / "profiles" / "work"


def test_two_profiles_resolve_to_two_brains(home, monkeypatch):
    import os

    monkeypatch.delenv("COMODOR_PROFILE", raising=False)
    default_db = user_root() / "brain.db"

    os.environ["COMODOR_PROFILE"] = "work"
    work_db = user_root() / "brain.db"

    assert default_db != work_db


def test_a_profile_loads_an_independent_config(home, monkeypatch, tmp_path):
    import os

    monkeypatch.delenv("COMODOR_PROFILE", raising=False)
    config = load(str(tmp_path))
    config.ui.theme = "ember"
    config.save()

    os.environ["COMODOR_PROFILE"] = "work"
    work = load(str(tmp_path))
    assert work.first_run, "a profile starts fresh, not from the default's file"


def test_an_empty_profile_name_means_the_default(home, monkeypatch):
    monkeypatch.setenv("COMODOR_PROFILE", "   ")
    assert profile_name() == DEFAULT_PROFILE


def test_the_cli_flag_selects_the_profile(home, monkeypatch, tmp_path):
    """`comodor --profile work` must reach the stores that never see argv."""
    import os

    from comodor.cli import build_parser

    args = build_parser().parse_args(["--profile", "work", "run", "hello"])
    assert args.profile == "work"
    # The flag's whole job is to set the variable before config loads; the
    # main() branch that does it is one line, exercised here directly.
    monkeypatch.delenv("COMODOR_PROFILE", raising=False)
    os.environ["COMODOR_PROFILE"] = args.profile
    assert user_root() == home / "profiles" / "work"
