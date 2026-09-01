"""Evidence that the agent is actually improving.

"Gets better over time" is the sort of claim every tool makes and none of them
support. This module exists so Comodor can support it: every finished task
records how many steps it took, how often it had to ask, how many corrections
followed, and what it cost. Comparing the first stretch of tasks against the
most recent turns that into a number.

The measures are deliberately the ones a user feels rather than the ones that
flatter the tool. Fewer steps means less waiting. Fewer corrections means the
output needed less fixing. Fewer approvals means it stopped asking about things
you had already approved. If those do not move, the learning is not working, and
this panel will say so.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .store import Episode

SPARK = "▁▂▃▄▅▆▇█"
SPARK_ASCII = ".:-=+*#%"
MIN_FOR_TREND = 6            # below this, a "trend" is just noise
# A count metric has to have started above this to headline a claim; a fall from
# 0.4 to 0 is a real 100% but not a real improvement.
MEANINGFUL_BASE = 1.0


@dataclass
class Series:
    """One measured quantity over time."""

    key: str
    label: str
    values: list[float] = field(default_factory=list)
    lower_is_better: bool = True
    unit: str = ""

    @property
    def current(self) -> float:
        return self.values[-1] if self.values else 0.0

    def window(self, fraction: float = 0.3) -> tuple[float, float]:
        """Mean of the earliest and latest slices, for a first-versus-now delta."""
        if len(self.values) < MIN_FOR_TREND:
            return 0.0, 0.0
        size = max(2, int(len(self.values) * fraction))
        early = self.values[:size]
        late = self.values[-size:]
        return sum(early) / len(early), sum(late) / len(late)

    @property
    def change(self) -> float:
        """Relative change from the early window to the late one, in percent."""
        early, late = self.window()
        if early <= 0:
            return 0.0
        return (late - early) / early * 100.0

    @property
    def improving(self) -> bool | None:
        """True, False, or None when there is not enough evidence yet."""
        if len(self.values) < MIN_FOR_TREND:
            return None
        delta = self.change
        if abs(delta) < 5.0:
            return None                       # flat is not a direction
        return delta < 0 if self.lower_is_better else delta > 0

    def sparkline(self, width: int = 24, ascii_only: bool = False) -> str:
        """A compact plot of the series, bucketed to fit the width available."""
        glyphs = SPARK_ASCII if ascii_only else SPARK
        if not self.values:
            return ""
        points = _bucket(self.values, width)
        low, high = min(points), max(points)
        if high - low < 1e-9:
            return glyphs[len(glyphs) // 2] * len(points)
        span = high - low
        return "".join(
            glyphs[min(len(glyphs) - 1, int((value - low) / span * len(glyphs)))]
            for value in points
        )


def _bucket(values: list[float], width: int) -> list[float]:
    """Average values into at most ``width`` buckets."""
    if len(values) <= width:
        return list(values)
    size = len(values) / width
    buckets: list[float] = []
    for index in range(width):
        start = int(index * size)
        end = max(start + 1, int((index + 1) * size))
        chunk = values[start:end]
        buckets.append(sum(chunk) / len(chunk))
    return buckets


@dataclass
class Progress:
    """Everything the dashboard shows."""

    episodes: int = 0
    series: list[Series] = field(default_factory=list)
    success_rate: float = 0.0
    early_success_rate: float = 0.0
    rules_active: int = 0
    lessons: int = 0
    facts: int = 0
    corrections_total: int = 0
    since: float = 0.0
    days: float = 0.0

    @property
    def enough_data(self) -> bool:
        return self.episodes >= MIN_FOR_TREND

    def get(self, key: str) -> Series | None:
        return next((series for series in self.series if series.key == key), None)

    def headline(self) -> str:
        """One sentence a user could screenshot, or an honest 'not yet'.

        Candidates are considered in the order a user actually feels them, and
        a metric is only allowed to lead if it started from a base worth
        talking about. "Tool errors down 100%" sounds impressive and means
        almost nothing when the early average was 0.4 per task.
        """
        if not self.enough_data:
            remaining = MIN_FOR_TREND - self.episodes
            return (f"{self.episodes} task{'s' if self.episodes != 1 else ''} recorded — "
                    f"{remaining} more before a trend means anything.")

        for key in ("steps", "corrections", "tokens", "approvals", "retries", "success"):
            series = self.get(key)
            if series is None or series.improving is not True:
                continue
            early, _ = series.window()
            if key != "success" and early < MEANINGFUL_BASE:
                continue
            direction = "down" if series.lower_is_better else "up"
            return (f"{series.label} {direction} {abs(series.change):.0f}% "
                    f"since the first tasks in this project.")

        return "No measurable change yet. The numbers below are the honest ones."


def analyse(episodes: list[Episode], lessons: int = 0,
            rules_active: int = 0, facts: int = 0) -> Progress:
    """Turn stored episodes into the series behind the dashboard."""
    usable = [episode for episode in episodes if episode.stopped != "cancelled"]
    progress = Progress(episodes=len(usable), lessons=lessons,
                        rules_active=rules_active, facts=facts)
    if not usable:
        return progress

    progress.since = usable[0].created_at
    progress.days = max(0.0, (time.time() - progress.since) / 86400.0)
    progress.corrections_total = sum(episode.corrections for episode in usable)

    successes = [1.0 if episode.success else 0.0 for episode in usable]
    progress.success_rate = sum(successes) / len(successes)
    early = successes[: max(2, int(len(successes) * 0.3))]
    progress.early_success_rate = sum(early) / len(early)

    progress.series = [
        Series("steps", "Steps per task",
               [float(episode.steps) for episode in usable], unit=""),
        Series("corrections", "Corrections per task",
               [float(episode.corrections) for episode in usable]),
        Series("approvals", "Approvals asked",
               [float(episode.approvals_asked) for episode in usable]),
        Series("retries", "Tool errors per task",
               [float(episode.retries) for episode in usable]),
        Series("tokens", "Tokens per task",
               [float(episode.tokens) for episode in usable]),
        Series("success", "First-try success", successes, lower_is_better=False),
    ]
    # A series that is zero throughout says nothing; leave it out rather than
    # pad the panel with flat lines.
    progress.series = [series for series in progress.series if any(series.values)]
    return progress
