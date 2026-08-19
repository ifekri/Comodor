"""The status block under the sidebar, and the footer line under the prompt.

Both exist to answer questions the user would otherwise have to guess at: which
model is actually answering, how much of the context window is gone, whether the
agent is allowed to change files, and what this turn has cost. Guessing wrong
about any of those is expensive, so they are always on screen.

``Context: 1M`` is a live gauge, not a label. It shows the window size and fills
as the conversation grows, which is the earliest warning that compaction is
about to happen.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from ...agent.tokens import humanise
from ..layout import Rect
from ..theme import Theme


@dataclass
class StatusModel:
    """Everything the two status surfaces display."""

    provider: str = "—"
    model: str = "—"
    connected: bool = False
    mode: str = "act"
    loop: bool = True
    gateway: str = "Disable"
    context_used: int = 0
    context_limit: int = 1_000_000
    cost_usd: float | None = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    busy: bool = False
    activity: str = ""
    lessons: int = 0
    rules: int = 0

    @property
    def fill(self) -> float:
        if self.context_limit <= 0:
            return 0.0
        return min(1.0, self.context_used / self.context_limit)

    @property
    def status_word(self) -> str:
        if self.busy:
            return "Working"
        return "Connected" if self.connected else "Offline"


def _pair(label: str, value: str, theme: Theme, value_style: str = "value") -> Text:
    text = Text()
    text.append(label, style=theme.style("label"))
    text.append(value, style=theme.style(value_style))
    return text


def _state_style(good: bool) -> str:
    return "good" if good else "bad"


def gauge(fill: float, width: int, theme: Theme) -> Text:
    """A proportional bar that turns amber, then red, as the window fills."""
    width = max(4, width)
    filled = int(round(fill * width))
    glyphs = theme.glyphs
    tone = "good" if fill < 0.6 else ("warn" if fill < 0.85 else "bad")
    bar = Text()
    bar.append(glyphs.gauge_full * filled, style=theme.style(tone))
    bar.append(glyphs.gauge_empty * (width - filled), style=theme.style("dim"))
    return bar


def status_block(model: StatusModel, rect: Rect, theme: Theme) -> RenderableType:
    """The left-hand block: Context / GW / Mode / Loop, plus Settings."""
    inner = max(10, rect.width - 4)
    rows: list[RenderableType] = []

    context = _pair("Context:", humanise(model.context_limit), theme)
    gateway = _pair("GW: ", model.gateway, theme,
                    "good" if model.gateway.lower() != "disable" else "bad")
    mode = _pair("Mode : ", model.mode.title(), theme)
    loop = _pair("Loop : ", "On" if model.loop else "Off", theme,
                 _state_style(model.loop))

    if inner < 20:
        # Two columns here would wrap every value onto its own line anyway, and
        # a wrapped "Disable" under "GW:" reads worse than four clean rows.
        rows.extend([context, gateway, mode, loop])
    else:
        grid = Table.grid(padding=(0, 1), expand=True)
        grid.add_column(justify="left", ratio=1)
        grid.add_column(justify="left", ratio=1)
        grid.add_row(context, gateway)
        grid.add_row(mode, loop)
        rows.append(grid)

    # The gauge and the counters only appear when the panel is tall enough;
    # below that the four core facts matter more than the detail.
    if rect.height >= 7:
        rows.append(gauge(model.fill, inner, theme))
    if rect.height >= 8:
        detail = Text()
        detail.append(f"{humanise(model.context_used)} used", style=theme.style("dim"))
        if model.cost_usd is not None and model.cost_usd > 0:
            detail.append("  ", style=theme.style("dim"))
            detail.append(f"${model.cost_usd:.3f}", style=theme.style("accent"))
        # The rule count is the visible sign that Reflex is doing something,
        # so it earns a place even on a cramped panel.
        if model.rules:
            detail.append(f"  {theme.glyphs.memory}{model.rules}",
                          style=theme.style("good"))
        elif model.lessons:
            detail.append(f"  {theme.glyphs.memory}{model.lessons}",
                          style=theme.style("tool"))
        rows.append(detail)

    rows.append(settings_button(inner, theme))
    return Group(*rows)


def settings_button(width: int, theme: Theme) -> RenderableType:
    """The bordered Settings control, drawn as its own small box."""
    from rich.panel import Panel

    return Panel(
        Text("Settings", justify="center", style=theme.style("value")),
        box=theme.box,
        border_style=theme.style("border"),
        width=max(10, width),
        height=3,
        padding=(0, 0),
        expand=True,
    )


def footer_line(model: StatusModel, width: int, theme: Theme) -> Text:
    """``Provider : Openrouter | Model : Claude Fable 5 | Status : Connected``."""
    separator = Text(" | ", style=theme.style("dim"))
    text = Text()
    text.append_text(_pair("Provider : ", model.provider, theme))
    text.append_text(separator)
    text.append_text(_pair("Model : ", _fit_model(model.model, width), theme))
    text.append_text(separator)
    text.append_text(_pair(
        "Status : ", model.status_word, theme,
        "warn" if model.busy else _state_style(model.connected),
    ))

    # On a narrow terminal the whole line will not fit; drop the provider first
    # since the model name is the more useful half.
    if text.cell_len > width and width > 24:
        short = Text()
        short.append_text(_pair("Model : ", _fit_model(model.model, width - 14), theme))
        short.append_text(separator)
        short.append_text(_pair("", model.status_word, theme,
                                _state_style(model.connected)))
        return short
    return text


def _fit_model(name: str, width: int) -> str:
    """Model ids get long; keep the informative tail (`…/claude-opus-5`)."""
    budget = max(8, width // 3)
    if len(name) <= budget:
        return name
    if "/" in name:
        tail = name.split("/")[-1]
        if len(tail) <= budget:
            return tail
        name = tail
    return name[: budget - 1] + "…"


def activity_line(model: StatusModel, theme: Theme, frame: int = 0) -> Text:
    """What the agent is doing right now, with a spinner while it works."""
    if not model.busy:
        return Text("")
    glyphs = theme.glyphs
    spinner = glyphs.spinner[frame % len(glyphs.spinner)]
    text = Text()
    text.append(f"{spinner} ", style=theme.style("accent"))
    text.append(model.activity or "thinking…", style=theme.style("dim"))
    text.append("   esc to stop", style=theme.style("dim", dim=True))
    return text
