"""The /progress dashboard, and the honesty rules it is built on.

A panel whose job is to say "look how much better this got" is exactly the place
where a tool is tempted to flatter itself. These tests pin down the opposite
behaviour: not enough data says so, no movement says so, and a rate is reported
in points rather than as a percentage of a percentage.
"""

from __future__ import annotations

import io
import time

import pytest
from rich.console import Console

from comodor.learning.progress import Series, analyse
from comodor.learning.store import Episode
from comodor.ui import theme as theme_module
from comodor.ui.widgets.progress import render_progress


def episodes(count: int, *, steps=None, corrections=None, success=True,
             tokens=None, approvals=None) -> list[Episode]:
    now = time.time()
    made = []
    for index in range(count):
        made.append(Episode(
            steps=steps(index) if callable(steps) else (steps or 5),
            corrections=corrections(index) if callable(corrections) else (corrections or 0),
            approvals_asked=approvals(index) if callable(approvals) else (approvals or 0),
            tokens=tokens(index) if callable(tokens) else (tokens or 1000),
            success=success(index) if callable(success) else success,
            created_at=now - (count - index) * 3600,
        ))
    return made


# --------------------------------------------------------------------------- #
# series maths
# --------------------------------------------------------------------------- #


def test_a_falling_metric_reads_as_improvement():
    series = Series("steps", "Steps", [10.0] * 5 + [4.0] * 5)
    assert series.improving is True
    assert series.change < 0


def test_a_rising_cost_reads_as_regression():
    series = Series("tokens", "Tokens", [1000.0] * 5 + [3000.0] * 5)
    assert series.improving is False


def test_a_flat_metric_claims_nothing():
    series = Series("steps", "Steps", [5.0, 5.1, 4.9, 5.0, 5.05, 5.0])
    assert series.improving is None, "noise is not a trend"


def test_too_little_history_claims_nothing():
    series = Series("steps", "Steps", [9.0, 3.0])
    assert series.improving is None


def test_sparkline_fits_the_width_it_is_given():
    series = Series("steps", "Steps", [float(i) for i in range(200)])
    assert len(series.sparkline(width=20)) == 20
    assert len(series.sparkline(width=8)) == 8


def test_sparkline_has_an_ascii_form():
    series = Series("steps", "Steps", [1.0, 5.0, 3.0, 9.0, 2.0, 7.0])
    spark = series.sparkline(width=6, ascii_only=True)
    assert spark.isascii() and len(spark) == 6


# --------------------------------------------------------------------------- #
# the headline
# --------------------------------------------------------------------------- #


def test_a_new_project_says_it_needs_more_data():
    progress = analyse(episodes(2))
    assert not progress.enough_data
    assert "before a trend means anything" in progress.headline()


def test_a_real_improvement_is_stated_plainly():
    progress = analyse(episodes(30, steps=lambda i: max(2, 12 - i // 3)))
    assert "Steps per task down" in progress.headline()


def test_no_movement_is_admitted_rather_than_dressed_up():
    progress = analyse(episodes(30, steps=5, tokens=1000))
    assert "No measurable change" in progress.headline()


def test_a_drop_from_almost_nothing_does_not_headline():
    """"Tool errors down 100%" from an average of 0.4 is not an achievement."""
    progress = analyse(episodes(
        30,
        steps=5,                                     # flat, so it cannot lead
        corrections=lambda i: 1 if i < 4 else 0,     # tiny base, drops to zero
    ))
    headline = progress.headline()
    assert "Corrections" not in headline
    assert "No measurable change" in headline


def test_getting_worse_is_not_reported_as_progress():
    progress = analyse(episodes(30, steps=lambda i: 3 + i // 3))
    assert "No measurable change" in progress.headline()
    assert progress.get("steps").improving is False


# --------------------------------------------------------------------------- #
# analysis
# --------------------------------------------------------------------------- #


def test_cancelled_tasks_are_left_out():
    made = episodes(10)
    made[0].stopped = "cancelled"
    assert analyse(made).episodes == 9


def test_metrics_that_are_always_zero_are_omitted():
    progress = analyse(episodes(10, corrections=0, approvals=0))
    keys = {series.key for series in progress.series}
    assert "corrections" not in keys
    assert "steps" in keys


def test_success_rate_is_measured_against_the_early_window():
    progress = analyse(episodes(20, success=lambda i: i >= 8))
    assert progress.success_rate == pytest.approx(0.6)
    assert progress.early_success_rate == 0.0


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #


def render(progress, width: int = 90, ascii_only: bool = False) -> str:
    import re

    theme = theme_module.load("ember", ascii_borders=ascii_only)
    buffer = io.StringIO()
    console = Console(file=buffer, width=width, force_terminal=True,
                      color_system="truecolor", legacy_windows=False,
                      theme=theme.rich_theme())
    console.print(render_progress(progress, theme, width=width))
    return re.sub(r"\x1b\[[0-9;]*m", "", buffer.getvalue())


def test_the_dashboard_shows_its_numbers():
    text = render(analyse(episodes(30, steps=lambda i: max(2, 12 - i // 3)),
                          lessons=12, rules_active=4))

    assert "Steps per task" in text
    assert "12 lessons" in text
    assert "4 rules" in text
    assert "30 tasks" in text


def test_a_rate_is_reported_in_points_not_percent():
    text = render(analyse(episodes(30, success=lambda i: i >= 6)))
    assert "pp" in text, "a success rate must move in percentage points"


@pytest.mark.parametrize("width", [50, 70, 90, 120, 200])
def test_the_dashboard_fits_the_width_it_is_given(width):
    text = render(analyse(episodes(30, steps=lambda i: max(2, 12 - i // 3))), width)
    for line in text.splitlines():
        assert len(line) <= width


def test_the_dashboard_renders_without_unicode():
    text = render(analyse(episodes(30, steps=lambda i: max(2, 12 - i // 3))),
                  ascii_only=True)
    assert text.isascii()


def test_an_empty_brain_still_renders():
    text = render(analyse([]))
    assert "0 tasks" in text
