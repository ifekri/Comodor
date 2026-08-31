"""Putting the plan back in front of the model after the context that held it
is gone.

`todo_write` already exists, and the agent uses it. But the list it writes went
to two places and neither of them was the model: `ctx.todos`, which only the
sidebar reads, and a tool result in the transcript. Compaction summarises old
messages away, and the tool result goes with them — so on a long job the plan
quietly stopped being something the model could see, at exactly the point the
job was long enough to need one. The list was still in memory the whole time.
Nothing ever showed it again.

That is what this fixes, and it is deliberately the smaller half of the idea.
The plan does not need to be rebuilt or re-derived: it survives compaction
already, as a plain Python list. It only needs saying out loud.

**Where it is put.** Appended, as a new message, after compaction has run. Not
in the system prompt: that prefix is what the provider's cache matches on, and
a system prompt that changes whenever a checkbox is ticked would miss the cache
on every request of every turn. Measured against two live endpoints a repeated
prefix comes back over 99% cached, so that is not a small thing to give up.
Appending costs the cache nothing, and after compaction it costs nothing at
all, because compaction has already rewritten the history.
"""

from __future__ import annotations

from typing import Any, Iterable

#: Below this, nothing is re-injected. One or two items is not a plan, and a
#: reminder about it would cost more than it carries.
WORTH_IT = 3

#: A plan longer than this is reported by its shape rather than in full. A
#: fifty-item list re-injected whole is a large message arriving at the moment
#: the context is already under pressure, which is the opposite of the point.
MOST = 25

#: Deliberately not the sidebar's icons. Those are chosen to be legible in a
#: terminal at a glance; these are chosen to be unambiguous to a model that has
#: seen a million Markdown checklists.
MARKS = {"done": "[x]", "active": "[>]", "blocked": "[!]", "pending": "[ ]"}

HEADING = (
    "The task list as it stands. Earlier messages have just been summarised, "
    "so this is repeated here rather than left in history that no longer "
    "exists."
)

FOOTING = (
    "Carry on from the item marked [>]. If the list no longer describes the "
    "job, correct it with todo_write rather than working around it."
)


def render(todos: Iterable[Any]) -> str:
    """The plan as a message, or an empty string if there is no point.

    Takes anything with `text` and `state` — the live `TodoItem`s the tool
    keeps, or the plain dictionaries the session file stores.
    """
    items = [(_text(item), _state(item)) for item in todos or ()]
    items = [(text, state) for text, state in items if text]
    if len(items) < WORTH_IT:
        return ""

    done = sum(1 for _, state in items if state == "done")
    lines = [HEADING, "", f"{done}/{len(items)} done."]

    shown = items[:MOST]
    lines.append("")
    lines.extend(f"{MARKS.get(state, MARKS['pending'])} {text}"
                 for text, state in shown)
    if len(items) > MOST:
        lines.append(f"... and {len(items) - MOST} more.")

    lines.extend(["", FOOTING])
    return "\n".join(lines)


def _text(item: Any) -> str:
    value = item.get("text") if isinstance(item, dict) else getattr(item, "text", "")
    return str(value or "").strip()


def _state(item: Any) -> str:
    value = item.get("state") if isinstance(item, dict) else getattr(item, "state", "")
    state = str(value or "pending").lower()
    return state if state in MARKS else "pending"


def as_records(todos: Iterable[Any]) -> list[dict[str, str]]:
    """The list in the form the session file keeps, so it survives the process.

    Compaction is not the only way the plan is lost — closing the terminal is
    the other one, and `--resume` brought the messages back without it.
    """
    records = []
    for item in todos or ():
        text = _text(item)
        if text:
            records.append({"text": text, "state": _state(item)})
    return records
