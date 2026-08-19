"""House rules: conventions learned by counting, not by asking a model.

Every detector here is deterministic and cheap — regexes over text, no network,
no tokens, microseconds per file. That matters for two reasons. It means the
agent keeps learning when the user is offline or on a budget model, and it means
a rule comes with its evidence: not "I think you prefer single quotes" but
"31 of 34 string literals in this project use single quotes".

Two sources feed the same counters:

*Observation* — scanning the project tells us how the code already looks.
*Correction* — when the user rewrites something the agent produced, the diff
tells us what the agent got wrong. That is worth far more, so it is weighted
higher and needs less repetition before it starts influencing the prompt.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 400_000
MAX_FILES = 120                  # a sample is enough; this runs on a hot path
SAMPLE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
                   ".rb", ".php", ".c", ".cpp", ".h", ".cs", ".sh", ".css"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist",
             "build", ".comodor", ".mypy_cache", ".pytest_cache", "target"}


@dataclass(slots=True)
class Observation:
    """One counted vote for or against a convention."""

    key: str
    statement: str
    detail: str = ""
    category: str = "style"
    agrees: bool = True
    weight: int = 1


# --------------------------------------------------------------------------- #
# detectors
# --------------------------------------------------------------------------- #

_INDENT = re.compile(r"^([ \t]+)\S", re.MULTILINE)
_SINGLE = re.compile(r"'[^'\n]{0,120}'")
_DOUBLE = re.compile(r'"[^"\n]{0,120}"')
_DEF_SNAKE = re.compile(r"^\s*(?:def|function)\s+([a-z_][a-z0-9_]*)\s*\(", re.MULTILINE)
_DEF_CAMEL = re.compile(r"^\s*(?:def|function)\s+([a-z]+[A-Z][A-Za-z0-9]*)\s*\(", re.MULTILINE)
_ANNOTATED = re.compile(r"^\s*def\s+\w+\s*\([^)]*\)\s*->", re.MULTILINE)
_PLAIN_DEF = re.compile(r"^\s*def\s+\w+\s*\(", re.MULTILINE)
_FSTRING = re.compile(r"""f["']""")
_FORMAT = re.compile(r"\.format\(|%\s*\(")
_SEMICOLON = re.compile(r";\s*$", re.MULTILINE)


def analyse_text(path: str, text: str) -> list[Observation]:
    """Style facts visible in one file."""
    if not text:
        return []
    suffix = Path(path).suffix.lower()
    observations: list[Observation] = []

    # -- indentation --------------------------------------------------- #
    indents = _INDENT.findall(text)
    tabs = sum(1 for indent in indents if indent.startswith("\t"))
    spaces = len(indents) - tabs
    if tabs or spaces:
        uses_tabs = tabs > spaces
        observations.append(Observation(
            key="indent.style",
            statement=f"Indent with {'tabs' if uses_tabs else 'spaces'}.",
            detail=f"{max(tabs, spaces)} of {tabs + spaces} indented lines",
            weight=1,
        ))
        if not uses_tabs and spaces:
            widths = Counter(len(indent) for indent in indents
                             if not indent.startswith("\t") and len(indent) <= 8)
            unit = _indent_unit(widths)
            if unit:
                observations.append(Observation(
                    key="indent.width",
                    statement=f"Indent {unit} spaces per level.",
                    detail=f"most common step across {sum(widths.values())} lines",
                ))

    # -- quotes ---------------------------------------------------------- #
    if suffix in (".py", ".js", ".ts", ".tsx", ".jsx", ".rb"):
        singles, doubles = len(_SINGLE.findall(text)), len(_DOUBLE.findall(text))
        total = singles + doubles
        if total >= 6 and abs(singles - doubles) / total >= 0.3:
            prefer_single = singles > doubles
            observations.append(Observation(
                key="quotes.style",
                statement=f"Use {'single' if prefer_single else 'double'} quotes "
                          f"for string literals.",
                detail=f"{max(singles, doubles)} of {total} literals",
            ))

    # -- line length ----------------------------------------------------- #
    lengths = [len(line) for line in text.splitlines() if line.strip()]
    if len(lengths) >= 20:
        lengths.sort()
        p95 = lengths[int(len(lengths) * 0.95) - 1]
        limit = _line_limit(p95)
        if limit:
            observations.append(Observation(
                key="line.length",
                statement=f"Keep lines within about {limit} characters.",
                detail=f"95% of lines are under {p95}",
            ))

    # -- naming ---------------------------------------------------------- #
    snake, camel = len(_DEF_SNAKE.findall(text)), len(_DEF_CAMEL.findall(text))
    if snake + camel >= 5:
        observations.append(Observation(
            key="naming.functions",
            statement=f"Name functions in {'snake_case' if snake > camel else 'camelCase'}.",
            detail=f"{max(snake, camel)} of {snake + camel} definitions",
        ))

    # -- python specifics ------------------------------------------------ #
    if suffix == ".py":
        annotated, plain = len(_ANNOTATED.findall(text)), len(_PLAIN_DEF.findall(text))
        if plain >= 4:
            share = annotated / plain
            if share >= 0.7:
                observations.append(Observation(
                    key="python.annotations",
                    statement="Annotate function return types.",
                    detail=f"{annotated} of {plain} functions annotated",
                ))
            elif share <= 0.1:
                observations.append(Observation(
                    key="python.annotations",
                    statement="This project does not use type annotations; do not add them.",
                    detail=f"only {annotated} of {plain} functions annotated",
                ))
        if _FSTRING.search(text) and not _FORMAT.search(text):
            observations.append(Observation(
                key="python.interpolation",
                statement="Use f-strings rather than .format() or % formatting.",
                detail="f-strings only in this file",
            ))

    # -- javascript specifics -------------------------------------------- #
    if suffix in (".js", ".ts", ".tsx", ".jsx"):
        statements = [line for line in text.splitlines()
                      if line.strip() and not line.strip().startswith(("//", "*", "/*"))]
        if len(statements) >= 15:
            with_semi = len(_SEMICOLON.findall(text))
            observations.append(Observation(
                key="js.semicolons",
                statement=("End statements with semicolons." if with_semi > len(statements) / 3
                           else "Omit semicolons at the end of statements."),
                detail=f"{with_semi} semicolon-terminated lines of {len(statements)}",
            ))

    return observations


def _indent_unit(widths: Counter[int]) -> int | None:
    """The most plausible indent step from observed leading-space counts."""
    for candidate in (2, 4, 8, 3):
        hits = sum(count for width, count in widths.items()
                   if width and width % candidate == 0)
        total = sum(widths.values())
        if total and hits / total >= 0.9:
            return candidate
    return None


def _line_limit(p95: int) -> int | None:
    """Snap an observed width to the limit the project is probably enforcing."""
    for limit in (79, 88, 100, 120):
        if p95 <= limit:
            return limit
    return None


# --------------------------------------------------------------------------- #
# corrections
# --------------------------------------------------------------------------- #


def analyse_correction(before: str, after: str, path: str = "") -> list[Observation]:
    """What the user changed about what the agent wrote.

    Only differences that are unambiguous are reported. A user who rewrites the
    logic entirely has taught us nothing transferable, and guessing at intent
    from an arbitrary diff would fill the playbook with noise.
    """
    if not before or not after or before == after:
        return []

    observations: list[Observation] = []

    def counts(text: str) -> dict[str, int]:
        return {
            "single": len(_SINGLE.findall(text)),
            "double": len(_DOUBLE.findall(text)),
            "tabs": len([m for m in _INDENT.findall(text) if m.startswith("\t")]),
            "spaces": len([m for m in _INDENT.findall(text) if not m.startswith("\t")]),
            "annotated": len(_ANNOTATED.findall(text)),
            "fstring": len(_FSTRING.findall(text)),
            "format": len(_FORMAT.findall(text)),
            "semicolon": len(_SEMICOLON.findall(text)),
        }

    was, now = counts(before), counts(after)

    if now["single"] > was["single"] and now["double"] < was["double"]:
        observations.append(Observation(
            key="quotes.style", statement="Use single quotes for string literals.",
            detail="you rewrote double quotes as single", category="style"))
    elif now["double"] > was["double"] and now["single"] < was["single"]:
        observations.append(Observation(
            key="quotes.style", statement="Use double quotes for string literals.",
            detail="you rewrote single quotes as double", category="style"))

    if now["tabs"] > was["tabs"] and now["spaces"] < was["spaces"]:
        observations.append(Observation(
            key="indent.style", statement="Indent with tabs.",
            detail="you converted spaces to tabs"))
    elif now["spaces"] > was["spaces"] and now["tabs"] < was["tabs"]:
        observations.append(Observation(
            key="indent.style", statement="Indent with spaces.",
            detail="you converted tabs to spaces"))

    if now["annotated"] > was["annotated"]:
        observations.append(Observation(
            key="python.annotations", statement="Annotate function return types.",
            detail="you added the annotations that were missing"))

    if now["fstring"] > was["fstring"] and now["format"] < was["format"]:
        observations.append(Observation(
            key="python.interpolation", statement="Use f-strings for interpolation.",
            detail="you converted .format() calls to f-strings"))

    if now["semicolon"] < was["semicolon"] and was["semicolon"] >= 3:
        observations.append(Observation(
            key="js.semicolons", statement="Omit semicolons at the end of statements.",
            detail="you removed the semicolons"))

    # Length is the one structural signal worth reading: a user who consistently
    # shortens what the agent writes is telling it to be less verbose.
    before_lines, after_lines = len(before.splitlines()), len(after.splitlines())
    if before_lines >= 12 and after_lines <= before_lines * 0.7:
        observations.append(Observation(
            key="output.verbosity", category="preference",
            statement="Write less: this user trims generated code down.",
            detail=f"{before_lines} lines cut to {after_lines}"))

    for observation in observations:
        observation.weight = 2          # a correction outweighs a passive look
    return observations


# --------------------------------------------------------------------------- #
# project scan
# --------------------------------------------------------------------------- #


def scan_project(root: Path, max_files: int = MAX_FILES) -> list[Observation]:
    """Sample the repository and report what its code already looks like.

    Sampled rather than exhaustive: a hundred files establish a convention just
    as well as ten thousand, and this must stay fast enough to run at startup.
    """
    observations: list[Observation] = []
    seen = 0

    for path in _walk(root):
        if seen >= max_files:
            break
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        seen += 1
        observations.extend(analyse_text(str(path), text))

    observations.extend(_project_signals(root))
    return observations


def _walk(root: Path):
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (OSError, PermissionError):
            continue
        for entry in entries:
            if entry.name in SKIP_DIRS or entry.name.startswith("."):
                continue
            if entry.is_dir():
                if not entry.is_symlink():
                    stack.append(entry)
            elif entry.suffix.lower() in SAMPLE_SUFFIXES:
                yield entry


def _project_signals(root: Path) -> list[Observation]:
    """Facts from the project's own configuration — cheap and highly reliable."""
    observations: list[Observation] = []

    def exists(name: str) -> bool:
        try:
            return (root / name).exists()
        except OSError:
            return False

    if exists("pyproject.toml"):
        try:
            text = (root / "pyproject.toml").read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if "[tool.pytest" in text or "pytest" in text:
            observations.append(Observation(
                key="python.tests", category="workflow",
                statement="Write tests with pytest and run them with `pytest -q`.",
                detail="pytest configured in pyproject.toml", weight=3))
        if "[tool.ruff" in text:
            observations.append(Observation(
                key="python.lint", category="workflow",
                statement="Lint with ruff before finishing.",
                detail="ruff configured in pyproject.toml", weight=3))
        if "[tool.black" in text:
            observations.append(Observation(
                key="python.format", category="workflow",
                statement="Format with black; do not hand-align code.",
                detail="black configured in pyproject.toml", weight=3))
    if exists("package.json"):
        try:
            text = (root / "package.json").read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for marker, statement in (
            ("vitest", "Write tests with vitest."),
            ("jest", "Write tests with jest."),
            ("eslint", "Keep eslint clean."),
            ("prettier", "Format with prettier; do not hand-align code."),
        ):
            if marker in text:
                observations.append(Observation(
                    key=f"js.{marker}", category="workflow", statement=statement,
                    detail=f"{marker} listed in package.json", weight=3))
    if exists("Makefile"):
        observations.append(Observation(
            key="build.make", category="workflow",
            statement="This project has a Makefile — prefer its targets over ad-hoc commands.",
            detail="Makefile in the project root", weight=2))

    return observations


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #


def render_rules(rules: list, max_tokens: int = 300) -> str:
    """The House rules block for the system prompt, within a token budget."""
    if not rules:
        return ""
    header = ("House rules — how this user works, counted from their code and "
              "from the edits they made to yours. Follow them unless the task "
              "says otherwise.")
    lines = [header, ""]
    used = len(header) // 4

    for rule in rules:
        entry = f"- {rule.statement}"
        cost = len(entry) // 4 + 1
        if used + cost > max_tokens:
            break
        lines.append(entry)
        used += cost
    return "\n".join(lines) if len(lines) > 2 else ""


def export_markdown(rules: list, project: str = "") -> str:
    """A readable file a team can commit and review."""
    lines = [
        "# House rules",
        "",
        "Conventions Comodor has observed in this project and in the edits made to",
        "its output. Generated automatically — edit freely, or delete a rule you",
        "disagree with using `/rules`.",
        "",
    ]
    if project:
        lines += [f"Project: `{project}`", ""]

    by_category: dict[str, list] = {}
    for rule in rules:
        by_category.setdefault(rule.category, []).append(rule)

    for category in sorted(by_category):
        lines.append(f"## {category.title()}")
        lines.append("")
        for rule in sorted(by_category[category], key=lambda r: -r.support):
            evidence = f"{rule.support} for / {rule.against} against"
            source = {"correction": "learned from your edits",
                      "user": "you told me",
                      "observation": "observed in the code"}.get(rule.source, rule.source)
            lines.append(f"- **{rule.statement}**  ")
            lines.append(f"  <sub>{rule.detail or source} · {evidence} · "
                         f"{rule.strength:.0%} agreement</sub>")
        lines.append("")
    return "\n".join(lines)
