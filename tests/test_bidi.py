"""Right-to-left text in a left-to-right interface.

The terminal runs the Unicode bidirectional algorithm over each line it is
given, and it is good at it. Nothing here reimplements any of that. What is
tested is the one thing the *application* has to get right: stopping that
algorithm reaching across a boundary between our text and somebody else's.

A line of this interface is usually half ours and half theirs — `learned` then
a rule they wrote, `edit` then a path, a glyph then a task title — and bidi has
no idea which half is which. The neutral characters in between, the spaces and
the dots in a filename, resolve against whichever side wins, and the line comes
out scrambled.
"""

from __future__ import annotations

import pytest
from rich.cells import cell_len

from comodor.ui.bidi import FSI, PDI, direction, has_rtl, is_rtl, isolate, strip

PERSIAN = "یک تست بنویس"
ARABIC = "أضف نقطة نهاية"
HEBREW = "הוסף בדיקה"
ENGLISH = "add a test"


# --------------------------------------------------------------------------- #
# which way does it read
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("text, expected", [
    (PERSIAN, "rtl"),
    (ARABIC, "rtl"),
    (HEBREW, "rtl"),
    (ENGLISH, "ltr"),
    ("src/app.py", "ltr"),
    ("", "neutral"),
    ("123 456", "neutral"),          # digits are not strong in either direction
    ("  ...  ", "neutral"),
])
def test_which_way_a_string_reads(text, expected):
    assert direction(text) == expected


def test_direction_comes_from_the_first_strong_character():
    """Which is the rule the terminal's own algorithm uses.

    Anything else here — a majority vote, say — would disagree with what the
    terminal is about to do, and disagreeing is worse than not looking.
    """
    assert is_rtl(f"{PERSIAN} and some English after it")
    assert not is_rtl(f"English first, then {PERSIAN}")


def test_a_line_that_opens_with_punctuation_takes_the_next_strong_character():
    assert direction(f'"{PERSIAN}"') == "rtl"
    assert direction(f'"{ENGLISH}"') == "ltr"


@pytest.mark.parametrize("text, expected", [
    (PERSIAN, True),
    (f"the file {ARABIC}.py", True),
    (ENGLISH, False),
    ("", False),
])
def test_whether_there_is_any_rtl_in_here_at_all(text, expected):
    assert has_rtl(text) is expected


# --------------------------------------------------------------------------- #
# fencing
# --------------------------------------------------------------------------- #


def test_a_field_that_needs_a_fence_gets_one():
    fenced = isolate(PERSIAN)

    assert fenced.startswith(FSI)
    assert fenced.endswith(PDI)
    assert strip(fenced) == PERSIAN


def test_ascii_is_left_exactly_as_it_was():
    """A line of English cannot be reordered, so fencing it costs two
    codepoints to protect against nothing — and makes every snapshot test in
    the suite unreadable."""
    assert isolate(ENGLISH) == ENGLISH
    assert isolate("") == ""
    assert isolate("src/app.py") == "src/app.py"


def test_the_fence_is_free():
    """It has to be. Every width in the layout is computed from `cell_len`,
    and a mark that measured one cell would push the right-hand column of every
    line containing Persian one place over."""
    assert cell_len(FSI) == 0
    assert cell_len(PDI) == 0
    assert cell_len(isolate(PERSIAN)) == cell_len(PERSIAN)


def test_fencing_twice_does_not_nest():
    once = isolate(PERSIAN)

    assert strip(isolate(once)) == PERSIAN


# --------------------------------------------------------------------------- #
# where it is applied
# --------------------------------------------------------------------------- #


def test_a_task_title_is_trimmed_before_it_is_fenced():
    """Truncating an isolated string throws away its closing mark, and an
    unbalanced isolate leaks into the rest of the line — which is worse than
    never fencing it."""
    from rich.console import Console

    from comodor.ui.layout import Rect
    from comodor.ui.theme import load
    from comodor.ui.widgets.history import HistoryModel, render_history

    long_title = PERSIAN * 6
    model = HistoryModel(todos=[{"text": long_title, "state": "active"}])
    console = Console(file=None, width=30, no_color=True)
    with console.capture() as captured:
        console.print(render_history(model, Rect(0, 0, 24, 10), load("ember")))
    output = captured.get()

    assert output.count(FSI) == output.count(PDI), "an isolate was left open"


def test_the_verb_and_the_rule_are_fenced_apart():
    """`learned` is ours and reads left to right; what follows may not be."""
    from rich.console import Console

    from comodor.ui.theme import load
    from comodor.ui.widgets.chat import Entry, render_entry

    entry = Entry("memory", PERSIAN, meta={"verb": "learned"})
    console = Console(file=None, width=60, no_color=True)
    with console.capture() as captured:
        console.print(render_entry(entry, load("ember"), 60))
    output = captured.get()

    assert FSI in output and PDI in output
    assert "learned" in strip(output)


def transcript(*entries) -> list[str]:
    """The real path: entries, through the screen, onto a fixed-size console."""
    import io as io_module
    import re

    from rich.console import Console

    from comodor.ui import layout as layout_module
    from comodor.ui import theme as theme_module
    from comodor.ui.screen import Screen, ScreenState

    theme = theme_module.load("ember")
    buffer = io_module.StringIO()
    console = Console(file=buffer, width=90, height=20, theme=theme.rich_theme(),
                      force_terminal=True, color_system="truecolor",
                      legacy_windows=False, highlight=False, soft_wrap=False)
    console.print(Screen(console, theme).render(
        ScreenState(entries=list(entries)), layout_module.compute(90, 20)))
    return re.sub('\x1b' + r"\[[0-9;:?]*[a-zA-Z]", "",
                  buffer.getvalue()).splitlines()


def test_a_right_to_left_exchange_is_set_to_the_right_margin():
    """Where a Persian reader's line begins. Left-aligning it is the equivalent
    of setting an English paragraph against the wrong margin: legible, and
    obviously not meant for you."""
    from comodor.ui.widgets.chat import Entry

    rows = transcript(Entry("user", PERSIAN),
                      Entry("assistant", "می‌توانم انجام دهم."),
                      Entry("user", ENGLISH),
                      Entry("assistant", "I can do that."))

    persian = [row for row in rows if strip(row).strip().endswith(PERSIAN)]
    english = [row for row in rows if row.strip().endswith(ENGLISH)]

    assert persian and english
    assert persian[0].startswith("  " + " " * 20), "the question was left-aligned"
    assert english[0].lstrip().startswith("›"), "English was moved"

    reply = [row for row in rows if "می‌توانم" in row][0]
    assert reply.startswith(" " * 20), "the answer was left-aligned"


def test_a_code_block_inside_a_persian_answer_stays_where_code_belongs():
    """A Persian explanation of a Python function belongs on the right. The
    function does not."""
    from comodor.ui.widgets.chat import Entry

    answer = "\n".join(["این تابع را اضافه کن:", "", "```python", "x = 1", "```"])
    rows = transcript(Entry("assistant", answer))
    code = [row for row in rows if "x = 1" in row]

    assert code, "the code block vanished"
    # Inside its frame, at the left of the column, exactly as in an English answer.
    assert code[0].index("x = 1") < 45


def test_the_whole_interface_still_measures_correctly_with_persian_in_it():
    """The fence is invisible; the layout must not notice it is there."""
    import io as io_module

    from rich.console import Console

    from comodor.ui import layout as layout_module
    from comodor.ui import theme as theme_module
    from comodor.ui.screen import Screen, ScreenState
    from comodor.ui.widgets.chat import Entry
    from comodor.ui.widgets.history import HistoryModel

    theme = theme_module.load("ember")
    buffer = io_module.StringIO()
    console = Console(file=buffer, width=100, height=24, theme=theme.rich_theme(),
                      force_terminal=True, color_system="truecolor",
                      legacy_windows=False, highlight=False, soft_wrap=False)

    state = ScreenState(
        entries=[Entry("user", PERSIAN),
                 Entry("assistant", "می‌توانم. اول فایل را می‌خوانم."),
                 Entry("memory", PERSIAN, meta={"verb": "learned"})],
        history=HistoryModel(todos=[{"text": PERSIAN, "state": "active"}]),
    )
    console.print(Screen(console, theme).render(state, layout_module.compute(100, 24)))

    import re

    rows = re.sub(r"\x1b\[[0-9;:?]*[a-zA-Z]", "", buffer.getvalue()).splitlines()
    assert len(rows) <= 24
    for row in rows:
        assert cell_len(row) <= 100, f"{cell_len(row)} cells in 100 columns"
