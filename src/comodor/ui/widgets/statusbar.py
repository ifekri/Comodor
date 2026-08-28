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
    version: str = ""
    #: The folder the agent is confined to, and how many skills are loaded.
    #: Neither changes during a session, so neither is on the status line —
    #: they are on the empty transcript, where somebody checks them before
    #: typing the first thing.
    project: str = ""
    skills: int = 0

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
    """The bottom line: what mode this is, what is answering, and the keys.

    Three groups, in the order somebody needs them. The mode, because it
    decides whether the next thing typed edits files. What is answering, in
    `provider/model` — the single fact people most often get wrong about a
    session. Then the keys, which are the least urgent and the first to go.

    It sheds from the right as the terminal narrows and the mode never goes.
    There is no border holding this row open, so a line one cell too long does
    not clip — it wraps, and takes the whole layout down a row with it.
    """
    dim = theme.style("dim", dim=True)
    glyphs = theme.glyphs

    mode = Text()
    mode.append("Mode : ", style=theme.style("label"))
    mode.append(model.mode.capitalize(), style=theme.style("accent", bold=True))
    mode.append(" [TAB]", style=dim)

    who = Text()
    who.append(f"{glyphs.check} ", style=theme.style(
        "good" if model.connected else "bad"))
    if model.provider and model.provider != "—":
        who.append(model.provider, style=theme.style("dim"))
        who.append("/", style=dim)
    who.append(_fit_model(model.model, width), style=theme.style("value"))

    # Everything the window is holding, in one figure. A percentage on its own
    # answers "how full" and not "of what", and the limit is the part that
    # differs between models.
    fill = model.fill
    tone = "dim" if fill < 0.6 else ("warn" if fill < 0.85 else "bad")
    context = Text()
    context.append(f"{fill:.0%}", style=theme.style(tone))
    context.append(f" of {humanise(model.context_limit)}", style=dim)

    keys = [
        _key("Setting", "[ctrl + s]", theme),
        _key("Command", "/", theme),
        _key("Exit", "esc", theme),
    ]

    money: Text | None = None
    if model.cost_usd:
        money = Text(f"${model.cost_usd:.3f}", style=theme.style("accent"))

    # Least important last: this is the order they are dropped in.
    parts: list[Text] = [mode, who, context]
    if model.loop:
        parts.append(Text("loop", style=theme.style("good")))
    if model.rules:
        parts.append(Text(f"{glyphs.memory}{model.rules}", style=theme.style("good")))
    if money is not None:
        parts.append(money)
    parts.extend(keys)

    separator = "   "
    if width <= 0:
        return _join(parts, separator, dim)
    while len(parts) > 1 and _joined_len(parts, len(separator)) > width:
        parts.pop()
    return _join(parts, separator, dim)


def _key(name: str, stroke: str, theme: Theme) -> Text:
    row = Text()
    row.append(f"{name} : ", style=theme.style("label"))
    row.append(stroke, style=theme.style("dim"))
    return row


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
