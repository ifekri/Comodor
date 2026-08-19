"""Composing one frame.

Every widget is rendered at the exact size the geometry gave it and then placed
into a grid of fixed-width columns, so the picture on screen and the rectangles
used for hit-testing cannot drift apart.

Rendering is pure: state in, renderable out. Nothing here reads input, touches
the agent, or mutates anything, which is what allows the whole interface to be
snapshot-tested at a dozen terminal sizes without a terminal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from .layout import Geometry, Rect
from .theme import Theme
from .widgets.buttons import button_column, keyboard_hints
from .widgets.chat import Entry, render_transcript
from .widgets.history import HistoryModel, render_history
from .widgets.overlay import Overlay, render_overlay
from .widgets.panel import framed, hint_line, too_small_notice
from .widgets.prompt import Editor, completions, render_completions, render_editor
from .widgets.statusbar import StatusModel, activity_line, footer_line, status_block
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

        body = self._body_row(state, geometry)
        footer = self._footer_row(state, geometry)
        frame = Group(body, Text(""), footer)
        if geometry.margin:
            return Padding(frame, (geometry.margin, geometry.margin))
        return frame

    # -- rows ------------------------------------------------------------- #

    @staticmethod
    def _columns(*widths: int) -> Table:
        """A grid whose columns are exactly the geometry's widths.

        Rich's own cell padding would silently steal columns and force the
        panels to shrink, so gaps are explicit spacer columns instead.
        """
        grid = Table.grid(padding=0, pad_edge=False, collapse_padding=True)
        for width in widths:
            grid.add_column(width=width, no_wrap=True)
        return grid

    def _body_row(self, state: ScreenState, geometry: Geometry) -> RenderableType:
        chat_panel = self._chat(state, geometry.chat)
        if geometry.sidebar is None:
            return chat_panel

        gap = geometry.chat.x - geometry.sidebar.right
        grid = self._columns(geometry.sidebar.width, gap, geometry.chat.width)
        grid.add_row(self._sidebar(state, geometry.sidebar), "", chat_panel)
        return grid

    def _footer_row(self, state: ScreenState, geometry: Geometry) -> RenderableType:
        prompt_panel = self._prompt(state, geometry.prompt)

        right: RenderableType = prompt_panel
        if geometry.show_buttons:
            first = next(iter(geometry.buttons.values()))
            gap = first.x - geometry.prompt.right
            columns = self._columns(geometry.prompt.width, gap, first.width)
            columns.add_row(prompt_panel, "",
                            Group(*button_column(geometry.buttons, self.theme,
                                                 busy=state.status.busy)))
            right = columns

        if geometry.status is None:
            return right

        gap = geometry.prompt.x - geometry.status.right
        grid = self._columns(geometry.status.width, gap, geometry.chat.width)
        grid.add_row(self._status(state, geometry.status), "", right)
        return grid

    # -- panels ----------------------------------------------------------- #

    def _sidebar(self, state: ScreenState, rect: Rect) -> RenderableType:
        body = render_history(state.history, rect, self.theme)
        return framed(body, rect, self.theme, title="History",
                      focused=state.focus == "sidebar")

    def _chat(self, state: ScreenState, rect: Rect) -> RenderableType:
        body, total = render_transcript(state.entries, rect, self.theme,
                                        self.console, state.scroll)
        state.transcript_rows = total

        subtitle = ""
        if state.scroll > 0:
            subtitle = f"scrolled {state.scroll}"
        return framed(body, rect, self.theme, title="Chat",
                      focused=state.focus == "chat", subtitle=subtitle)

    def _status(self, state: ScreenState, rect: Rect) -> RenderableType:
        return framed(status_block(state.status, rect, self.theme), rect, self.theme)

    def _prompt(self, state: ScreenState, rect: Rect) -> RenderableType:
        theme = self.theme
        inner_width = max(8, rect.width - 4)
        # Panel chrome takes two rows; the footer line takes one, the divider one.
        editor_rows = max(1, rect.height - 4)

        matches = completions(state.editor.text, state.slash_commands)
        if matches and rect.height >= 6:
            editor_rows = max(1, editor_rows - min(len(matches), 4) - 1)

        editor = render_editor(state.editor, rect, theme,
                               focused=state.focus == "prompt", rows=editor_rows)
        blocks: list[RenderableType] = [editor]

        if matches and rect.height >= 6:
            blocks.append(render_completions(matches, theme, state.completion_index,
                                             limit=4))

        # The divider and the status line sit on the panel's bottom edge, so the
        # editor grows downward into the empty space rather than leaving a gap
        # under the footer.
        drawn = self._measure(Group(*blocks), inner_width)
        for _ in range(max(0, editor_rows - drawn)):
            blocks.append(Text(""))

        blocks.append(Text(theme.glyphs.divider * inner_width,
                           style=theme.style("border.dim")))

        if state.status.busy:
            blocks.append(activity_line(state.status, theme, state.spinner))
        elif state.toasts.active:
            blocks.append(state.toasts.render(theme, inner_width))
        else:
            blocks.append(footer_line(state.status, inner_width, theme))

        return framed(Group(*blocks), rect, theme,
                      focused=state.focus == "prompt")

    def _measure(self, renderable: RenderableType, width: int) -> int:
        """How many rows something will occupy once wrapped to ``width``."""
        options = self.console.options.update(width=max(1, width), height=None)
        return len(self.console.render_lines(renderable, options, pad=False))

    # -- narrow-terminal extras -------------------------------------------- #

    def hints(self) -> RenderableType:
        return hint_line(keyboard_hints(self.theme), self.theme)
