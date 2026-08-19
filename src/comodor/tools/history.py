"""Letting the agent look up what you did before.

The brain remembers *rules* — distilled, general, deliberately few. This is the
other kind of memory: the raw record of every conversation, searchable. They
answer different questions. "Do they prefer single quotes" is a rule. "What was
the fix for that circular import last month" is not a rule and never will be,
but it is written down verbatim in a transcript from March.

Handing the model a search tool rather than pre-loading history is the whole
design. Nothing enters the context until the agent decides the question needs
it, so the cost of having four hundred sessions on disk is zero on the turns
that do not need them.
"""

from __future__ import annotations

from typing import Any

from ..safety import Risk
from .base import Tool, ToolContext, ToolResult

MAX_RESULTS = 10


class SearchHistory(Tool):
    name = "search_history"
    description = (
        "Search past conversations with this user for something that has come up "
        "before — an error they hit, a decision they made, how a problem was "
        "solved. Use it when the user refers to earlier work ('like we did last "
        "time', 'that bug from last week'), or when a task looks familiar and a "
        "previous approach would save repeating it. Searches transcripts, not "
        "files: use grep for the code itself."
    )
    risk = Risk.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Words likely to appear in the earlier conversation. "
                    "Distinctive terms work best — an error name, a file, a "
                    "library — rather than a full sentence."
                ),
            },
            "limit": {
                "type": "integer",
                "description": f"How many results, at most (default 6, max {MAX_RESULTS}).",
            },
        },
        "required": ["query"],
    }

    def __init__(self, index: Any = None, current_session: str = "") -> None:
        self.index = index
        self.current_session = current_session

    def summary(self, args: dict[str, Any]) -> str:
        return f"search history: {args.get('query', '')!r}"

    def run(self, ctx: ToolContext, query: str = "", limit: int = 6,
            **_: Any) -> ToolResult:
        if self.index is None:
            return ToolResult.failure("session history is not available here")

        text = str(query).strip()
        if not text:
            return ToolResult.failure("give some words to search for")

        try:
            count = max(1, min(int(limit), MAX_RESULTS))
        except (TypeError, ValueError):
            count = 6

        self.index.refresh()
        hits = self.index.search(text, limit=count,
                                 exclude_session=self.current_session)

        if not hits:
            # Said plainly, because the model's next move should be to solve the
            # problem rather than to search again with different words.
            return ToolResult.success(
                f"Nothing in past conversations matches {text!r}. "
                "This has not come up before, or it was worded differently.",
                display="no matches")

        lines = [f"{len(hits)} match(es) in past conversations, most relevant first:", ""]
        for hit in hits:
            speaker = "user" if hit.role == "user" else "you"
            lines.append(f"[{hit.when} · session {hit.session_id} · {speaker}]")
            lines.append(hit.snippet())
            lines.append("")

        return ToolResult.success(
            "\n".join(lines).strip(),
            display=f"{len(hits)} match(es)",
            matches=len(hits),
        )
