"""The task list the agent keeps for itself.

This is the tool behind the left-hand History panel. It exists for two reasons
that have nothing to do with pretty output: writing the plan down keeps a long
autonomous run from drifting off task, and it gives the person watching a way to
see what the agent thinks it is doing — and to stop it early if that is wrong.
"""

from __future__ import annotations

from typing import Any

from ..events import Kind
from ..safety import Risk
from .base import Tool, ToolContext, ToolResult, TodoItem

VALID_STATES = ("pending", "active", "done", "blocked")


class TodoWrite(Tool):
    name = "todo_write"
    description = (
        "Record or update the task list for the current job. Send the complete list "
        "every time. Mark exactly one item 'active' while you work on it, then 'done'. "
        "Use this for any task that takes more than a couple of steps."
    )
    risk = Risk.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "The full task list, in order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "state": {
                            "type": "string",
                            "enum": list(VALID_STATES),
                            "description": "pending, active, done or blocked.",
                        },
                    },
                    "required": ["text"],
                },
            }
        },
        "required": ["items"],
    }

    def summary(self, args: dict[str, Any]) -> str:
        items = args.get("items") or []
        done = sum(1 for item in items if isinstance(item, dict)
                   and item.get("state") == "done")
        return f"update task list ({done}/{len(items)} done)"

    def run(self, ctx: ToolContext, items: list[dict[str, Any]], **_: Any) -> ToolResult:
        if not isinstance(items, list):
            return ToolResult.failure("items must be a list of {text, state} objects")

        parsed: list[TodoItem] = []
        for entry in items:
            if isinstance(entry, str):
                parsed.append(TodoItem(text=entry))
                continue
            if not isinstance(entry, dict) or not entry.get("text"):
                continue
            state = str(entry.get("state", "pending")).lower()
            if state not in VALID_STATES:
                state = "pending"
            parsed.append(TodoItem(text=str(entry["text"]), state=state))

        if not parsed:
            return ToolResult.failure("no valid task items were provided")

        active = [item for item in parsed if item.state == "active"]
        if len(active) > 1:
            # Not fatal, but worth telling the model: two "in progress" items
            # usually means it lost track of where it was.
            note = " (note: more than one item is marked active)"
        else:
            note = ""

        ctx.todos[:] = parsed
        ctx.bus.emit(Kind.TODO, items=[{"text": item.text, "state": item.state}
                                       for item in parsed])

        done = sum(1 for item in parsed if item.state == "done")
        listing = "\n".join(f"{item.icon} {item.text}" for item in parsed)
        return ToolResult.success(
            content=f"Task list updated — {done}/{len(parsed)} done.{note}\n{listing}",
            display=listing, total=len(parsed), done=done,
        )
