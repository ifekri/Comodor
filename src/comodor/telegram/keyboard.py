"""The buttons, and the words on them.

Everything Comodor can be asked to do from Telegram is a button. Typing is for
the task itself; nothing else should require somebody to remember a command,
because the whole reason to use this instead of the terminal is that they are
not at a terminal — they are on a phone, and a phone is a bad place to
remember syntax.

Two rules the layouts follow.

*Every button says what happens, not what it is.* `Stop` rather than
`interrupt`, `Approve once` rather than `allow`. A label that names an internal
concept is a label somebody has to translate.

*Nothing lands more than two taps deep, and every screen has a way back.* A
menu somebody can get lost in is worse than a command they have to remember,
because at least the command has documentation.

**Callback data is limited to sixty-four bytes**, which is the constraint that
shapes the naming. Every action is a short verb and an argument, and anything
that cannot fit — a folder path, a model id — is held in a table on our side
and referred to by a key.
"""

from __future__ import annotations

from typing import Any

#: One screen's worth. Telegram will render more, but a keyboard taller than
#: this pushes the message it belongs to off a phone screen.
MOST_ROWS = 8

MODES = ("act", "plan", "chat")

MODE_WORDS = {
    "act": "Act — edits files, runs commands",
    "plan": "Plan — reads only, changes nothing",
    "chat": "Chat — no tools at all",
}


def button(text: str, action: str) -> dict[str, str]:
    """One inline button.

    The callback payload is checked here rather than at the point it is
    tapped: Telegram silently refuses to *send* a keyboard whose data is too
    long, so the failure appears as a message with no buttons under it and
    nothing in any log.
    """
    payload = action.encode("utf-8")
    if len(payload) > 64:
        raise ValueError(f"callback data is {len(payload)} bytes: {action!r}")
    return {"text": text, "callback_data": action}


def rows(*lines: list[dict[str, str]]) -> dict[str, Any]:
    return {"inline_keyboard": [line for line in lines if line]}


def link(text: str, url: str) -> dict[str, str]:
    return {"text": text, "url": url}


# --------------------------------------------------------------------------- #
# the main screen
# --------------------------------------------------------------------------- #


def main_menu(*, busy: bool, mode: str, rules: int = 0,
              model: str = "") -> dict[str, Any]:
    """What is offered when nothing else is happening.

    The first row changes with the state rather than being disabled: a button
    that is present and does nothing is the most confusing control there is, so
    while a turn is running the only thing offered is stopping it.
    """
    if busy:
        top = [button("⏹  Stop", "stop")]
    else:
        top = [button("✳  New chat", "new"),
               button("↺  History", "chats")]

    # The settings people need are on this screen, not behind Settings. The
    # first thing somebody does with a new bot is find out what it is pointed
    # at and change it — which model, which folder, what it is allowed to do —
    # and a first screen that hides all three behind one button asks them to
    # guess that it is there.
    return rows(
        top,
        [button(f"◐  Mode · {mode.capitalize()}", "mode"),
         button("◈  Status", "status")],
        [button(f"◆  Model{f' · {model}' if model else ''}"[:60], "models"),
         button("▤  Folder", "folder")],
        [button("✦  Skills", "skills"),
         button(f"⌗  Rules{f' · {rules}' if rules else ''}", "rules")],
        [button("⚙  Settings", "settings"),
         button("?  Help", "help")],
    )


def mode_menu(current: str) -> dict[str, Any]:
    """Which mode, with what each one means written out.

    The names alone are not self-explanatory — "plan" could as easily mean
    "make a plan and carry it out" — and this is the setting that decides
    whether the next message edits somebody's files.
    """
    lines = []
    for name in MODES:
        mark = "●" if name == current else "○"
        lines.append([button(f"{mark}  {MODE_WORDS[name]}", f"mode:{name}")])
    lines.append([button("←  Back", "menu")])
    return rows(*lines)


def settings_menu(*, provider: str, model: str, folder: str) -> dict[str, Any]:
    return rows(
        [button(f"◈  {provider} / {model}"[:60], "models")],
        [button("▤  Change folder", "folder")],
        [button("⌗  Rules", "rules"), button("✦  Skills", "skills")],
        [button("⚙  What it may do", "writes")],
        [button("◔  Cost this session", "cost")],
        [button("←  Back", "menu")],
    )


# --------------------------------------------------------------------------- #
# things the agent asks
# --------------------------------------------------------------------------- #


def permission(request_id: str) -> dict[str, Any]:
    """Approve, approve-for-the-session, or refuse.

    Three, in the order of increasing commitment, and the widest commitment is
    never the first thing under a thumb. On a phone the buttons are close
    together and a mis-tap on "always" is not undoable.
    """
    return rows(
        [button("✓  Yes, once", f"ok:{request_id}")],
        [button("✓✓  Yes, and stop asking this session",
                f"okall:{request_id}")],
        [button("✗  No", f"no:{request_id}")],
    )


def question(request_id: str, index: int, options: list[str],
             chosen: set[int] | None = None,
             multi: bool = False) -> dict[str, Any]:
    """One question from the `ask` tool, as a column of options.

    A column rather than a grid: the options are sentences, and two sentences
    side by side on a phone are two columns of three words each.
    """
    chosen = chosen or set()
    lines = []
    for slot, label in enumerate(options):
        mark = ("☑" if slot in chosen else "☐") if multi else \
               ("●" if slot in chosen else "○")
        lines.append([button(f"{mark}  {label}"[:60],
                             f"q:{request_id}:{index}:{slot}")])
    lines.append([button("✎  Write my own", f"qw:{request_id}:{index}")])
    if multi or chosen:
        lines.append([button("→  Send", f"qs:{request_id}")])
    return rows(*lines)


# --------------------------------------------------------------------------- #
# lists
# --------------------------------------------------------------------------- #


def picker(action: str, items: list[tuple[str, str]], *, back: str = "menu",
           page: int = 0, per_page: int = 6) -> dict[str, Any]:
    """A paged list of things to choose between.

    Paged because Telegram will happily render eighty buttons and nobody will
    scroll them. Six is what fits above the keyboard on a phone.
    """
    start = page * per_page
    window = items[start:start + per_page]
    lines = [[button(label[:60], f"{action}:{key}"[:64])]
             for key, label in window]

    steps = []
    if page > 0:
        steps.append(button("‹  Previous", f"page:{action}:{page - 1}"))
    if start + per_page < len(items):
        steps.append(button("Next  ›", f"page:{action}:{page + 1}"))
    if steps:
        lines.append(steps)

    lines.append([button("←  Back", back)])
    return rows(*lines)


def confirm(action: str, *, back: str = "menu") -> dict[str, Any]:
    """For anything that cannot be undone."""
    return rows(
        [button("✓  Yes, do it", action), button("✗  Cancel", back)],
    )


def just_back(where: str = "menu") -> dict[str, Any]:
    return rows([button("←  Back", where)])


# --------------------------------------------------------------------------- #
# what the slash menu offers
# --------------------------------------------------------------------------- #

#: Registered with Telegram so they appear as somebody types `/`. Deliberately
#: short: the buttons are the interface, and a command list that mirrors every
#: button is two things to keep in step.
COMMANDS: list[tuple[str, str]] = [
    ("start", "Open the menu"),
    ("new", "Start a fresh conversation"),
    ("stop", "Interrupt what is running"),
    ("mode", "Act, plan, or chat"),
    ("status", "Model, folder, cost, context"),
    ("help", "What this bot can do"),
]
