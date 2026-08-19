"""Reading the files a skill brings with it.

A skill in the open format can bundle `references/`, `scripts/` and `assets/`
alongside its instructions. Those files are named in the prompt but never
inlined — that is the whole idea. A skill can carry a thousand-line API
reference and cost nothing until the one turn that needs it.

This tool is the third stage of that. It is separate from `read_file` on
purpose: skills live in `~/.comodor/skills`, outside the workspace, and the
alternative would have been to widen the workspace rule for everybody so that
one feature could reach one folder. Instead the reachable set here is exactly
the files discovery already found, in skills that are actually loaded.
"""

from __future__ import annotations

from typing import Any

from ..safety import Risk
from .base import Tool, ToolContext, ToolResult

MAX_BYTES = 96_000


class ReadSkillFile(Tool):
    name = "read_skill_file"
    description = (
        "Read a file bundled with a skill — a reference document, a script, a "
        "template. Only files listed under 'Bundled files' in a skill you have "
        "been given can be read. Use this when the skill's instructions point at "
        "one, rather than guessing at its contents."
    )
    risk = Risk.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "description": "The skill's name, as it appears in its heading.",
            },
            "path": {
                "type": "string",
                "description": "The file, as listed — for example 'references/API.md'.",
            },
        },
        "required": ["skill", "path"],
    }

    def __init__(self, registry: Any = None) -> None:
        # Injected rather than imported: the registry is per-session, and a
        # tool that reached for a global would read the wrong project's skills.
        self.registry = registry

    def summary(self, args: dict[str, Any]) -> str:
        return f"read {args.get('skill', '?')}/{args.get('path', '?')}"

    def run(self, ctx: ToolContext, skill: str = "", path: str = "",
            **_: Any) -> ToolResult:
        if self.registry is None:
            return ToolResult.failure("no skills are loaded in this session")

        found = self.registry.get(str(skill).strip())
        if found is None:
            available = ", ".join(sorted(self.registry.skills)) or "none"
            return ToolResult.failure(
                f"no skill named {skill!r} is loaded. Available: {available}")

        target = found.resolve(str(path))
        if target is None:
            listing = ", ".join(found.resources) or "none"
            return ToolResult.failure(
                f"{path!r} is not bundled with {found.name!r}. "
                f"Its files are: {listing}")

        try:
            if target.stat().st_size > MAX_BYTES:
                return ToolResult.failure(
                    f"{path} is larger than {MAX_BYTES // 1000} KB. Ask the skill's "
                    "author to split it, or read what you need another way.")
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            return ToolResult.failure(f"could not read {path}: {error}")

        return ToolResult.success(
            f"# {found.name}/{path}\n\n{text}",
            display=f"{found.name}/{path} ({len(text)} chars)",
            skill=found.name, path=path,
        )
