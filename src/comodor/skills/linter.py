"""Reading a skill the way a reviewer would, before anybody has to.

The findings are advisory, always. A skill that trips every rule here still
loads and still runs — the point is that the person who owns the skill hears
about the rough edges at the moment the skill is written, not six weeks
later when it misfires and they have to read it to find out why.

The rules began as the mistakes actually observed: instructions that named a
shell command where a tool exists, a name that does not match its folder,
links into the void, and the marketing voice that pads descriptions until
the matching engine cannot tell what the skill is for.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Words that say "this description is selling, not describing". A description
#: stuffed with these stops being useful to the matcher that picks skills.
MARKETING = ("revolutionary", "game-changing", "blazingly fast",
             "best-in-class", "seamlessly", "cutting-edge", "ultimate",
             "10x", "unleash")

#: Files that arrive from scaffolding and mean nothing inside a skill folder.
SCAFFOLD = {"readme.md", "changelog.md", "changelog", ".env", "license",
            "license.md", "todo.md"}

#: Built-in tools the model has. An instruction telling it to run `grep` in
#: bash is slower and more dangerous than telling it to use the tool.
TOOLS = {"read_file": "read_file", "write_file": "write_file",
         "edit_file": "edit_file", "list_dir": "list_dir", "grep": "grep",
         "glob": "glob", "run_shell": "run_shell", "run_python": "run_python",
         "web_fetch": "web_fetch", "web_search": "web_search",
         "todo_write": "todo_write", "ask": "ask", "delegate": "delegate",
         "search_history": "search_history"}


@dataclass
class Finding:
    severity: str                   # error | warning
    where: str                      # file or section, short
    why: str

    def line(self) -> str:
        return f"{self.severity}: {self.where} — {self.why}"


def lint(skill) -> list[Finding]:
    """Everything worth saying about one skill, worst first."""
    findings: list[Finding] = []
    findings += _metadata(skill)
    findings += _identity(skill)
    findings += _description(skill)
    findings += _body(skill)
    findings += _files(skill)
    order = {"error": 0, "warning": 1}
    return sorted(findings, key=lambda f: order.get(f.severity, 2))


def _metadata(skill) -> list[Finding]:
    found = []
    if not (getattr(skill, "description", "") or "").strip():
        found.append(Finding(
            "error", "frontmatter",
            "no description — the matcher picks skills by it, so a skill "
            "without one never matches"))
    elif len(getattr(skill, "description", "")) < 20:
        found.append(Finding(
            "warning", "frontmatter",
            "very short description — say what it is for and when to use it"))
    return found


def _identity(skill) -> list[Finding]:
    name = str(getattr(skill, "name", "") or "")
    path = getattr(skill, "path", None)
    if path is None:
        return []
    folder = Path(path).parent.name
    if folder and name and folder != name and folder not in (".", ".."):
        return [Finding(
            "warning", "frontmatter",
            f"the skill is named {name!r} but lives in {folder!r} — rename "
            "one or the other so the folder can be found by the name")]
    return []


def _description(skill) -> list[Finding]:
    text = (getattr(skill, "description", "") or "").lower()
    hits = [word for word in MARKETING if word in text]
    if hits:
        return [Finding(
            "warning", "description",
            f"reads as marketing ({', '.join(hits[:3])}) — say what it does "
            "and when to reach for it, plainly")]
    return []


def _body(skill) -> list[Finding]:
    found: list[Finding] = []
    text = str(getattr(skill, "instructions", "") or "")
    if not text.strip():
        return found
    seen: set[str] = set()
    for line in text.splitlines():
        # The instruction sends the model to a shell for something a native
        # tool does in one safe step.
        lowered = line.lower()
        for shell_word, tool in (("run grep", "grep"), ("use grep", "grep"),
                                 ("run rg", "grep"), ("run ripgrep", "grep"),
                                 ("run find", "glob"), ("run ls", "list_dir")):
            if shell_word in lowered and tool not in seen:
                seen.add(tool)
                found.append(Finding(
                    "warning", "instructions",
                    f"mentions {shell_word} in a shell — the {tool} tool "
                    "does this without shell risk"))
    return found


def _files(skill) -> list[Finding]:
    found: list[Finding] = []
    path = getattr(skill, "path", None)
    if path is None:
        return found
    root = Path(path).parent
    try:
        names = {entry.name.lower() for entry in root.iterdir()
                 if entry.is_file()}
    except OSError:
        return found
    scaffold = names & SCAFFOLD
    if scaffold:
        found.append(Finding(
            "warning", "files",
            f"scaffold file(s) {', '.join(sorted(scaffold))} in the skill "
            "folder — remove them; a skill is instructions, not a project"))
    for name in sorted(names):
        if not name.endswith(".md"):
            continue
        try:
            body = (root / name).read_text(encoding="utf-8")
        except OSError:
            continue
        for link in _markdown_links(body):
            if not (root / link).exists():
                found.append(Finding(
                    "error", name,
                    f"links to {link}, which does not exist"))
    return found


def _markdown_links(text: str) -> list[str]:
    import re

    return [match.strip() for match in
            re.findall(r"\]\(([^)#]+)\)", text)]
