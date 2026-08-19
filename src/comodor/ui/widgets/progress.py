"""The /progress panel.

The one screen in Comodor whose job is to be looked at rather than used. It
answers a question no other agent lets you ask: *is this thing actually getting
better, or does it just claim to?*

It is built to be honest, which is what makes it worth showing. When there is
not enough history it says so instead of drawing a flattering line, and a metric
that has not moved is reported as unchanged rather than dressed up.
"""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from ...learning.progress import Progress, Series
from ..theme import Theme


def render_progress(progress: Progress, theme: Theme, width: int = 90) -> RenderableType:
    """The whole dashboard, sized to the overlay it sits in."""
    blocks: list[RenderableType] = [_headline(progress, theme), Text("")]

    if progress.series:
        blocks.append(_table(progress, theme, width))
        blocks.append(Text(""))

    blocks.append(_summary(progress, theme))
    return Group(*blocks)


def _headline(progress: Progress, theme: Theme) -> Text:
    text = Text()
    if not progress.enough_data:
        text.append(progress.headline(), style=theme.style("dim"))
        return text
    text.append(f"{theme.glyphs.memory} ", style=theme.style("accent"))
    text.append(progress.headline(), style=theme.style("good", bold=True))
    return text


def _table(progress: Progress, theme: Theme, width: int) -> RenderableType:
    spark_width = max(12, min(30, width - 52))
    table = Table.grid(padding=(0, 2))
    table.add_column("metric", no_wrap=True)
    table.add_column("spark", no_wrap=True)
    table.add_column("now", justify="right", no_wrap=True)
    table.add_column("change", justify="right", no_wrap=True)

    table.add_row(
        Text("metric", style=theme.style("label")),
        Text("trend", style=theme.style("label")),
        Text("now", style=theme.style("label")),
        Text("vs first", style=theme.style("label")),
    )

    for series in progress.series:
        table.add_row(
            Text(series.label, style=theme.style("value")),
            Text(series.sparkline(spark_width, ascii_only=theme.ascii),
                 style=_trend_style(series, theme)),
            Text(_format(series), style=theme.style("value")),
            _change(series, theme),
        )
    return table


def _trend_style(series: Series, theme: Theme):
    improving = series.improving
    if improving is None:
        return theme.style("dim")
    return theme.style("good" if improving else "warn")


def _format(series: Series) -> str:
    _, late = series.window()
    value = late or series.current
    if series.key == "success":
        return f"{value:.0%}"
    if series.key == "tokens":
        return f"{value / 1000:.1f}K" if value >= 1000 else f"{value:.0f}"
    return f"{value:.1f}"


def _change(series: Series, theme: Theme) -> Text:
    improving = series.improving
    if improving is None:
        return Text(theme.glyphs.dash, style=theme.style("dim"))

    if series.key == "success":
        # A rate moves in percentage points. Reporting a jump from 80% to 88%
        # as "up 10%" is the kind of shading that makes a dashboard untrusted.
        early, late = series.window()
        points = (late - early) * 100
        arrow = theme.glyphs.rise if points > 0 else theme.glyphs.fall
        return Text(f"{arrow}{abs(points):.0f}pp",
                    style=theme.style("good" if improving else "warn"))

    delta = series.change
    arrow = theme.glyphs.fall if delta < 0 else theme.glyphs.rise
    return Text(f"{arrow}{abs(delta):.0f}%",
                style=theme.style("good" if improving else "warn"))


def _summary(progress: Progress, theme: Theme) -> RenderableType:
    rows: list[Text] = []

    line = Text()
    line.append("brain  ", style=theme.style("label"))
    line.append(f"{progress.rules_active} rules", style=theme.style("value"))
    line.append(f" {theme.glyphs.dot} ", style=theme.style("dim"))
    line.append(f"{progress.lessons} lessons", style=theme.style("value"))
    line.append(f" {theme.glyphs.dot} ", style=theme.style("dim"))
    line.append(f"{progress.corrections_total} corrections learned from",
                style=theme.style("value"))
    rows.append(line)

    period = Text()
    period.append("history  ", style=theme.style("label"))
    period.append(f"{progress.episodes} tasks", style=theme.style("value"))
    if progress.days >= 1:
        period.append(f" over {progress.days:.0f} days", style=theme.style("dim"))
    rows.append(period)

    if progress.enough_data:
        success = Text()
        success.append("success  ", style=theme.style("label"))
        success.append(f"{progress.success_rate:.0%} overall",
                       style=theme.style("value"))
        delta = (progress.success_rate - progress.early_success_rate) * 100
        if abs(delta) >= 5:
            success.append(f"  ({'+' if delta > 0 else ''}{delta:.0f} points "
                           f"since the first tasks)",
                           style=theme.style("good" if delta > 0 else "warn"))
        rows.append(success)

    rows.append(Text(""))
    rows.append(Text(f"Reflex learns from corrections, undos and refusals "
                     f"{theme.glyphs.dash} no model call, no tokens.",
                     style=theme.style("dim")))
    return Group(*rows)
