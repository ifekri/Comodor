"""The image-generation tool: a prompt becomes a file, at a price.

Every call costs real money, so the tool is DANGEROUS — the same tier as
the shell — and a daily fuse in the brain's metadata refuses the call in
words once the ceiling is reached, rather than letting the bill say it.
Where the image lands and what the transcript records about it are part
of the result, not something the caller has to remember to do.
"""

from __future__ import annotations

from typing import Any

from ..image_gen import ImageGenError
from ..image_gen.registry import generate
from ..safety import Risk
from ..vision import encode_for_model, sniff
from .base import Tool, ToolContext, ToolResult


class ImageGen(Tool):
    """Generate one image from a text prompt."""

    name = "image_gen"
    description = (
        "Generate an image from a text prompt. Costs money per call and "
        "counts against a daily limit; use it when the user asks for a "
        "picture, an illustration or a mock, not for diagrams a code "
        "library or a chart would draw better."
    )
    risk = Risk.DANGEROUS
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string",
                       "description": "what the image should show; be "
                                      "specific about subject, style and "
                                      "composition"},
            "size": {"type": "string",
                     "description": "square 1024x1024 by default; the "
                                    "provider's supported sizes apply"},
            "output_dir": {"type": "string",
                           "description": "where to write the file; blank "
                                          "means the session's generated "
                                          "media folder"},
        },
        "required": ["prompt"],
    }

    def summary(self, args: dict[str, Any]) -> str:
        preview = str(args.get("prompt", ""))[:60]
        return f"generate an image: {preview}"

    def detail(self, ctx: ToolContext, args: dict[str, Any]) -> str:
        # The prompt leaves the machine whole — no redaction pass can run on
        # it — so the person approving sees exactly what would be sent.
        return ("the prompt is sent to the image provider and one image "
                "comes back; it counts against the daily limit "
                f"({ctx.config.image_gen.max_per_day}/day)")

    def run(self, ctx: ToolContext, prompt: str, size: str = "1024x1024",
            output_dir: str = "", **_: Any) -> ToolResult:
        # The fuse is shared through the brain's metadata, which is why the
        # tool takes the store from the memory engine rather than keeping
        # its own counter a delegate could quietly sidestep.
        store = getattr(ctx, "brain_store", None)
        if store is None:
            return ToolResult.failure(
                "image generation needs the learning brain's store, which "
                "this session does not have")

        where = ctx.resolve(output_dir) if output_dir.strip() else \
            ctx.config.paths.user / "media" / "generated"
        try:
            path = generate(ctx.config, store, prompt, where, size=size)
        except ImageGenError as problem:
            return ToolResult.failure(str(problem))

        data = path.read_bytes()
        # Provenance lives in the transcript: what was asked for, on which
        # model, and the fingerprint of what came back — not the bytes.
        note = (f"[generated image: {ctx.relative(path)} · "
                f"{len(data) / 1024:.0f} KB · {sniff(data[:8])} · "
                f"prompt: {prompt.strip()[:120]}]")
        return ToolResult.success(
            content="\n".join([
                f"written to {path}",
                f"model: {ctx.config.image_gen.model} · size: {size}",
                note,
                "[the image follows]",
            ]),
            display=note,
            image=encode_for_model(data),
            path=str(path))
