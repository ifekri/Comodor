"""Insights: the history already on disk, added up honestly.

The acceptance cases: numbers come from real session files and episodes;
a model with no published price contributes a dash, not a guess; a window
with too few sessions says so instead of showing a trend.
"""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path

import pytest

from comodor.config import Config
from comodor.insights import collect, render, to_json
from comodor.learning.store import BrainStore, Episode
from comodor.session.store import SessionMeta, SessionStore


def _config(tmp_path: Path) -> Config:
    return Config(paths=dataclasses.replace(
        Config().paths.ensure(), user=tmp_path / "home",
        project=tmp_path / "proj"))


def _session(store: SessionStore, cwd: str, model: str, cost: float,
             when: float | None = None, messages: int = 3) -> SessionMeta:
    meta = SessionMeta(id=f"s-{model}-{cost}-{time.time_ns()}",
                       cwd=cwd, model=model, cost_usd=cost,
                       messages=messages,
                       created_at=when or time.time(),
                       updated_at=when or time.time())
    store.save_meta(meta)
    return meta


def _episode(store: BrainStore, steps: int, corrections: int,
             when: float | None = None, cost: float = 0.0) -> Episode:
    return store.add_episode(Episode(
        goal="do the thing", scope="global", success=True, steps=steps,
        corrections=corrections, created_at=when or time.time(),
        cost_usd=cost))


# -- collection --------------------------------------------------------------- #

def test_it_reads_real_session_files(tmp_path):
    config = _config(tmp_path)
    sessions = SessionStore(config.paths.user / "sessions")
    _session(sessions, str(config.paths.project), "m", 2.0)
    _session(sessions, str(config.paths.project), "m", 3.0)

    result = collect(config, days=30)
    assert result.sessions == 2
    assert result.messages == 6
    assert result.cost_usd == pytest.approx(5.0)


def test_old_sessions_are_outside_the_window(tmp_path):
    config = _config(tmp_path)
    sessions = SessionStore(config.paths.user / "sessions")
    _session(sessions, str(config.paths.project), "m", 2.0)
    _session(sessions, str(config.paths.project), "m", 9.0,
             when=time.time() - 90 * 86400)

    result = collect(config, days=30)
    assert result.sessions == 1
    assert result.cost_usd == pytest.approx(2.0)


def test_an_unpriced_session_is_counted_but_its_spend_is_not_guessed(tmp_path):
    config = _config(tmp_path)
    sessions = SessionStore(config.paths.user / "sessions")
    _session(sessions, str(config.paths.project), "priced", 4.0)
    _session(sessions, str(config.paths.project), "local-model", 0.0)

    result = collect(config, days=30)
    assert result.sessions == 2
    assert result.cost_usd == pytest.approx(4.0)
    assert result.unpriced_sessions == 1
    assert not result.spend_is_whole


def test_projects_and_models_are_ranked(tmp_path):
    config = _config(tmp_path)
    sessions = SessionStore(config.paths.user / "sessions")
    _session(sessions, "/Users/x/client-site", "alpha", 5.0)
    _session(sessions, "/Users/x/scratch", "alpha", 1.0)
    _session(sessions, "/Users/x/scratch", "beta", 1.0)

    result = collect(config, days=30)
    assert result.projects[0] == ("client-site", pytest.approx(5.0))
    assert result.models[0][0] == "alpha"
    assert result.models[0][1] == pytest.approx(6.0 / 7.0)


def test_episodes_carry_the_brain_numbers(tmp_path):
    config = _config(tmp_path)
    brain = BrainStore(config.paths.brain_db)
    for steps, fixes in ((10, 3), (10, 3), (10, 3), (10, 3), (10, 3), (10, 1),
                         (10, 1), (10, 1), (10, 1), (10, 1)):
        _episode(brain, steps, fixes)

    result = collect(config, days=30)
    assert result.episodes == 10
    assert result.corrections_per_ten == pytest.approx(2.0)
    # The recent window is smaller than the whole — fewer fixes lately.
    assert result.recent_corrections_per_ten < result.corrections_per_ten
    assert result.brain_improving is True


def test_episode_cost_is_stored_and_loaded(tmp_path):
    config = _config(tmp_path)
    brain = BrainStore(config.paths.brain_db)
    _episode(brain, 10, 1, cost=0.42)

    loaded = brain.episodes(limit=5)
    assert loaded[-1].cost_usd == pytest.approx(0.42)


# -- honesty ------------------------------------------------------------------- #

def test_a_thin_window_says_so_instead_of_inventing_numbers(tmp_path):
    config = _config(tmp_path)
    sessions = SessionStore(config.paths.user / "sessions")
    _session(sessions, str(config.paths.project), "m", 2.0)

    text = render(collect(config, days=30))
    assert "Not enough sessions" in text
    assert "$2.00" not in text


def test_an_unpriced_spend_is_disclosed_in_the_view(tmp_path):
    config = _config(tmp_path)
    sessions = SessionStore(config.paths.user / "sessions")
    for _ in range(4):
        _session(sessions, str(config.paths.project), "local", 0.0)

    text = render(collect(config, days=30))
    assert "no published price" in text


def test_a_flat_brain_series_is_flat_not_improving(tmp_path):
    config = _config(tmp_path)
    brain = BrainStore(config.paths.brain_db)
    for _ in range(6):
        _episode(brain, 10, 2)

    assert collect(config, days=30).brain_improving is None


# -- surfaces ------------------------------------------------------------------ #

def test_to_json_carries_the_same_numbers(tmp_path):
    config = _config(tmp_path)
    sessions = SessionStore(config.paths.user / "sessions")
    _session(sessions, str(config.paths.project), "m", 2.5)

    payload = to_json(collect(config, days=30))
    assert payload["sessions"] == 1
    assert payload["cost_usd"] == 2.5
    assert payload["projects"][0]["name"]


def test_the_view_names_the_window(tmp_path):
    config = _config(tmp_path)
    sessions = SessionStore(config.paths.user / "sessions")
    _session(sessions, str(config.paths.project), "m", 2.0)
    _session(sessions, str(config.paths.project), "m", 2.0)
    _session(sessions, str(config.paths.project), "m", 2.0)

    text = render(collect(config, days=7))
    assert "7 days" in text
