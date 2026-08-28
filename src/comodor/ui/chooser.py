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
* **Some questions take more than one answer.** In that mode each row carries
  a box, space ticks the one under the cursor, and enter takes everything
  ticked. The ticks are held by value rather than by row, so filtering the
  list down and clearing the filter again leaves them where they were.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Sequence

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .input.keys import KeyEvent
from .input.reader import TerminalInput
from .theme import Theme

#: Rows the frame spends on itself: two borders, the hint line under it, the
#: two "more above / more below" lines, and a blank line either side.
CHROME = 7
#: Never show fewer than this, even on a very short terminal.
MIN_ROWS = 3
#: The most the detail pane may take, as a share of the screen. It grows to
#: fit the note rather than being a fixed size — the descriptions run from one
#: line to nine hundred characters, and a fixed pane either wastes rows on the
#: short ones or cuts the long ones — but it never takes so much that the list
#: it is describing disappears.
DETAIL_SHARE = 0.5
#: And never fewer than this, so the pane is worth opening at all.
DETAIL_MIN = 4
#: The widest a label may get before it is cut. Long enough for every skill id
#: in the catalogue, short enough that one long one cannot starve the note.
LABEL_WIDTH = 24


def _pane_width(console: Console) -> int:
    """Columns a line of the detail pane may use.

    Six off the console rather than four: two for the frame, two for its
    padding, and two of slack. Rich measures the panel's inside slightly
    narrower than the arithmetic suggests, and a line one column too long is
    re-wrapped into two — which makes the pane taller than the height that was
    reserved for it.
    """
    return max(20, console.width - 6)


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
                 title: str = "", default: int = 0, multi: bool = False,
                 verb: str = "choose") -> None:
        self.console = console
        self.theme = theme
        self.options = list(options)
        self.title = title
        self.cursor = max(0, min(default, len(self.options) - 1))
        self.filter = ""
        self.offset = 0
        #: Whether enter takes one row or every ticked one.
        self.multi = multi
        #: What enter is going to do, for the hint line. "install" rather than
        #: "choose" when that is what happens next.
        self.verb = verb
        #: Ticked values, not ticked rows. Filtering changes which options are
        #: on screen and at which index; it must not change what was asked for.
        self.picked: set[str] = set()
        #: Whether the full note for the highlighted row is open underneath.
        #:
        #: The rows show one line each, which is what keeps the list scannable
        #: and the frame the size of the screen — but some of these notes are a
        #: paragraph, and a list that truncates with no way to read the rest is
        #: a list you cannot choose from. Tab opens it, in the same frame,
        #: against whatever is under the cursor.
        self.detail = False

    # -- what is currently visible ---------------------------------------- #

    @property
    def matching(self) -> list[Option]:
        if not self.filter:
            return self.options
        needle = self.filter.lower()
        return [option for option in self.options if option.matches(needle)]

    def rows(self) -> int:
        """How many options fit, given the terminal we are in.

        One option is one row, which is only true because the note column is
        told not to wrap. It was not, and a four-hundred-character description
        became eight lines — so ten options claimed to fit and took sixty rows,
        the frame ran off the bottom of the screen, and the cursor could be
        moved several times before this number noticed it had left the window.
        Both faults were the same fault.
        """
        spare = self.console.size.height - CHROME
        if self.detail:
            spare -= self.detail_rows()
        return min(len(self.matching) or 1, max(MIN_ROWS, spare))

    def detail_rows(self) -> int:
        """How tall the open pane is: what the note needs, within reason."""
        if not self.detail:
            return 0
        items = self.matching
        note = items[self.cursor].note if items else ""
        # One for the rule naming the row, plus however many the note wraps to.
        # The same width `_detail` wraps at, so the height reserved here is the
        # height actually drawn.
        wrapped = textwrap.wrap(note, _pane_width(self.console)) or [""]
        wants = 1 + max(1, len(wrapped))
        ceiling = max(DETAIL_MIN, int(self.console.size.height * DETAIL_SHARE))
        return min(wants, ceiling)

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

        box_width = max(len(theme.glyphs.ticked), len(theme.glyphs.unticked))

        # `expand` and a ratio on the note, because the note is the only column
        # that can give ground. Without them Rich asks every column for the
        # width its longest cell wants, finds four hundred characters of note,
        # and squeezes the arrow and the checkbox to nothing to make room — so
        # the one mark saying where you are disappears exactly when the list is
        # long enough to need it.
        table = Table.grid(padding=(0, 1), expand=True)
        table.add_column(width=2, no_wrap=True)
        if self.multi:
            table.add_column(width=box_width, no_wrap=True)
        table.add_column(no_wrap=True, max_width=LABEL_WIDTH)
        # `no_wrap` as well as the ellipsis. `overflow` alone only decides what
        # happens to a line that is too long *after* wrapping has been tried,
        # so without this a long note silently became a paragraph.
        # Rich's own ellipsis is "…", which is not ASCII, so under `--ascii`
        # the note is cropped instead of marked. Cutting is the lesser fault:
        # the whole note is a keypress away in the pane below.
        table.add_column(no_wrap=True, ratio=1,
                         overflow="crop" if theme.ascii else "ellipsis")

        if not items:
            blank = ["", Text("nothing matches", style=theme.style("bad")), Text("")]
            table.add_row(*([blank[0], ""] + blank[1:] if self.multi else blank))

        for index, option in enumerate(visible, start=self.offset):
            chosen = index == self.cursor
            # The arrow, not just a colour: a highlighted row that relies on
            # background alone disappears on a terminal that renders it faintly,
            # and this is the only thing on screen saying where you are.
            cells = [Text(theme.glyphs.arrow if chosen else " ",
                          style=theme.style("accent", bold=True))]
            if self.multi:
                ticked = option.value in self.picked
                cells.append(Text(
                    theme.glyphs.ticked if ticked else theme.glyphs.unticked,
                    style=theme.style("good" if ticked else "dim",
                                      bold=ticked)))
            cells.append(Text(
                option.label,
                style=theme.style("accent" if chosen else "value", bold=chosen)))
            cells.append(Text(option.note, style=theme.style("dim")))
            table.add_row(*cells)

        blocks: list[RenderableType] = []
        above = self.offset
        below = max(0, len(items) - self.offset - window)
        if above:
            blocks.append(Text(f"  {above} more above", style=theme.style("dim")))
        blocks.append(table)
        if below:
            blocks.append(Text(f"  {below} more below", style=theme.style("dim")))
        if self.detail and items:
            blocks.append(self._detail(items[self.cursor]))

        subtitle = None
        if self.filter:
            subtitle = Text(f" filter: {self.filter} ", style=theme.style("accent"))
        elif self.multi and self.picked:
            subtitle = Text(f" {len(self.picked)} selected ",
                            style=theme.style("good"))
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

    def _detail(self, option: Option) -> RenderableType:
        """The whole note for the highlighted row, wrapped, under a rule.

        Inside the same frame rather than a second screen: the point of opening
        it is to decide about *this* row, and a pane that hides the list makes
        that comparison impossible.
        """
        theme = self.theme
        note = option.note or "Nothing more to say about this one."
        lines = textwrap.wrap(note, _pane_width(self.console)) or [""]
        cut = max(1, self.detail_rows() - 1)
        if len(lines) > cut:
            lines = lines[:cut]
            lines[-1] = lines[-1].rstrip() + theme.glyphs.ellipsis
        return Group(
            Text(theme.glyphs.divider * 3 + " " + option.label,
                 style=theme.style("dim")),
            # `no_wrap`, because the wrapping above is the one that was
            # counted. Left to Rich, the lines were re-wrapped a couple of
            # columns narrower, each one spilling a word onto a line of its
            # own — so a pane that had reserved eight rows quietly drew ten
            # and pushed the bottom border off the screen.
            Text("\n".join(lines), style=theme.style("text"),
                 no_wrap=True, overflow="crop"),
        )

    def _hint(self) -> Text:
        theme = self.theme
        # Through the glyph table, like everything else in the frame. Written
        # as a literal, this line stayed in arrows on a terminal that had just
        # had its borders downgraded for not being able to draw them.
        updown = f"{theme.glyphs.rise}{theme.glyphs.fall}"
        if self.multi:
            # The count is on the hint rather than only in the corner, because
            # this is the line that says what enter will do and "install"
            # without a number is a question.
            taking = (f"{self.verb} {len(self.picked)}" if self.picked
                      else f"{self.verb} nothing")
            keys = ((updown, "move"), ("space", "select"), ("enter", taking),
                    ("tab", "less" if self.detail else "more"),
                    ("esc", "cancel"))
        else:
            keys = ((updown, "move"), ("enter", "choose"),
                    ("tab", "less" if self.detail else "more"),
                    ("esc", "cancel"))
        hint = Text("  ", style=theme.style("dim"))
        for key, what in keys:
            hint.append(key, style=theme.style("accent"))
            hint.append(f" {what}   ", style=theme.style("dim"))
        return hint

    # -- the loop ----------------------------------------------------------- #

    def run(self) -> str | list[str] | None:
        """The chosen value, or the chosen values, or None if backed out.

        A list when `multi` is set — possibly an empty one, which is an answer
        of "none of them" rather than a refusal to answer. None is only ever
        escape or ctrl-c.
        """
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
            if self.multi:
                # In the order they were offered, not the order they were
                # ticked: the list on screen is what the reader remembers.
                return [option.value for option in self.options
                        if option.value in self.picked]
            return items[self.cursor].value if items else _CANCEL
        if self.multi and event.key == "char" and event.char == " " \
                and not event.ctrl and not event.alt:
            if items:
                value = items[self.cursor].value
                self.picked.symmetric_difference_update({value})
            return None

        if event.key == "tab":
            self.detail = not self.detail
            return None
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
    picked = _run(console, theme, options, title=title, default=default)
    return picked if isinstance(picked, str) else None


def choose_many(console: Console, theme: Theme, options: Sequence[Option],
                title: str = "", verb: str = "choose") -> list[str] | None:
    """Tick as many as you like. None means the list could not run.

    An empty list is a real answer — nothing ticked, enter pressed — and the
    caller must tell it apart from None, which means fall back to asking some
    other way.
    """
    picked = _run(console, theme, options, title=title, multi=True, verb=verb)
    return picked if isinstance(picked, list) else None


def _run(console: Console, theme: Theme, options: Sequence[Option],
         title: str = "", default: int = 0, multi: bool = False,
         verb: str = "choose") -> str | list[str] | None:
    if not interactive(console) or not options:
        return None
    try:
        return Chooser(console, theme, options, title=title, default=default,
                       multi=multi, verb=verb).run()
    except Exception:
        # A terminal that will not do raw mode, a reader that will not start:
        # the caller still has the numbered prompt, and a failed experiment
        # must not cost somebody their first run.
        return None
