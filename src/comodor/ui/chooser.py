"""Choosing from a list, with the arrow keys.

The wizard used to print a numbered list and read a number. That is fine for
three options and wrong for a hundred: picking a model meant reading a wall of
identifiers, finding the one you wanted, remembering its number, scrolling back
down because the list had pushed the prompt off the screen, and typing a digit
you were no longer sure of. And every question stayed on screen afterwards, so
by the fourth one the terminal was a transcript of decisions already made.

What is here instead is one framed list at a time.

* **The frame never grows past the terminal.** However many options there are,
  the list is windowed to what will fit and moves with the cursor, with a count
  of what is above and below. Nothing is ever off screen with no sign that it
  is there.
* **Typing filters.** With sixty models on offer, `son` is faster than sixty
  presses of the down arrow, and it is what anybody who has used a fuzzy finder
  will try first.
* **It refuses to be the only way in.** Without a terminal — a pipe, a test, an
  editor's console, `curl | sh` — the numbered prompt is still there. A setup
  wizard that requires a particular kind of terminal is a setup wizard that
  cannot be scripted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .input.keys import KeyEvent
from .input.reader import TerminalInput
from .theme import Theme

#: Rows the frame spends on itself: two borders, and the hint line under it.
CHROME = 4
#: Never show fewer than this, even on a very short terminal.
MIN_ROWS = 3


@dataclass(frozen=True)
class Option:
    value: str
    label: str
    note: str = ""

    def matches(self, needle: str) -> bool:
        return needle in self.label.lower() or needle in self.note.lower()


def interactive(console: Console) -> bool:
    """Can we take over the keyboard here?"""
    try:
        return bool(console.is_terminal and console.file.isatty()
                    and _stdin_is_a_terminal())
    except Exception:
        return False


def _stdin_is_a_terminal() -> bool:
    import sys

    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except Exception:
        return False


class Chooser:
    """One list, one choice."""

    def __init__(self, console: Console, theme: Theme, options: Sequence[Option],
                 title: str = "", default: int = 0) -> None:
        self.console = console
        self.theme = theme
        self.options = list(options)
        self.title = title
        self.cursor = max(0, min(default, len(self.options) - 1))
        self.filter = ""
        self.offset = 0

    # -- what is currently visible ---------------------------------------- #

    @property
    def matching(self) -> list[Option]:
        if not self.filter:
            return self.options
        needle = self.filter.lower()
        return [option for option in self.options if option.matches(needle)]

    def rows(self) -> int:
        """How many options fit, given the terminal we are in."""
        available = max(MIN_ROWS, self.console.size.height - CHROME - 6)
        return min(len(self.matching) or 1, available)

    def _scroll_into_view(self) -> None:
        window = self.rows()
        if self.cursor < self.offset:
            self.offset = self.cursor
        elif self.cursor >= self.offset + window:
            self.offset = self.cursor - window + 1
        self.offset = max(0, min(self.offset, max(0, len(self.matching) - window)))

    # -- drawing ----------------------------------------------------------- #

    def render(self) -> RenderableType:
        theme = self.theme
        items = self.matching
        window = self.rows()
        self._scroll_into_view()
        visible = items[self.offset:self.offset + window]

        table = Table.grid(padding=(0, 1))
        table.add_column(width=2, no_wrap=True)
        table.add_column(no_wrap=True)
        table.add_column(overflow="ellipsis")

        if not items:
            table.add_row("", Text("nothing matches", style=theme.style("bad")),
                          Text(""))

        for index, option in enumerate(visible, start=self.offset):
            chosen = index == self.cursor
            # The arrow, not just a colour: a highlighted row that relies on
            # background alone disappears on a terminal that renders it faintly,
            # and this is the only thing on screen saying where you are.
            table.add_row(
                Text(theme.glyphs.arrow if chosen else " ",
                     style=theme.style("accent", bold=True)),
                Text(option.label,
                     style=theme.style("accent" if chosen else "value",
                                       bold=chosen)),
                Text(option.note, style=theme.style("dim")),
            )

        blocks: list[RenderableType] = []
        above = self.offset
        below = max(0, len(items) - self.offset - window)
        if above:
            blocks.append(Text(f"  {above} more above", style=theme.style("dim")))
        blocks.append(table)
        if below:
            blocks.append(Text(f"  {below} more below", style=theme.style("dim")))

        subtitle = None
        if self.filter:
            subtitle = Text(f" filter: {self.filter} ", style=theme.style("accent"))
        elif len(items) != len(self.options):
            subtitle = Text(f" {len(items)} of {len(self.options)} ",
                            style=theme.style("dim"))

        panel = Panel(
            Group(*blocks),
            box=self.theme.box,
            border_style=theme.style("border"),
            title=Text(f" {self.title} ", style=theme.style("title")) if self.title
            else None,
            title_align="left",
            subtitle=subtitle,
            subtitle_align="right",
            padding=(0, 1),
        )
        return Group(panel, self._hint())

    def _hint(self) -> Text:
        theme = self.theme
        hint = Text("  ", style=theme.style("dim"))
        for key, what in (("↑↓", "move"), ("enter", "choose"),
                          ("type", "filter"), ("esc", "cancel")):
            hint.append(key, style=theme.style("accent"))
            hint.append(f" {what}   ", style=theme.style("dim"))
        return hint

    # -- the loop ----------------------------------------------------------- #

    def run(self) -> str | None:
        """Returns the chosen value, or None if the user backed out."""
        from rich.live import Live

        items = self.matching
        if not items:
            return None

        with TerminalInput(mouse=False, paste=False) as terminal, Live(
            self.render(), console=self.console, auto_refresh=False,
            transient=True,
        ) as live:
            while True:
                event = terminal.wait(0.2)
                if event is None:
                    continue
                if not isinstance(event, KeyEvent):
                    continue

                outcome = self._handle(event)
                if outcome is _CANCEL:
                    return None
                if outcome is not None:
                    return outcome
                live.update(self.render(), refresh=True)

    def _handle(self, event: KeyEvent) -> object:
        """None to keep going, a string to accept it, ``_CANCEL`` to give up."""
        items = self.matching

        if event.matches("ctrl+c") or event.key == "escape":
            return _CANCEL
        if event.key == "enter":
            return items[self.cursor].value if items else _CANCEL

        if event.key in ("up", "down", "pgup", "pgdn", "home", "end"):
            self._move(event.key, len(items))
            return None
        if event.key == "backspace":
            self.filter = self.filter[:-1]
            self._reset_cursor()
            return None
        if event.key == "char" and event.char and not event.ctrl and not event.alt:
            self.filter += event.char
            self._reset_cursor()
            return None
        return None

    def _move(self, key: str, count: int) -> None:
        if count == 0:
            return
        window = self.rows()
        if key == "up":
            # Wrapping, because a list that stops dead at the top makes you
            # reach for the mouse to get to the bottom of a long one.
            self.cursor = (self.cursor - 1) % count
        elif key == "down":
            self.cursor = (self.cursor + 1) % count
        elif key == "pgup":
            self.cursor = max(0, self.cursor - window)
        elif key == "pgdn":
            self.cursor = min(count - 1, self.cursor + window)
        elif key == "home":
            self.cursor = 0
        elif key == "end":
            self.cursor = count - 1

    def _reset_cursor(self) -> None:
        """A changed filter means a changed list; start at the top of it."""
        self.cursor = 0
        self.offset = 0


class _Cancel:
    pass


_CANCEL = _Cancel()


def choose(console: Console, theme: Theme, options: Sequence[Option],
           title: str = "", default: int = 0) -> str | None:
    """The whole interaction, or None if there is no terminal to run it in."""
    if not interactive(console) or not options:
        return None
    try:
        return Chooser(console, theme, options, title=title, default=default).run()
    except Exception:
        # A terminal that will not do raw mode, a reader that will not start:
        # the caller still has the numbered prompt, and a failed experiment
        # must not cost somebody their first run.
        return None
