"""The question form, in a terminal.

Several questions have to fit on one screen without becoming a wall of text, so
they are stacked as tabs: one strip of headers along the top, one question's
options below it, left and right to move between them. The user sees the whole
shape of what is being asked immediately — three tabs means three decisions —
and reads only one at a time.

Two pieces of state that look decorative and are not.

*Answered tabs are marked.* Somebody who tabbed away mid-form needs to see
which questions they have already dealt with without visiting each one, and
the mark on the tab is the only place that can be shown.

*The write-your-own row opens an editor in place.* Not a second screen: the
question and the other options stay visible while it is typed, because what
somebody writes in that box is usually a variation on an option they can see.

Navigation, in full:

    left / right      previous and next question
    up / down         move within the options
    space             pick (and for a multi-answer question, toggle)
    enter             pick, then go to the next unanswered question,
                      or submit if this was the last one
    ctrl+s            submit from anywhere
    escape            close the form without answering
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Group, RenderableType
from rich.style import Style
from rich.text import Text

from ...questions import Answer, Question
from ..theme import Theme


@dataclass
class Form:
    """A questionnaire being filled in."""

    questions: list[Question]
    #: Which question is on screen.
    current: int = 0
    #: Which option is under the cursor, per question. Kept per question so
    #: tabbing away and back returns to where the user was, not to the top.
    cursors: list[int] = field(default_factory=list)
    #: Chosen option indices, per question.
    picked: list[set[int]] = field(default_factory=list)
    #: What was typed into the write-your-own row, per question.
    written: list[str] = field(default_factory=list)
    #: True while the write-your-own row is being typed into.
    writing: bool = False
    caret: int = 0

    def __post_init__(self) -> None:
        count = len(self.questions)
        if not self.cursors:
            self.cursors = [0] * count
        if not self.picked:
            self.picked = [set() for _ in range(count)]
        if not self.written:
            self.written = [""] * count

    # -- where we are ------------------------------------------------------ #

    @property
    def question(self) -> Question:
        return self.questions[self.current]

    @property
    def cursor(self) -> int:
        return self.cursors[self.current]

    @cursor.setter
    def cursor(self, value: int) -> None:
        self.cursors[self.current] = value

    @property
    def on_free_row(self) -> bool:
        options = self.question.options
        return 0 <= self.cursor < len(options) and options[self.cursor].free

    def answered(self, index: int) -> bool:
        return bool(self.picked[index]) or bool(self.written[index].strip())

    @property
    def complete(self) -> bool:
        return all(self.answered(index) for index in range(len(self.questions)))

    @property
    def given(self) -> int:
        return sum(1 for index in range(len(self.questions)) if self.answered(index))

    # -- moving ------------------------------------------------------------ #

    def move(self, delta: int) -> None:
        """Up and down the options of the current question."""
        count = len(self.question.options)
        if count:
            self.cursor = max(0, min(count - 1, self.cursor + delta))

    def go(self, delta: int) -> None:
        """To the previous or next question."""
        count = len(self.questions)
        if count > 1:
            # Wrapping, because with three tabs the fastest way back to the
            # first is often forwards.
            self.current = (self.current + delta) % count
        self.writing = False

    def next_unanswered(self) -> bool:
        """Move to the next question still needing an answer.

        Returns False when there is none left, which is what tells the caller
        that enter should submit rather than advance.
        """
        count = len(self.questions)
        for step in range(1, count + 1):
            index = (self.current + step) % count
            if not self.answered(index):
                self.current = index
                self.writing = False
                return True
        return False

    # -- answering --------------------------------------------------------- #

    def pick(self) -> None:
        """Choose the option under the cursor."""
        if self.on_free_row:
            self.writing = True
            self.caret = len(self.written[self.current])
            return
        chosen = self.picked[self.current]
        if self.question.multi:
            chosen.symmetric_difference_update({self.cursor})
        else:
            # A single-answer question replaces rather than accumulates, and
            # clears anything typed into the free row: picking a listed option
            # is the user changing their mind about having written one.
            chosen.clear()
            chosen.add(self.cursor)
            self.written[self.current] = ""

    def type_char(self, char: str) -> None:
        text = self.written[self.current]
        self.written[self.current] = text[:self.caret] + char + text[self.caret:]
        self.caret += len(char)
        # Typing an answer is answering. For a single-answer question that
        # means the listed options are no longer chosen.
        if not self.question.multi:
            self.picked[self.current].clear()

    def backspace(self) -> None:
        if self.caret <= 0:
            return
        text = self.written[self.current]
        self.written[self.current] = text[:self.caret - 1] + text[self.caret:]
        self.caret -= 1

    def move_caret(self, delta: int) -> None:
        self.caret = max(0, min(len(self.written[self.current]), self.caret + delta))

    def stop_writing(self) -> None:
        self.writing = False

    # -- the result -------------------------------------------------------- #

    def answers(self) -> list[Answer]:
        out: list[Answer] = []
        for index, question in enumerate(self.questions):
            chosen = [question.options[slot].label
                      for slot in sorted(self.picked[index])
                      if 0 <= slot < len(question.options)
                      and not question.options[slot].free]
            out.append(Answer(header=question.header, prompt=question.prompt,
                              chosen=chosen, written=self.written[index].strip()))
        return out


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #


def render_form(form: Form, width: int, height: int, theme: Theme) -> RenderableType:
    glyphs = theme.glyphs
    blocks: list[RenderableType] = []

    if len(form.questions) > 1:
        blocks.append(_tabs(form, width, theme))
        blocks.append(Text(""))

    prompt = Text(form.question.prompt, style=theme.style("value", bold=True))
    prompt.no_wrap = False
    blocks.append(prompt)
    blocks.append(Text(""))

    for index, option in enumerate(form.question.options):
        blocks.extend(_option_rows(form, index, option, width, theme))

    if form.question.multi:
        blocks.append(Text(""))
        blocks.append(Text("  several answers may apply",
                           style=theme.style("dim")))

    if len(form.questions) > 1:
        blocks.append(Text(""))
        progress = Text("  ", style=theme.style("dim"))
        progress.append(f"{form.given} of {len(form.questions)} answered",
                        style=theme.style("good" if form.complete else "dim"))
        blocks.append(progress)

    _ = height, glyphs
    return Group(*blocks)


def _tabs(form: Form, width: int, theme: Theme) -> RenderableType:
    """The header strip.

    Rendered as one line and allowed to overflow rather than wrap: a tab strip
    that reflows as the user moves along it is one they lose their place in.
    """
    glyphs = theme.glyphs
    row = Text(no_wrap=True, overflow="ellipsis")
    for index, question in enumerate(form.questions):
        here = index == form.current
        done = form.answered(index)
        mark = glyphs.ticked if done else glyphs.unticked
        row.append("  ")
        row.append(f"{mark} ",
                   style=theme.style("good" if done else "dim"))
        row.append(f" {question.header} ",
                   style=theme.style("accent", bold=True, on="border") if here
                   else theme.style("dim"))
    _ = width
    return row


def _option_rows(form: Form, index: int, option, width: int,
                 theme: Theme) -> list[RenderableType]:
    glyphs = theme.glyphs
    here = index == form.cursor
    chosen = index in form.picked[form.current]
    typed = form.written[form.current]

    if option.free:
        chosen = bool(typed.strip())

    mark = glyphs.ticked if chosen else glyphs.unticked
    row = Text(no_wrap=True, overflow="ellipsis")
    row.append(f" {glyphs.arrow} " if here else "   ",
               style=theme.style("accent", bold=True))
    row.append(f"{mark} ", style=theme.style("good" if chosen else "dim"))

    label_style = theme.style("value", bold=True) if here or chosen \
        else theme.style("value")
    if option.free and not form.writing:
        row.append(option.label, style=theme.style("dim"))
        if typed.strip():
            row.append(f"  {typed.strip()}", style=label_style)
    else:
        row.append(option.label, style=label_style)

    rows: list[RenderableType] = [row]

    if option.free and form.writing and here:
        rows.append(_writing_row(form, width, theme))
    elif option.description:
        # Only under the cursor. Every description at once turns five options
        # into fifteen lines, and the panel starts scrolling.
        if here:
            detail = Text("      ", no_wrap=False)
            detail.append(option.description, style=theme.style("dim"))
            rows.append(detail)

    return rows


def _writing_row(form: Form, width: int, theme: Theme) -> RenderableType:
    """The in-place editor, with a visible caret."""
    text = form.written[form.current]
    caret = max(0, min(len(text), form.caret))
    room = max(10, width - 10)

    # Keep the caret on screen in a long answer.
    start = max(0, caret - room + 1)
    window = text[start:start + room]
    at = caret - start

    row = Text("      ", no_wrap=True)
    row.append(window[:at], style=theme.style("value"))
    row.append(window[at] if at < len(window) else " ",
               style=theme.style("value") + Style(reverse=True))
    row.append(window[at + 1:] if at + 1 <= len(window) else "",
               style=theme.style("value"))
    if not text:
        row.append("  type your answer", style=theme.style("dim"))
    return row


def rows_needed(form: Form, width: int) -> int:
    """How many rows the body wants.

    The overlay panel is otherwise a fixed height, which for a permission
    prompt is right — it has a diff in it and wants the room. A three-question
    form is a dozen rows, and given forty it drew twelve and then twenty-eight
    blank ones with a border round them.

    An estimate, not a measurement: the exact figure needs a console to wrap
    against, and the cost of being one row out is one row of padding.
    """
    rows = 0
    if len(form.questions) > 1:
        rows += 2                                    # the strip and a blank

    room = max(20, width)
    rows += max(1, -(-len(form.question.prompt) // room))
    rows += 1                                        # blank after the prompt

    for index, option in enumerate(form.question.options):
        rows += 1
        here = index == form.cursor
        if option.free and form.writing and here:
            rows += 1
        elif option.description and here:
            rows += max(1, -(-len(option.description) // max(20, room - 6)))

    if form.question.multi:
        rows += 2
    if len(form.questions) > 1:
        rows += 2                                    # the progress line
    return rows


def form_hint(form: Form, theme: Theme) -> str:
    """The footer line.

    Built from the theme's glyphs rather than written with literal arrows: on a
    terminal that cannot draw them the whole hint has to degrade with
    everything else, and a hint pointing at keys the user cannot see drawn is
    worse than no hint.
    """
    glyphs = theme.glyphs
    if form.writing:
        return f" type {glyphs.dot} enter done {glyphs.dot} esc back "
    parts = [f"{glyphs.rise}{glyphs.fall} move"]
    if len(form.questions) > 1:
        parts.append(f"{glyphs.left}{glyphs.right} question")
    parts.append("space pick")
    parts.append("enter next" if not form.complete else "enter send")
    parts.append("esc cancel")
    return " " + f" {glyphs.dot} ".join(parts) + " "
