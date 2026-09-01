"""Let the agent create and mend skills, with the person still in charge.

The loop this closes: a workflow that just worked gets written down, and a
skill that has drifted gets mended while the reason it drifted is still in
context. The tool reaches only the skills directories — user and project —
and every path the model supplies is checked against them, because "the
skills folder" must never be interpretable as "any folder, via a symlink".

Everything it changes goes through the ledger, which keeps the text it
replaced under its hash, so any change the model makes here can be put back
byte for byte by the person reviewing it.

Risk is WRITE, not DANGEROUS: the folder is a managed one and the writes
are inspectable in the transcript, but they are writes outside the
workspace all the same, and the permission engine treats them as such.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..safety import Risk
from .base import Tool, ToolContext, ToolResult

#: The open format's name rule. A skill whose name breaks it still works
#: here, but it will not travel — the tool writes portable names.
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MANIFEST = "SKILL.md"


class SkillManage(Tool):
    """Create, patch, and remove skill files in the managed directories."""

    name = "skill_manage"
    risk = Risk.WRITE
    description = (
        "Write down a procedure as a skill, or fix an existing one. A skill "
        "is a SKILL.md the user keeps: a name, a description, instructions "
        "for doing one thing well.\n"
        "\n"
        "Actions:\n"
        "- create: name, description, instructions. Use after a multi-step "
        "workflow that just worked, so next time the steps are already "
        "written — but propose it in conversation and let the user agree "
        "before calling this.\n"
        "- patch: name, old, new. Replaces the first place `old` appears in "
        "the SKILL.md, forgiving line endings and indentation. If nothing "
        "matches or the match is ambiguous, nothing changes and the file's "
        "text comes back so a second attempt can be exact.\n"
        "- remove: name. Deletes the skill folder.\n"
        "\n"
        "The description's first sentence is what matches the skill to "
        "requests — make it self-contained, under 60 characters, and plain."
    )

    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string", "enum": ["create", "patch", "remove"],
                "description": "What to do.",
            },
            "name": {
                "type": "string",
                "description": "Skill name: lowercase, hyphen-separated "
                               "(\"release-checklist\"). Must match the "
                               "folder name.",
            },
            "description": {
                "type": "string",
                "description": "For create: what it is for, and when to use "
                               "it. First sentence stands alone.",
            },
            "instructions": {
                "type": "string",
                "description": "For create: the steps, in markdown. What "
                               "the model should read to do the thing.",
            },
            "old": {"type": "string",
                    "description": "For patch: the text to replace."},
            "new": {"type": "string",
                    "description": "For patch: the replacement."},
        },
        "required": ["action"],
    }

    def __init__(self, ledger=None) -> None:
        super().__init__()
        self._ledger = ledger

    # -- naming -------------------------------------------------------------- #

    def summary(self, args: dict[str, Any]) -> str:
        action = str(args.get("action") or "")
        name = str(args.get("name") or "")
        return {"create": f"writing skill {name}", "patch": f"patching {name}",
                "remove": f"removing skill {name}"}.get(action, action)

    def detail(self, ctx: ToolContext, args: dict[str, Any]) -> str:
        if args.get("action") == "patch":
            return f"- replace: {str(args.get('old') or '')[:200]}"
        if args.get("action") == "create":
            return str(args.get("description") or "")
        return ""

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        action = str(args.get("action") or "").strip().lower()
        if action == "create":
            return self._create(ctx, args)
        if action == "patch":
            return self._patch(ctx, args)
        if action == "remove":
            return self._remove(ctx, args)
        return ToolResult.failure(
            "unknown action — one of: create, patch, remove")

    # -- the directories ------------------------------------------------------ #

    def _roots(self, ctx: ToolContext) -> list[Path]:
        """Where skills may be written: the user's and this project's."""
        roots = [Path(ctx.config.paths.skills)]
        project = getattr(ctx.config.paths, "project_skills", None)
        if project is not None:
            roots.append(Path(project))
        return roots

    def _resolve(self, ctx: ToolContext, name: str) -> Path | None:
        """The skill folder for `name`, or None when the name is unusable.

        A name is a single path segment. Anything that could climb out of
        the skills directory — separators, dots beyond the obvious — is
        refused here rather than escaped from later.
        """
        if not NAME_PATTERN.match(name or ""):
            return None
        for root in self._roots(ctx):
            candidate = root / name
            if candidate.is_dir():
                return candidate
        return None

    def _empty_slot(self, ctx: ToolContext, name: str) -> Path | None:
        """Where a new skill would go: the user directory, by preference."""
        if not NAME_PATTERN.match(name or ""):
            return None
        user = Path(ctx.config.paths.skills)
        if not (user / name).exists():
            return user / name
        return None

    # -- actions --------------------------------------------------------------- #

    def _create(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        name = str(args.get("name") or "").strip()
        description = " ".join(str(args.get("description") or "").split())
        instructions = str(args.get("instructions") or "").strip()
        if not NAME_PATTERN.match(name):
            return ToolResult.failure(
                f"name {name!r} is not portable — lowercase letters, digits "
                "and single hyphens, as in 'release-checklist'")
        if not description:
            return ToolResult.failure(
                "`description` is required — it is what matches the skill "
                "to requests")
        if not instructions:
            return ToolResult.failure("`instructions` is required — say the "
                                      "steps, in markdown")
        folder = self._empty_slot(ctx, name)
        if folder is None:
            return ToolResult.failure(
                f"a skill named {name!r} already exists — patch it instead, "
                "or remove it and write it again")

        manifest = folder / MANIFEST
        body = (f"---\nname: {name}\ndescription: {description}\n---\n\n"
                f"{instructions.rstrip()}\n")
        flagged = self._threat_note(body)
        folder.mkdir(parents=True, exist_ok=True)
        manifest.write_text(body, encoding="utf-8")
        self._mark_created(ctx, name)
        self._record(ctx, action="create", skill=name,
                     before_text="", after_text=body)
        findings = self._lint_note(ctx, folder)
        return ToolResult.success(
            f"Wrote {manifest} in the user skills folder.{flagged}{findings}",
            display=f"skill {name} created")

    def _patch(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        from ..skills.usage import UsageStore
        from ..tools.matching import find, near_misses

        name = str(args.get("name") or "").strip()
        old = str(args.get("old") or "")
        new = str(args.get("new") or "")
        folder = self._resolve(ctx, name)
        if folder is None:
            return ToolResult.failure(
                f"no skill named {name!r} — list them with their exact names")
        if not old:
            return ToolResult.failure("`old` is empty — say what to replace")

        manifest = folder / MANIFEST
        if not manifest.exists():
            return ToolResult.failure(
                f"{name!r} has no {MANIFEST} to patch")
        # newline="" keeps the file's own line endings, so the matching
        # ladder does the forgiving and reports it — read_text would
        # silently normalise and the note would be a lie.
        with manifest.open("r", encoding="utf-8", newline="") as handle:
            text = handle.read()
        matches, _ = find(text, old)
        if not matches:
            hint = near_misses(text, old)
            # The whole file, so the model can correct itself from what is
            # actually there rather than from what it remembers.
            return ToolResult.failure(
                f"that text does not appear in {MANIFEST}. The file, so the "
                f"next attempt is exact:\n\n{text}" + (f"\n\n{hint}" if hint
                                                       else ""))
        if len(matches) > 1:
            return ToolResult.failure(
                f"that text appears {len(matches)} times — name the place "
                f"more exactly. The file:\n\n{text}")
        match = matches[0]
        note = f" ({match.how})" if not match.exact else ""
        changed = text[:match.start] + new + text[match.end:]
        flagged = self._threat_note(new)
        with manifest.open("w", encoding="utf-8", newline="") as handle:
            handle.write(changed)
        self._record(ctx, action="patch", skill=name, before_text=text,
                     after_text=changed)
        store = UsageStore(ctx.config.paths.skills)
        store.record_patch(name, note="patched by agent")
        findings = self._lint_note(ctx, folder)
        return ToolResult.success(
            f"Patched {MANIFEST}{note or ''}.{flagged}{findings}",
            display=f"skill {name} patched")

    def _remove(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        import shutil

        name = str(args.get("name") or "").strip()
        folder = self._resolve(ctx, name)
        if folder is None:
            return ToolResult.failure(f"no skill named {name!r}")
        text = ""
        manifest = folder / MANIFEST
        if manifest.exists():
            with manifest.open("r", encoding="utf-8", newline="") as handle:
                text = handle.read()
        shutil.rmtree(folder)
        self._record(ctx, action="remove", skill=name, before_text=text,
                     after_text="")
        return ToolResult.success(f"Removed skill {name!r}.",
                                  display=f"skill {name} removed")

    # -- bookkeeping ----------------------------------------------------------- #

    def _record(self, ctx: ToolContext, *, action: str, skill: str,
                before_text: str, after_text: str) -> None:
        """The ledger entry, with version blocks. Never blocks the work."""
        if self._ledger is None:
            return
        before = self._ledger.keep(before_text) if before_text else ""
        after = self._ledger.keep(after_text) if after_text else ""
        self._ledger.record(actor="agent", action=action, skill=skill,
                            before=before, after=after)

    def _threat_note(self, text: str) -> str:
        """What the injection scan saw, said once, at write time.

        Advisory like the linter notes: the finding lands in the result the
        person is already reading, and the person decides. Nothing is
        blocked here — a scan that silently refuses text is a gate with a
        pattern list for a brain, and that is not what this is.
        """
        from ..skills.threats import scan

        hits = scan(text)
        if not hits:
            return ""
        return ("\n\nSecurity note — this text also:\n" + "\n".join(
            f"- {hit}" for hit in hits))

    def _mark_created(self, ctx: ToolContext, name: str) -> None:
        """Record who authored the skill, in the usage sidecar.

        The curator exempts user-authored skills from archiving, so the
        honest answer is "agent": this file was written by the tool, at the
        model's request. A person editing it later is a patch, not a birth.
        """
        import time as _time

        from ..skills.usage import UsageStore

        def claim(record):
            record.created_by = "agent"
            if not record.created:
                record.created = _time.strftime("%Y-%m-%dT%H:%M:%S")
            return record

        try:
            UsageStore(ctx.config.paths.skills).update(name, claim)
        except OSError:
            pass

    def _lint_note(self, ctx: ToolContext, folder: Path) -> str:
        """What the reviewer would say, said once, at write time."""
        from ..skills.linter import lint
        from ..skills.loader import load

        try:
            skill = load(folder / MANIFEST)
        except Exception:
            return ""
        findings = lint(skill)
        if not findings:
            return ""
        return "\n\nReviewer notes:\n" + "\n".join(
            f"- {finding.line()}" for finding in findings[:5])
