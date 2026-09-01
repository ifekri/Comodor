"""The vision tool: let the model look at an image it was told about.

A screenshot of its own the agent could always take; an image the *user*
has — a diagram, a photo of a whiteboard, an error dialog — it could not.
This tool hands one over, through the same budget and the same wire format
an attached image rides, so the model answers about what is actually in
the picture rather than about a filename.

The image is sent to the model provider, so the tool is DANGEROUS — the
permission engine is where "this picture leaves the machine" is asked.
URLs additionally pass the SSRF guard, the same one web_fetch uses.
Whether the tool is advertised at all is decided in the registry: a model
that cannot see images never sees a tool that would feed it one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..safety import Risk
from ..vision import ImageError, budget, encode_for_model, from_source, note_for
from .base import Tool, ToolContext, ToolResult
from .web import check_url


class Vision(Tool):
    """Look at an image — a file, or a URL — and answer about what is in it."""

    name = "vision"
    description = (
        "Look at an image file (or image URL) and describe or analyse it. "
        "Use it when the user's question is about what a picture shows — "
        "a diagram, a screenshot they sent, a design mock, a photo of text."
    )
    risk = Risk.DANGEROUS
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string",
                       "description": "path to the image, or an image URL"},
            "question": {"type": "string",
                         "description": "what to look for; omitted means "
                                        "describe the image"},
        },
        "required": ["source"],
    }

    def summary(self, args: dict[str, Any]) -> str:
        return f"look at {args.get('source', '?')}"

    def detail(self, ctx: ToolContext, args: dict[str, Any]) -> str:
        return f"the image is sent to the provider ({ctx.config.provider}) to be read"

    def run(self, ctx: ToolContext, source: str, question: str = "",
            **_: Any) -> ToolResult:
        if source.lower().startswith(("http://", "https://")):
            refused = check_url(ctx, source)
            if refused:
                return ToolResult.failure(refused)
            where = source
        else:
            # Relative paths mean the workspace, exactly as read_file means it.
            where = str(ctx.resolve(source))
        try:
            data, fmt = from_source(where)
            encoded_bytes, _out_fmt, resized, note = budget(data, fmt)
        except ImageError as problem:
            return ToolResult.failure(str(problem))

        transcript_note = note_for(ctx.relative(Path(where)), encoded_bytes, resized)
        lines = [transcript_note]
        if note:
            lines.append(f"note: {note}")

        ask = question.strip() or (
            "Describe this image: what it shows, any text in it, and "
            "anything relevant to the current task.")
        # The image itself rides the tool result as `image` meta, the same
        # channel a screenshot takes; the loop puts it beside this content.
        return ToolResult.success(
            content="\n".join(lines) + "\n[the image follows]",
            display=transcript_note,
            image=encode_for_model(encoded_bytes),
            question=ask)
