"""The two lines that are not the conversation.

One at the top: the name, and the model actually answering. One at the bottom:
the mode, the loop, how much of the window is gone, what it has cost.

They exist to answer questions that are expensive to guess wrong about, and
they are two lines because that is all the information needs. It used to be a
bordered block of six labelled pairs beside the transcript — `Mode : Act`,
`Context:1M`, `GW: Disable` — where half the characters were the labels and
none of the information was. `act` says everything `Mode : Act` says.

The context reading is live. It fills as the conversation grows, which is the
earliest warning that compaction is about to happen.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

from ... import APP_NAME as APP
from ...agent.tokens import humanise
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


def header_line(model: StatusModel, width: int, theme: Theme) -> Text:
    """The top line: the name, and what it is talking to.

    Two facts, one at each end. The name because a terminal window with six
    tabs open needs to say which one this is, and the model because it is the
    single thing most worth knowing and the thing people most often get wrong
    about which one is answering.

    Everything else that used to be up here — the mode, the loop, the gauge,
    the cost — moved to the bottom line. None of it changes often enough to
    earn the first row.
    """
    name = Text(APP, style=theme.style("title", bold=True))

    right = Text()
    if model.provider and model.provider != "—":
        right.append(model.provider, style=theme.style("dim"))
        right.append(f" {theme.glyphs.dot} ", style=theme.style("dim", dim=True))
    right.append(_fit_model(model.model, width), style=theme.style("value"))

    # One row, always. A header that wraps pushes the rule off the top of the
    # screen and takes a line of the transcript with it.
    if name.cell_len + right.cell_len + 2 > width:
        right = Text(_fit_model(model.model, max(8, width - name.cell_len - 2)),
                     style=theme.style("value"))

    gap = max(1, width - name.cell_len - right.cell_len)
    line = Text()
    line.append_text(name)
    line.append(" " * gap)
    line.append_text(right)
    return line


def footer_line(model: StatusModel, width: int = 0, theme: Theme = None) -> Text:  # type: ignore[assignment]
    """The bottom line: where you are, and what this turn has cost.

    Written as a sentence of small facts rather than a table of labels. The
    labels were half the characters and none of the information: `Mode : Act`
    says nothing `act` does not.

    It sheds from the right as the terminal narrows, in the order the facts
    stop being worth the space — the cost first, the window size last, the mode
    never. There is no border holding a row open any more, so a line one cell
    too long does not get clipped: it wraps, and takes the whole layout down a
    row with it.
    """
    dim = theme.style("dim", dim=True)
    separator = f" {theme.glyphs.dot} "

    mode = Text(model.mode.lower(), style=theme.style("value"))
    loop = Text("loop " + ("on" if model.loop else "off"),
                style=theme.style(_state_style(model.loop)))

    fill = model.fill
    tone = "dim" if fill < 0.6 else ("warn" if fill < 0.85 else "bad")
    context = Text(f"{fill:.0%}", style=theme.style(tone))
    context.append(" of ", style=dim)
    context.append(humanise(model.context_limit), style=theme.style("dim"))

    short_context = Text(f"{fill:.0%}", style=theme.style(tone))

    # Least important last: this is the order they get dropped in.
    parts: list[Text] = [mode, loop, context]
    if model.gateway and model.gateway.lower() not in ("disable", "off", ""):
        parts.append(Text(f"gw {model.gateway.lower()}", style=theme.style("good")))
    if model.rules:
        parts.append(Text(f"{theme.glyphs.memory}{model.rules}",
                          style=theme.style("good")))
    elif model.lessons:
        parts.append(Text(f"{theme.glyphs.memory}{model.lessons}",
                          style=theme.style("tool")))
    if model.cost_usd:
        parts.append(Text(f"${model.cost_usd:.3f}", style=theme.style("accent")))

    if width <= 0:
        return _join(parts, separator, dim)

    while len(parts) > 1 and _joined_len(parts, len(separator)) > width:
        parts.pop()
    if len(parts) == 3 and _joined_len(parts, len(separator)) > width:
        parts[2] = short_context
    while len(parts) > 1 and _joined_len(parts, len(separator)) > width:
        parts.pop()

    return _join(parts, separator, dim)


def _joined_len(parts: list[Text], separator: int) -> int:
    return sum(part.cell_len for part in parts) + separator * (len(parts) - 1)


def _join(parts: list[Text], separator: str, style) -> Text:
    line = Text()
    for index, part in enumerate(parts):
        if index:
            line.append(separator, style=style)
        line.append_text(part)
    return line


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
