"""The buttons, inside limits that are much tighter than Telegram's.

Telegram will draw eleven inline buttons in a grid and let each label run to a
sentence. WhatsApp allows **three** reply buttons of twenty characters, or one
button that opens a sheet of **ten** rows. That is the whole design constraint,
and pretending otherwise produces messages Meta rejects outright — which
arrives as a bot that answers nothing, with the reason only in a log.

So there are two shapes and a rule for choosing between them:

*Three or fewer, and each label short* — reply buttons, which sit under the
message and are one tap.

*Anything longer* — a list, which costs a tap to open but holds ten rows with a
line of description each.

The main menu is a list, and it is exactly ten rows: everything Telegram puts
on its first screen, minus the *Settings* button, because on a screen this
narrow a menu that leads to another menu is worse than one flat list.

**Paging is part of the ten.** A list showing eight things plus *Previous* and
*Next* is at the limit, so `page` takes eight and never nine.
"""

from __future__ import annotations

from dataclasses import dataclass

from .api import MOST_BUTTONS, MOST_ROWS

#: Rows kept back for navigation, so a page of items plus its arrows fits.
NAVIGATION = 2
PAGE = MOST_ROWS - NAVIGATION

MODES = ("act", "plan", "chat")

MODE_WORDS = {
    "act": "Act",
    "plan": "Plan",
    "chat": "Chat",
}

MODE_NOTES = {
    "act": "Edits files, runs commands",
    "plan": "Reads only, changes nothing",
    "chat": "No tools at all",
}


@dataclass(frozen=True)
class Row:
    """One line of a list message."""

    key: str
    title: str
    note: str = ""

    def as_tuple(self) -> tuple[str, str, str]:
        return self.key, self.title, self.note


def main_menu(*, busy: bool, mode: str, rules: int = 0,
              model: str = "", writes: bool = False) -> list[Row]:
    """What is offered when nothing else is happening.

    Ten rows, which is the limit. When a turn is running the only thing on
    offer is stopping it — a button that is present and does nothing is the
    most confusing control there is, and on WhatsApp there is no room to keep
    it around greyed out.
    """
    if busy:
        return [Row("stop", "Stop", "Interrupt what it is doing")]

    return [
        Row("new", "New chat", "Forget the conversation so far"),
        Row("chats", "History", "Re-open an earlier conversation"),
        Row("mode", f"Mode · {MODE_WORDS.get(mode, mode).capitalize()}",
            MODE_NOTES.get(mode, "What it is allowed to do")),
        Row("status", "Status", "Model, folder, context, spend"),
        Row("models", f"Model · {model}" if model else "Model",
            "Switch to another one"),
        Row("folder", "Folder", "Which project it works in"),
        Row("skills", "Skills", "Procedures it follows"),
        Row("rules", f"Rules · {rules}" if rules else "Rules",
            "What it learned from your corrections"),
        Row("writes", "What it may do",
            "Edits files and runs commands" if writes
            else "Reads and plans only"),
        Row("help", "Help", "What everything here does"),
    ]


def mode_menu(current: str) -> list[tuple[str, str]]:
    """Three modes, three reply buttons. It fits exactly.

    The twenty-character limit is why the explanation is not on the button: a
    label reading "Plan — reads only, ch" is worse than one reading "Plan" with
    the sentence in the message above it.
    """
    return [(f"mode:{name}",
             ("● " if name == current else "") + MODE_WORDS[name])
            for name in MODES]


def mode_body(current: str) -> str:
    lines = ["*Mode*", "", "What the next message is allowed to do.", ""]
    for name in MODES:
        mark = "●" if name == current else "○"
        lines.append(f"{mark} *{MODE_WORDS[name]}* — {MODE_NOTES[name]}")
    return "\n".join(lines)


def permission(request_id: str) -> list[tuple[str, str]]:
    """Approve, approve-for-the-session, or refuse.

    Three, and the widest commitment is never first. On a phone the buttons sit
    side by side and a mis-tap on "always" is not undoable.
    """
    return [
        (f"ok:{request_id}", "Yes, once"),
        (f"okall:{request_id}", "Yes, all session"),
        (f"no:{request_id}", "No"),
    ]


def question(request_id: str, index: int, options: list[str],
             chosen: set[int] | None = None,
             multi: bool = False) -> tuple[str, list[Row]]:
    """One question from the `ask` tool.

    Returns the label for the button that opens the sheet, and the rows. Always
    a list rather than buttons even when there are two options: the options are
    sentences, and a sentence does not fit in twenty characters.
    """
    chosen = chosen or set()
    rows = []
    for slot, label in enumerate(options[:MOST_ROWS - 1]):
        mark = ("☑ " if slot in chosen else "") if multi else \
               ("● " if slot in chosen else "")
        rows.append(Row(f"q:{request_id}:{index}:{slot}",
                        f"{mark}{label}"[:24], label[:72]))
    rows.append(Row(f"qw:{request_id}:{index}", "Write my own",
                    "Type an answer instead of choosing"))
    return "Choose", rows


def page(action: str, items: list[Row], *, back: str = "menu",
         page_number: int = 0) -> list[Row]:
    """One screenful of a longer list, with its own way forward and back.

    Ten rows including the arrows, so eight items — the arithmetic that Meta
    enforces by rejecting the whole message.
    """
    start = page_number * PAGE
    window = list(items[start:start + PAGE])

    if page_number > 0:
        window.append(Row(f"page:{action}:{page_number - 1}", "‹ Previous",
                          "The page before this one"))
    if start + PAGE < len(items):
        window.append(Row(f"page:{action}:{page_number + 1}", "Next ›",
                          "More of them"))
    if len(window) < MOST_ROWS:
        window.append(Row(back, "← Back", "The main menu"))
    return window[:MOST_ROWS]


def confirm(action: str, back: str = "menu") -> list[tuple[str, str]]:
    """For anything that cannot be undone."""
    return [(action, "Yes, do it"), (back, "Cancel")]


def fits_as_buttons(choices: list[tuple[str, str]]) -> bool:
    """Whether this set can be reply buttons rather than a list.

    Three at most, and every label short enough to survive intact — a label
    that has to be cut to twenty characters to fit is a label that should have
    been a list row with its description underneath.
    """
    from .api import BUTTON_TITLE

    return (1 <= len(choices) <= MOST_BUTTONS
            and all(len(label) <= BUTTON_TITLE for _, label in choices))
