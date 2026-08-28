"""Composing one frame.

Every widget is rendered at the exact size the geometry gave it and then placed
into a grid of fixed-width columns, so the picture on screen and the rectangles
used for hit-testing cannot drift apart.

Rendering is pure: state in, renderable out. Nothing here reads input, touches
the agent, or mutates anything, which is what allows the whole interface to be
snapshot-tested at a dozen terminal sizes without a terminal.

What changed is what does the holding-together. There used to be four bordered
panels, and four borders is four things competing to be looked at first — the
transcript was framed exactly as loudly as the context gauge. Now a rule under
the name, a rule above the composer, and space between them. Everything that is
not the conversation is one quiet line at the top or one at the bottom.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from .layout import Geometry, Rect
from .theme import Theme
from .widgets.buttons import hint_line, keyboard_hints
from .widgets.chat import Entry, render_transcript
from .widgets.history import HistoryModel, render_history
from .widgets.overlay import Overlay, render_overlay
from .widgets.panel import rule, too_small_notice
from .widgets.prompt import Editor, completions, render_completions, render_editor
from .widgets.statusbar import StatusModel, activity_line, footer_line
from .widgets.toast import ToastQueue


@dataclass
class ScreenState:
    """Everything the renderer needs for one frame."""

    entries: list[Entry] = field(default_factory=list)
    history: HistoryModel = field(default_factory=HistoryModel)
    status: StatusModel = field(default_factory=StatusModel)
    editor: Editor = field(default_factory=Editor)
    toasts: ToastQueue = field(default_factory=ToastQueue)
    overlay: Overlay | None = None
    focus: str = "prompt"                 # prompt | chat | sidebar
    scroll: int = 0                       # rows up from the newest output
    spinner: int = 0
    slash_commands: list[tuple[str, str]] = field(default_factory=list)
    completion_index: int = 0
    sidebar_visible: bool = True
    transcript_rows: int = 0              # filled in by the renderer


class Screen:
    """Turns :class:`ScreenState` into something Rich can print."""

    def __init__(self, console: Console, theme: Theme) -> None:
        self.console = console
        self.theme = theme

    def render(self, state: ScreenState, geometry: Geometry) -> RenderableType:
        if geometry.too_small:
            return too_small_notice(geometry.width, geometry.height, self.theme)
        if state.overlay is not None:
            return render_overlay(state.overlay, geometry.width, geometry.height,
                                  self.theme)

        inner = geometry.width - 2 * geometry.margin
        rows: list[RenderableType] = [
            self._body(state, geometry),
            Text(""),
            rule(inner, self.theme),
            self._composer(state, geometry),
            Text(""),
            self._footer(state, geometry, inner),
        ]

        frame: RenderableType = Group(*rows)
        if geometry.margin:
            frame = Padding(frame, (0, geometry.margin))
        return self._painted(frame)

    def _painted(self, frame: RenderableType) -> RenderableType:
        """Fill every cell, for the palettes that need to own the background.

        A dark theme can leave the terminal's own black showing through and
        look right on anybody's machine. A light one cannot: dark ink on
        somebody's dark terminal is not a light theme, it is an unreadable one,
        and no program can ask a terminal to change colour. So the light
        palettes paint, and the dark ones stay out of the way.
        """
        palette = self.theme.palette
        if not palette.paint or self.theme.no_color:
            return frame

        from rich.style import Style
        from rich.styled import Styled

        return Styled(frame, Style(bgcolor=palette.background,
                                   color=palette.text))

    # -- the body ---------------------------------------------------------- #

    @staticmethod
    def _columns(*widths: int) -> Table:
        """A grid whose columns are exactly the geometry's widths.

        Rich's own cell padding would silently steal columns and force the
        content to shrink, so gaps are explicit spacer columns instead.
        """
        grid = Table.grid(padding=0, pad_edge=False, collapse_padding=True)
        for width in widths:
            grid.add_column(width=width, no_wrap=True)
        return grid

    def _body(self, state: ScreenState, geometry: Geometry) -> RenderableType:
        transcript = self._chat(state, geometry.chat)
        if geometry.sidebar is None:
            return transcript

        # Transcript first, sidebar second — it sits on the right now, and the
        # grid lays columns out in the order they are added rather than by the
        # x each rect carries. Moving the rect without moving this produced a
        # sidebar that reported one position and drew in another.
        gap = geometry.sidebar.x - geometry.chat.right
        grid = self._columns(geometry.chat.width, gap, geometry.sidebar.width)
        grid.add_row(transcript, "",
                     render_history(state.history, geometry.sidebar, self.theme))
        return grid

    def _chat(self, state: ScreenState, rect: Rect) -> RenderableType:
        body, total = render_transcript(state.entries, rect, self.theme,
                                        self.console, state.scroll,
                                        status=state.status)
        state.transcript_rows = total
        return body

    # -- the composer ------------------------------------------------------ #

    def _composer(self, state: ScreenState, geometry: Geometry) -> RenderableType:
        """What you are typing, and the commands it might mean.

        The completions sit *over* the editor's own rows rather than pushing
        anything: a list that grows downwards moves the line you are typing on,
        which is the one thing on screen that must not move while you type.
        """
        rect = geometry.prompt
        rows = max(1, rect.height)

        matches = completions(state.editor.text, state.slash_commands)
        listed = min(len(matches), max(0, rows - 1), 4) if matches else 0

        editor = render_editor(state.editor, rect, self.theme,
                               focused=state.focus == "prompt",
                               rows=max(1, rows - listed))
        if not listed:
            return editor
        return Group(editor, render_completions(matches, self.theme,
                                                state.completion_index,
                                                limit=listed))

    # -- the footer -------------------------------------------------------- #

    def _footer(self, state: ScreenState, geometry: Geometry,
                width: int) -> RenderableType:
        """Where you are on the left, what the keys do on the right.

        One row. It used to be a bordered block on the left of the screen
        holding six labelled values, three of which never changed during a
        session — and a column of coloured buttons on the right. Both are the
        same information, and neither needed to be the second thing you saw.
        """
        if state.status.busy:
            left: RenderableType = activity_line(state.status, self.theme,
                                                 state.spinner)
        elif state.toasts.active:
            left = state.toasts.render(self.theme, width)
        else:
            left = footer_line(state.status, width, self.theme)

        # The status line now ends with the keys it used to be missing —
        # setting, command, exit — so a second row of them on the right was
        # the same information twice, and the two of them together left the
        # left-hand side too narrow to say what model was answering.
        if not geometry.hints or not state.status.busy:
            return left

        keys = hint_line(keyboard_hints(self.theme), self.theme)
        gap = max(1, width - _measure(left, self.console) - _measure(keys, self.console))
        grid = self._columns(width - gap - _measure(keys, self.console), gap,
                             _measure(keys, self.console))
        grid.add_row(left, "", keys)
        return grid

    # -- narrow-terminal extras -------------------------------------------- #

    def hints(self) -> RenderableType:
        return hint_line(keyboard_hints(self.theme), self.theme)

    def _measure(self, renderable: RenderableType, width: int) -> int:
        """How many rows something will occupy once wrapped to ``width``."""
        options = self.console.options.update(width=max(1, width), height=None)
        return len(self.console.render_lines(renderable, options, pad=False))


def _measure(renderable: RenderableType, console: Console) -> int:
    """How many cells wide something wants to be."""
    if isinstance(renderable, Text):
        return renderable.cell_len
    return console.measure(renderable).maximum
