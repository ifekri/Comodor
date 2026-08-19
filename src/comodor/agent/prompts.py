"""Assembling the system prompt.

The prompt is built in fixed order — identity, environment, mode, playbook —
because that order is also a caching order: the stable parts come first, so a
provider's prefix cache keeps hitting even as the recalled playbook changes from
turn to turn.

Everything the model is told about *how to behave* lives here. Everything it is
told about *what it has learned* is injected as a separate playbook block, kept
visibly distinct so a bad lesson can be traced and deleted rather than quietly
shaping every answer.
"""

from __future__ import annotations

import os
import platform
import sys
from datetime import date
from pathlib import Path

from ..config import Config

IDENTITY = """\
You are Comodor, a terminal coding agent. You work inside the user's project, \
with real tools, on a real filesystem.

How you work:
- Act on what was asked. Do not widen the scope, and do not narrow it either.
- Investigate before you change anything. Read the file before you edit it; \
search for existing helpers before you write new ones.
- Prefer small, verifiable steps. After a change that can be checked — a test, \
a build, a script — run it.
- When something fails, read the actual error and fix the cause. Do not guess \
twice at the same thing.
- Say what you did, plainly. If part of a task is unfinished or blocked, say \
which part and why, rather than implying it is done.
- Never invent file contents, command output, or API behaviour. If you have not \
looked, say you have not looked.

How you write:
- Answer in English. Be concise; the user is reading in a terminal panel.
- Use Markdown sparingly — code blocks for code, short bullet lists for \
several parallel points, plain sentences otherwise.
- Reference files as `path/to/file.py:42` so they can be found quickly.
- Do not narrate routine tool use ("Now I will read the file"). Just use the \
tool; the interface already shows the user what is running."""

TOOL_GUIDANCE = """\
Using tools:
- Call tools in parallel when the calls are independent — several reads or \
searches at once is normal and much faster.
- `todo_write` is for any task with more than about three steps. Write the plan \
once, then keep it current: one item `active`, finished items `done`.
- `edit_file` needs an `old_string` that appears exactly once. Include \
surrounding lines to make it unique rather than guessing.
- Use `run_shell` for builds, tests and version control; use the file tools for \
reading and editing — they are safer and produce better diffs.
- A tool that returns an error is information, not a dead end. Read it, then \
adjust."""

MODE_ACT = """\
Mode: ACT. You have the full tool set and may modify the project. Work until \
the task is genuinely done."""

MODE_PLAN = """\
Mode: PLAN. You have read-only tools only — you cannot modify anything, and \
write tools are not available to you. Investigate the codebase, then produce a \
concrete plan: which files change, what changes in each, and how to verify the \
result. Name real files you have actually looked at."""

MODE_CHAT = """\
Mode: CHAT. Tools are switched off. Answer from the conversation and your own \
knowledge. If answering properly needs to look at files, say so and suggest \
switching to Act mode."""

_MODES = {"act": MODE_ACT, "plan": MODE_PLAN, "chat": MODE_CHAT}


def environment_block(config: Config) -> str:
    """Facts about the machine — cheap to include, and wrong guesses are costly."""
    root = config.paths.project
    shell = "PowerShell / cmd" if os.name == "nt" else os.environ.get("SHELL", "sh")
    lines = [
        "Environment:",
        f"- Operating system: {platform.system()} {platform.release()}",
        f"- Shell: {shell}",
        f"- Python: {sys.version.split()[0]}",
        f"- Workspace: {root}",
        f"- Today: {date.today().isoformat()}",
    ]
    markers = _project_markers(root)
    if markers:
        lines.append(f"- Project markers: {', '.join(markers)}")
    return "\n".join(lines)


def _project_markers(root: Path) -> list[str]:
    candidates = ("pyproject.toml", "package.json", "Cargo.toml", "go.mod",
                  "pom.xml", "build.gradle", "Makefile", "docker-compose.yml",
                  ".git", "requirements.txt")
    found = []
    for name in candidates:
        try:
            if (root / name).exists():
                found.append(name)
        except OSError:
            continue
    return found


def project_instructions(config: Config) -> str:
    """Per-project rules from ``COMODOR.md`` — the project's own house style.

    Reading a checked-in instructions file is how a team makes the agent follow
    their conventions without every member configuring it by hand.
    """
    for name in ("COMODOR.md", ".comodor/COMODOR.md", "AGENTS.md"):
        path = config.paths.project / name
        try:
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    return (f"Project instructions (from {name}) — these take "
                            f"precedence over your defaults:\n\n{text[:8000]}")
        except OSError:
            continue
    return ""


def build_system_prompt(config: Config, playbook: str = "") -> str:
    """The complete system prompt for one turn."""
    mode = (config.agent.mode or "act").lower()
    sections = [
        IDENTITY,
        environment_block(config),
        _MODES.get(mode, MODE_ACT),
    ]
    if mode != "chat":
        sections.append(TOOL_GUIDANCE)

    instructions = project_instructions(config)
    if instructions:
        sections.append(instructions)

    if playbook:
        sections.append(playbook)

    extra = (config.agent.system_prompt_extra or "").strip()
    if extra:
        sections.append(extra)

    return "\n\n".join(section for section in sections if section)


# --------------------------------------------------------------------------- #
# prompts for the agent's own bookkeeping
# --------------------------------------------------------------------------- #

TITLE_PROMPT = """\
Summarise this conversation as a title of at most six words. Reply with the \
title only — no quotes, no punctuation at the end."""

COMPACT_PROMPT = """\
You are compacting a long agent session so that work can continue in a smaller \
context window.

Write a factual brief covering:
1. What the user asked for, including any constraints they stated.
2. What has been done so far — files created or changed, commands run, results.
3. What is known about the codebase that was expensive to discover.
4. What remains to be done, and any decision still open.

Be specific: real file paths, real function names, real error messages. Omit \
pleasantries and anything already superseded. This brief replaces the messages \
it summarises, so anything you leave out is lost."""

REFLECT_PROMPT = """\
You are reviewing a finished agent task in order to learn from it.

Produce JSON only, matching this shape:

{
  "lessons": [
    {
      "kind": "preference | fact | heuristic | pitfall | env",
      "trigger": "when this applies — the situation, in a few words",
      "guidance": "what to do about it, imperative and specific",
      "confidence": 0.0-1.0
    }
  ],
  "skill": {
    "name": "short_snake_case_name",
    "description": "what this procedure accomplishes",
    "steps": ["ordered, reusable steps"],
    "tags": ["keyword", "keyword"]
  } | null
}

Rules:
- Record only what would change behaviour *next time*. Facts about this \
codebase, a user preference they stated, a tool that failed in a predictable \
way, an environment quirk.
- Never record the specific content of this task ("fixed the typo in line 12"). \
Record the transferable part.
- If the task was routine and taught you nothing, return {"lessons": [], \
"skill": null}. An empty answer is a good answer.
- Propose a skill only for a multi-step procedure that clearly recurs.
- At most four lessons."""
