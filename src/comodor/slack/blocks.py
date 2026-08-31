"""The buttons, in Block Kit.

Slack is the roomiest of the three channels: a message can be edited, buttons
sit in rows of up to five, and there is no twenty-character label limit. So the
layout is closest to Telegram's — everything on one screen, nothing nested two
menus deep.

Two limits that are real and worth respecting rather than discovering:

*A `block_id`/`action_id` is 255 characters and an action `value` is 2000.*
Roomy, but the same rule applies as everywhere else here: a model id or a
session id is referred to by its position in a list held on our side, because
a list that has moved on must fail loudly rather than act on the wrong row.

*Twenty-five elements per actions block, fifty blocks per message.* Nothing
here comes close, and the paging below keeps it that way.

Slack renders `mrkdwn`, not Markdown: `*bold*` rather than `**bold**`, and
`_italic_`. Sending Markdown to Slack prints the asterisks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Buttons per row before Slack starts wrapping them oddly on a narrow window.
PER_ROW = 3

#: One page of a long list. Slack will render more; a person will not read it.
PAGE = 8

MODES = ("act", "plan", "ask", "chat")

MODE_WORDS = {
    "act": "Act",
    "plan": "Plan",
    "ask": "Ask",
    "chat": "Chat",
}

MODE_NOTES = {
    "act": "edits files, runs commands",
    "plan": "reads only, changes nothing",
    "ask": "reads only, answers questions",
    "chat": "no tools at all",
}


@dataclass(frozen=True)
class Choice:
    """One button: what it says, and what it means."""

    key: str
    label: str

    def as_button(self, style: str = "") -> dict[str, Any]:
        button: dict[str, Any] = {
            "type": "button",
            "text": {"type": "plain_text", "text": self.label[:75],
                     "emoji": True},
            "action_id": self.key[:255],
            "value": self.key[:2000],
        }
        if style in ("primary", "danger"):
            button["style"] = style
        return button


def section(text: str) -> dict[str, Any]:
    return {"type": "section",
            "text": {"type": "mrkdwn", "text": text[:3000]}}


def context(text: str) -> dict[str, Any]:
    return {"type": "context",
            "elements": [{"type": "mrkdwn", "text": text[:3000]}]}


def divider() -> dict[str, Any]:
    return {"type": "divider"}


def actions(choices: list[Choice], styles: dict[str, str] | None = None,
            per_row: int = PER_ROW) -> list[dict[str, Any]]:
    """One or more actions blocks, wrapped at `per_row`."""
    styles = styles or {}
    rows: list[dict[str, Any]] = []
    for start in range(0, len(choices), per_row):
        window = choices[start:start + per_row]
        rows.append({"type": "actions",
                     "elements": [choice.as_button(styles.get(choice.key, ""))
                                  for choice in window]})
    return rows


# --------------------------------------------------------------------------- #
# the main screen
# --------------------------------------------------------------------------- #


def main_menu(*, busy: bool, mode: str, rules: int = 0, model: str = "",
              writes: bool = False, body: str = "") -> list[dict[str, Any]]:
    """What is offered when nothing else is happening.

    While a turn is running the only thing on offer is stopping it — a button
    that is present and does nothing is the most confusing control there is.
    """
    blocks: list[dict[str, Any]] = []
    if body:
        blocks.append(section(body))

    if busy:
        blocks += actions([Choice("stop", "Stop")], {"stop": "danger"})
        return blocks

    blocks += actions([
        Choice("new", "New chat"),
        Choice("chats", "History"),
        Choice("mode", f"Mode · {MODE_WORDS.get(mode, mode)}"),
        Choice("status", "Status"),
        Choice("models", f"Model · {model}" if model else "Model"),
        Choice("folder", "Folder"),
        Choice("skills", "Skills"),
        Choice("rules", f"Rules · {rules}" if rules else "Rules"),
        Choice("writes", "What it may do"),
        Choice("help", "Help"),
    ])
    blocks.append(context(
        ("*Act* — it may edit files and run commands" if writes
         else "*Reading only* — it will not edit a file from here")
        + "   ·   just type a task"))
    return blocks


def mode_menu(current: str) -> list[dict[str, Any]]:
    lines = ["*Mode*\nWhat the next message is allowed to do.\n"]
    for name in MODES:
        mark = "●" if name == current else "○"
        lines.append(f"{mark} *{MODE_WORDS[name]}* — {MODE_NOTES[name]}")
    blocks = [section("\n".join(lines))]
    blocks += actions([Choice(f"mode:{name}",
                              ("● " if name == current else "")
                              + MODE_WORDS[name])
                       for name in MODES])
    blocks += actions([Choice("menu", "← Back")])
    return blocks


def permission(request_id: str, what: str) -> list[dict[str, Any]]:
    """Approve, approve-for-the-session, or refuse.

    In that order, with the widest commitment in the middle rather than under
    the thumb — and "No" styled, because the destructive-looking button being
    the safe one is a habit worth not forming.
    """
    return [
        section(f"*Comodor wants to*\n{what}"),
        *actions([Choice(f"ok:{request_id}", "Yes, once"),
                  Choice(f"okall:{request_id}", "Yes, all session"),
                  Choice(f"no:{request_id}", "No")],
                 {f"ok:{request_id}": "primary", f"no:{request_id}": "danger"}),
    ]

def mode_choices(request_id: str, what: str,
                 options: list[str]) -> list[dict[str, Any]]:
    """The modes a proposal offered, as buttons built from the request.

    What the agent offered is what is shown, in the order it offered them,
    with the proposal first — the same shapes as the request, not a
    reinvention of the mode list.
    """
    return [
        section(f"*Comodor suggests a mode change*\n{what}"),
        *actions([Choice(f"mm:{request_id}:{option}",
                         ("● " if index == 0 else "") + MODE_WORDS.get(option, option))
                  for index, option in enumerate(options)]),
    ]


def question(request_id: str, index: int, prompt: str, options: list[str],
             chosen: set[int] | None = None, multi: bool = False,
             total: int = 1) -> list[dict[str, Any]]:
    """One question from the `ask` tool, as a column of buttons."""
    chosen = chosen or set()
    head = f"*{prompt}*"
    if total > 1:
        head += f"\n_{index + 1} of {total}_"

    picks = []
    for slot, label in enumerate(options[:20]):
        mark = ("☑ " if slot in chosen else "☐ ") if multi else \
               ("● " if slot in chosen else "")
        picks.append(Choice(f"q:{request_id}:{index}:{slot}",
                            f"{mark}{label}"[:75]))

    blocks = [section(head)]
    blocks += actions(picks, per_row=1 if any(len(o) > 24 for o in options)
                      else 2)
    tail = [Choice(f"qw:{request_id}:{index}", "✎ Write my own")]
    if multi or chosen:
        tail.append(Choice(f"qs:{request_id}", "Send"))
    blocks += actions(tail, {f"qs:{request_id}": "primary"})
    return blocks


# --------------------------------------------------------------------------- #
# lists
# --------------------------------------------------------------------------- #


def page(action: str, items: list[tuple[str, str]], *, body: str,
         page_number: int = 0, back: str = "menu") -> list[dict[str, Any]]:
    """One screenful of a longer list, with its own way forward and back.

    `items` is `(key, label)` where the key is a position, not an id: a list
    that has moved on has to fail loudly rather than act on whatever is now in
    that row.
    """
    start = page_number * PAGE
    window = items[start:start + PAGE]

    blocks = [section(body)]
    blocks += actions([Choice(f"{action}:{key}", label[:75])
                       for key, label in window], per_row=2)

    steps = []
    if page_number > 0:
        steps.append(Choice(f"page:{action}:{page_number - 1}", "‹ Previous"))
    if start + PAGE < len(items):
        steps.append(Choice(f"page:{action}:{page_number + 1}", "Next ›"))
    steps.append(Choice(back, "← Back"))
    blocks += actions(steps)

    if len(items) > PAGE:
        shown = min(start + PAGE, len(items))
        blocks.append(context(f"{start + 1}–{shown} of {len(items)}"))
    return blocks
