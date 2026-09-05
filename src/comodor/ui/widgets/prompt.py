"""The input editor.

A terminal agent lives and dies by its prompt box, so this is a real editor:
multi-line, word-wise motion, input history, bracketed paste, and slash-command
completion.

Cursor arithmetic uses ``rich.cells.cell_len`` rather than ``len`` throughout.
A CJK character occupies two terminal columns and an emoji can occupy two as
well; measuring in characters puts the cursor in the wrong place the moment
anyone types outside ASCII, which is exactly the kind of bug that makes a tool
feel unfinished.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rich.cells import cell_len
from rich.console import Group, RenderableType
from rich.text import Text

from ..layout import Rect
from ..theme import Theme

WORD = re.compile(r"\w+|\S")


@dataclass
class Editor:
    """A text buffer with a cursor."""

    text: str = ""
    cursor: int = 0
    history: list[str] = field(default_factory=list)
    history_index: int = -1
    draft: str = ""                     # what was typed before browsing history
    scroll: int = 0                     # first visible display row

    # -- editing ---------------------------------------------------------- #

    def insert(self, chunk: str) -> None:
        self.text = self.text[:self.cursor] + chunk + self.text[self.cursor:]
        self.cursor += len(chunk)

    def backspace(self) -> None:
        if self.cursor > 0:
            self.text = self.text[:self.cursor - 1] + self.text[self.cursor:]
            self.cursor -= 1

    def delete(self) -> None:
        if self.cursor < len(self.text):
            self.text = self.text[:self.cursor] + self.text[self.cursor + 1:]

    def delete_word(self) -> None:
        start = self._word_left()
        self.text = self.text[:start] + self.text[self.cursor:]
        self.cursor = start

    def delete_to_start(self) -> None:
        line_start = self.text.rfind("\n", 0, self.cursor) + 1
        self.text = self.text[:line_start] + self.text[self.cursor:]
        self.cursor = line_start

    def delete_to_end(self) -> None:
        line_end = self.text.find("\n", self.cursor)
        if line_end == -1:
            line_end = len(self.text)
        self.text = self.text[:self.cursor] + self.text[line_end:]

    def clear(self) -> str:
        taken = self.text
        self.text = ""
        self.cursor = 0
        self.scroll = 0
        self.history_index = -1
        return taken

    # -- motion ----------------------------------------------------------- #

    def left(self) -> None:
        self.cursor = max(0, self.cursor - 1)

    def right(self) -> None:
        self.cursor = min(len(self.text), self.cursor + 1)

    def word_left(self) -> None:
        self.cursor = self._word_left()

    def word_right(self) -> None:
        match = WORD.search(self.text, self.cursor)
        self.cursor = match.end() if match else len(self.text)

    def _word_left(self) -> int:
        index = self.cursor
        while index > 0 and self.text[index - 1].isspace():
            index -= 1
        while index > 0 and not self.text[index - 1].isspace():
            index -= 1
        return index

    def home(self) -> None:
        self.cursor = self.text.rfind("\n", 0, self.cursor) + 1

    def end(self) -> None:
        found = self.text.find("\n", self.cursor)
        self.cursor = len(self.text) if found == -1 else found

    def up(self) -> bool:
        """Move up a line; returns False when already on the first line."""
        line_start = self.text.rfind("\n", 0, self.cursor) + 1
        if line_start == 0:
            return False
        column = self.cursor - line_start
        previous_start = self.text.rfind("\n", 0, line_start - 1) + 1
        previous_length = line_start - 1 - previous_start
        self.cursor = previous_start + min(column, previous_length)
        return True

    def down(self) -> bool:
        line_start = self.text.rfind("\n", 0, self.cursor) + 1
        line_end = self.text.find("\n", self.cursor)
        if line_end == -1:
            return False
        column = self.cursor - line_start
        next_start = line_end + 1
        next_end = self.text.find("\n", next_start)
        next_length = (len(self.text) if next_end == -1 else next_end) - next_start
        self.cursor = next_start + min(column, next_length)
        return True

    # -- history ---------------------------------------------------------- #

    def remember(self, text: str) -> None:
        entry = text.strip()
        if entry and (not self.history or self.history[-1] != entry):
            self.history.append(entry)
        del self.history[:-200]
        self.history_index = -1

    def previous(self) -> bool:
        if not self.history:
            return False
        if self.history_index == -1:
            self.draft = self.text
            self.history_index = len(self.history) - 1
        elif self.history_index > 0:
            self.history_index -= 1
        else:
            return True
        self.text = self.history[self.history_index]
        self.cursor = len(self.text)
        return True

    def next(self) -> bool:
        if self.history_index == -1:
            return False
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.text = self.history[self.history_index]
        else:
            self.history_index = -1
            self.text = self.draft
        self.cursor = len(self.text)
        return True

    # -- layout ----------------------------------------------------------- #

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()

    def wrapped(self, width: int) -> list[tuple[str, int]]:
        """Display rows as ``(text, offset)`` where offset indexes into ``text``.

        Wrapping is done by display width so that a row of CJK text breaks at
        the right column rather than overflowing the panel.
        """
        width = max(1, width)
        rows: list[tuple[str, int]] = []
        offset = 0
        for line in self.text.split("\n"):
            if not line:
                rows.append(("", offset))
                offset += 1
                continue
            current = ""
            start = offset
            for char in line:
                if cell_len(current + char) > width:
                    rows.append((current, start))
                    start += len(current)
                    current = char
                else:
                    current += char
            rows.append((current, start))
            offset += len(line) + 1
        return rows

    def cursor_position(self, width: int) -> tuple[int, int]:
        """``(row, column)`` of the cursor in wrapped display coordinates."""
        rows = self.wrapped(width)
        for index, (text, offset) in enumerate(rows):
            if offset <= self.cursor <= offset + len(text):
                return index, cell_len(text[:self.cursor - offset])
        return max(0, len(rows) - 1), 0


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #

PLACEHOLDER = "Type a task, or / for commands"


def render_editor(editor: Editor, rect: Rect, theme: Theme, placeholder: str = PLACEHOLDER,
                  focused: bool = True, rows: int = 3) -> RenderableType:
    """Draw the buffer with a visible cursor, scrolled to keep it on screen.

    Always exactly ``rows`` rows. There is no border around the composer any
    more, so nothing else is holding the space open: a one-line draft would
    otherwise pull the footer up under it and the whole page would jump on
    every newline.
    """
    width = max(4, rect.width)

    if editor.is_empty and not editor.text:
        body = Text(placeholder, style=theme.style("dim"))
        if focused:
            body = Text.assemble(
                (theme.glyphs.cursor, theme.style("accent")),
                (placeholder, theme.style("dim")),
            )
        return _fill([body], rows)

    lines = editor.wrapped(width)
    cursor_row, cursor_column = editor.cursor_position(width)

    # Keep the cursor inside the visible window.
    if cursor_row < editor.scroll:
        editor.scroll = cursor_row
    elif cursor_row >= editor.scroll + rows:
        editor.scroll = cursor_row - rows + 1
    editor.scroll = max(0, min(editor.scroll, max(0, len(lines) - rows)))

    visible = lines[editor.scroll:editor.scroll + rows]
    rendered: list[Text] = []
    for index, (line, _) in enumerate(visible):
        row_index = editor.scroll + index
        text = Text(line, style=theme.style("value"))
        if focused and row_index == cursor_row:
            _mark_cursor(text, line, cursor_column, theme)
        rendered.append(text)

    if len(lines) > rows:
        marker = Text(f"  {editor.scroll + 1}-{editor.scroll + len(visible)}"
                      f"/{len(lines)}", style=theme.style("dim"))
        rendered.append(marker)

    return _fill(rendered, rows)


def _fill(rendered: list[Text], rows: int) -> RenderableType:
    """Pad out to the rows the geometry allotted, so the layout cannot move."""
    while len(rendered) < rows:
        rendered.append(Text(""))
    return Group(*rendered[:rows])


def _mark_cursor(text: Text, line: str, column: int, theme: Theme) -> None:
    """Highlight one cell, appending a space when the cursor sits past the end."""
    from rich.style import Style

    cursor_style = (Style(reverse=True) if theme.no_color
                    else Style(bgcolor=theme.palette.accent,
                               color=theme.palette.background))
    # Convert the display column back to a character index.
    index = 0
    measured = 0
    for position, char in enumerate(line):
        if measured >= column:
            index = position
            break
        measured += cell_len(char)
        index = position + 1
    if index >= len(line):
        text.append(" ", style=cursor_style)
    else:
        text.stylize(cursor_style, index, index + 1)


# --------------------------------------------------------------------------- #
# slash-command completion
# --------------------------------------------------------------------------- #


def completions(text: str, commands: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Commands matching what has been typed so far, if it starts with ``/``."""
    stripped = text.lstrip()
    if not stripped.startswith("/") or "\n" in text:
        return []
    prefix = stripped.split()[0] if stripped.split() else "/"
    if " " in stripped:
        return []                       # already past the command word
    return [(name, help_text) for name, help_text in commands
            if name.startswith(prefix)]


#: Where the description starts, in cells from the marker.
#:
#: Wide enough for every command there is, so the descriptions line up into a
#: column instead of stepping in and out with the length of each name.
NAME_COLUMN = 12

#: The most rows the completion menu may ever occupy, indicator included.
#:
#: Four commands and a line saying how many more there are. Taller would start
#: covering the conversation to list things nobody is reading; shorter stops
#: being a menu.
MENU_CEILING = 5


def menu_budget(total: int, available: int, ceiling: int = MENU_CEILING) -> int:
    """How many rows the completion menu gets. Rows, not items.

    `limit` used to mean "items", and the renderer then added an overflow line
    on top of it — so a composer that budgeted four rows got five, and the
    prompt sat one row lower than the layout said. Counting every row the menu
    can draw, including the indicator, is the only definition both sides can
    honour.

    Called by the screen to lay out and by the app to work out how far a
    keypress may scroll, so that the two cannot drift apart.
    """
    if total <= 0:
        return 0
    return min(total, max(0, min(available, ceiling)))


def visible_items(total: int, budget: int) -> int:
    """How many commands fit, given the rows the menu was granted.

    One row goes to the indicator whenever there is something it needs to
    point at. The exception is a menu one row tall: an indicator alone would
    be a list showing none of the list, so the row goes to the command.
    """
    if total <= 0 or budget <= 0:
        return 0
    if total <= budget:
        return total                    # everything fits; no indicator needed
    return budget if budget <= 1 else budget - 1


def scroll_into_view(selected: int, top: int, total: int, capacity: int) -> int:
    """Where the window starts, so that `selected` is inside it.

    Selection and viewport are separate things, and conflating them is what
    made arrow-down look broken: the index moved through all thirty-four
    commands while the menu kept drawing the first four, so past the fourth
    there was no highlight on screen at all and every keypress looked ignored.

    The rule is the ordinary one, and the important half is the first line of
    it: a selection already on screen does not move the window. Scrolling on
    every keypress is as disorienting as never scrolling.

    Arithmetic only — no scan of the list — so it costs the same for five
    commands as for a thousand.
    """
    if total <= 0 or capacity <= 0:
        return 0

    furthest = max(0, total - capacity)
    top = max(0, min(top, furthest))

    if selected < top:
        top = selected                          # walked off the top
    elif selected >= top + capacity:
        top = selected - capacity + 1           # walked off the bottom

    return max(0, min(top, furthest))


def render_completions(matches: list[tuple[str, str]], theme: Theme,
                       selected: int = 0, limit: int = MENU_CEILING,
                       top: int = 0, width: int = 0) -> RenderableType:
    """The commands a prefix could mean, in no more than `limit` terminal rows.

    `limit` counts **physical** rows — what the terminal actually draws, not
    entries in a list. Those were the same thing until a description ran past
    the edge of a narrow window: Rich wraps a `Text` by default, so one entry
    became two lines, and a menu budgeted five rows drew eight. The composer's
    arithmetic held; the drawing did not.

    So every row is truncated to `width` before it leaves here. One entry is
    one line, always, and the menu occupies exactly what it was granted.

    `width` of 0 means "do not know", and nothing is truncated. Only a caller
    that has no geometry should pass that — the screen always knows.

    `top` is a hint, not an instruction. The window is clamped here as well as
    where it is kept, because a stale index arriving from anywhere must not be
    able to produce a menu with nothing highlighted — that failure is silent
    on screen.
    """
    total = len(matches)
    if total <= 0 or limit <= 0:
        return Group()

    capacity = visible_items(total, limit)
    selected = max(0, min(selected, total - 1))
    top = scroll_into_view(selected, top, total, capacity)
    window = matches[top:top + capacity]

    rows: list[Text] = []
    for offset, (name, description) in enumerate(window):
        index = top + offset
        marker = theme.glyphs.arrow if index == selected else " "
        row = Text()
        row.append(f"{marker} ", style=theme.style("accent"))
        row.append(name.ljust(NAME_COLUMN), style=theme.style(
            "value" if index == selected else "text",
            bold=index == selected))
        row.append(description, style=theme.style("dim"))
        rows.append(_one_line(row, width))

    hidden = _overflow(top, capacity, total, width)
    if hidden and len(rows) < limit:
        rows.append(_one_line(Text(f"  … {hidden}", style=theme.style("dim")),
                              width))
    return Group(*rows)


def _one_line(row: Text, width: int) -> Text:
    """A row the terminal will draw on exactly one line.

    `Text.truncate` is the part that does the work, and it is used rather than
    `no_wrap` because `no_wrap` does not do what its name suggests here: a
    `Text` marked `no_wrap` printed to a narrower console still comes back as
    two lines. Truncating is the only thing that holds.

    It counts cells rather than characters, so a description in Chinese or one
    carrying an emoji is cut where the terminal would actually run out of room
    instead of two columns past it.

    What survives a cut is decided by order: the marker is first, then the
    command, then the description. So the thing somebody is choosing between
    stays legible and the explanation of it is what gives way.
    """
    if width > 0:
        row.truncate(width, overflow="ellipsis")
    row.no_wrap = True          # belt and braces; truncate is what guarantees it
    return row


def _overflow(top: int, capacity: int, total: int, width: int = 0) -> str:
    """What the indicator says, or "" when the whole list is on screen.

    It reports the window that is actually drawn. It used to say
    `len(matches) - limit` regardless of where the window was, which was
    right only for the first screenful and then quietly wrong — and it was the
    one thing on screen that could have revealed the selection had gone
    somewhere invisible.

    In a narrow window the long form is shortened rather than cut, because
    `… 7 above · 23 mo` reads as a bug and `↑7 ↓23` reads as a fact. The
    compact form says the same two numbers in a third of the room, and the
    row is still truncated afterwards in case even that does not fit.
    """
    above = top
    below = max(0, total - (top + capacity))
    if not above and not below:
        return ""

    if above and below:
        spelled = f"{above} above · {below} more"
        # 4 = the two leading spaces and the "… " the caller adds.
        if width and cell_len(spelled) + 4 > width:
            return f"↑{above} ↓{below}"
        return spelled
    if above:
        return f"{above} above"
    return f"{below} more"
