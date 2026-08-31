"""Let the agent read and curate its own memory shelf.

The facts table is what the model sees at the top of every turn, so it is
also the one part of memory the model should be able to maintain: a
correction the user just stated ("that database is Postgres, not MySQL")
should land as a fact while the conversation still holds it, not wait for a
background pass to rediscover it.

The tool is SAFE on purpose. Writing a fact changes no file, runs no command,
and every fact is visible in the briefing block, in /memory and in the web
panel — the writes are their own audit. The real guards are the caps and the
duplicate rule in the facts service: the model cannot grow the memory, only
curate it, and a full shelf comes back as an error listing the entries so
the next call replaces or removes instead of retrying the same add.
"""

from __future__ import annotations

from typing import Any

from ..safety import Risk
from .base import Tool, ToolContext, ToolResult

ACTIONS = ("add", "replace", "remove", "list")


class Memory(Tool):
    """Add, replace, remove or list the curated facts."""

    name = "memory"
    risk = Risk.SAFE
    description = (
        "Maintain the curated memory: a handful of one-sentence facts about "
        "this project and this person, injected at the top of every turn.\n"
        "\n"
        "Actions:\n"
        "- add: kind ('memory' for this project or its environment, 'user' "
        "for the person — true in any project), text (one plain sentence, "
        "120 characters at most).\n"
        "- replace: match (part of the existing fact's text) + the new text.\n"
        "- remove: match (part of the text to drop).\n"
        "- list: the current entries and how full each shelf is.\n"
        "\n"
        "When the user states something durable — which database this is, "
        "how they like replies, which channel is for alerts — record it "
        "here. Do not record anything transient to this conversation, and "
        "never record credentials. When a shelf is full, the error names "
        "every entry: replace the stale one instead of retrying the add."
    )

    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(ACTIONS),
                "description": "What to do.",
            },
            "kind": {
                "type": "string",
                "enum": ["memory", "user"],
                "description": "For add: 'memory' = this project, 'user' = the person, anywhere.",
            },
            "text": {
                "type": "string",
                "description": "For add and replace: the fact, one sentence.",
            },
            "match": {
                "type": "string",
                "description": "For replace and remove: part of the existing fact's text.",
            },
        },
        "required": ["action"],
    }

    def __init__(self, service: Any) -> None:
        super().__init__()
        self._service = service

    def summary(self, args: dict[str, Any]) -> str:
        action = str(args.get("action") or "")
        kind = str(args.get("kind") or "")
        text = str(args.get("text") or args.get("match") or "")
        if action in ("add", "replace"):
            return f"{action}ing {kind} fact: {text[:60]}".replace("inging", "ing")
        if action == "remove":
            return f"removing fact matching {text[:60]}"
        return "listing the curated memory"

    def detail(self, ctx: ToolContext, args: dict[str, Any]) -> str:
        return str(args.get("text") or args.get("match") or "")

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        action = str(args.get("action") or "").strip().lower()
        kind = str(args.get("kind") or "memory")
        try:
            if action == "add":
                fact = self._service.add(str(args.get("text") or ""), kind=kind)
                return ToolResult.success(
                    f"Memory holds: {self._service.usage_line()}", display=f"fact {kind} remembered"
                )
            if action == "replace":
                self._service.replace(
                    str(args.get("match") or ""), str(args.get("text") or ""), kind=kind
                )
                return ToolResult.success("Fact replaced.", display="fact replaced")
            if action == "remove":
                fact = self._service.remove(str(args.get("match") or ""), kind=kind)
                return ToolResult.success(
                    f"Removed #{fact.id}. Memory holds: {self._service.usage_line()}",
                    display="fact removed",
                )
            if action == "list":
                return self._list()
            return ToolResult.failure("unknown action — one of: add, replace, remove, list")
        except ValueError as error:
            return ToolResult.failure(str(error))

    def _list(self) -> ToolResult:
        entries = self._service.entries()
        if not entries:
            return ToolResult.success(
                f"No facts yet — the memory is empty. Shelves: {self._service.usage_line()}"
            )
        lines = [f"Memory holds: {self._service.usage_line()}", ""]
        for fact in entries:
            mark = " (pinned)" if fact.pinned else ""
            lines.append(f"- #{fact.id} ({fact.kind}{mark}): {fact.text}")
        return ToolResult.success("\n".join(lines))
