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
    #: What this particular observation was counted over, when it is not the
    #: sampled files as a whole — a layout observation names the directory
    #: structure it read, and is invalidated by that structure changing.
    source_ref: str = ""
    fingerprint: str = ""


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
    observations.extend(layout_signals(root))
    return observations


def sampled_files(root: Path, max_files: int = MAX_FILES) -> list[Path]:
    """The files `scan_project` would count, in the order it counts them."""
    found: list[Path] = []
    for path in _walk(root):
        if len(found) >= max_files:
            break
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        found.append(path)
    return found


def manifest_ref(root: Path, files: list[Path]) -> str:
    """What a counted convention was counted over: the sampled paths, relative."""
    names = []
    for path in files:
        try:
            names.append(path.relative_to(root).as_posix())
        except ValueError:
            names.append(str(path))
    return "sample:" + ",".join(names)


def manifest_fingerprint(files: list[Path]) -> str:
    """One fingerprint over the contents of the sampled files.

    A change to any of them changes this — which is the cue to re-count,
    not the verdict: a rule is stale only when re-counting flips what it
    says (see `learning/memory.py::LearningEngine.check_rule_staleness`).
    """
    import hashlib

    digest = hashlib.sha256()
    for path in files:
        try:
            digest.update(path.read_bytes())
        except OSError:
            continue
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def files_of(ref: str, root: Path) -> list[Path]:
    """The sampled files named by a `sample:` reference, resolved under `root`."""
    if not ref.startswith("sample:"):
        return []
    return [root / name for name in ref[len("sample:"):].split(",") if name]


def file_fingerprint(path: Path) -> str:
    """The fingerprint of one file's contents, or "" when it cannot be read."""
    import hashlib

    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def recount(files: list[Path], key: str, root: Path, statement: str = "") -> bool:
    """Whether the convention `key` still holds over `files`, counted afresh.

    This is the re-count behind rule-level staleness (T111): a changed
    fingerprint says the sample moved, and only a re-count says whether the
    verdict moved with it. It is no longer supported when the agreeing weight
    no longer outweighs the disagreeing weight, or when the convention the
    sample now shows contradicts `statement` — the tally may move without the
    verdict moving, but a flip from "use single quotes" to "use double quotes"
    is what "the source no longer supports it" means.
    """
    support = against = 0
    tallies: dict[str, int] = {}
    observations: list[Observation] = []
    for path in files:
        try:
            observations.extend(analyse_text(
                str(path), path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    observations.extend(_project_signals(root))
    for observation in observations:
        if observation.key != key:
            continue
        if observation.agrees:
            support += observation.weight
            normalised = _normalise(observation.statement)
            tallies[normalised] = tallies.get(normalised, 0) + observation.weight
        else:
            against += observation.weight
    if support <= 0 or support < against:
        return False
    if statement and tallies:
        # The prevailing convention, not the first file's: a sample with both
        # sides present is judged by the weighted majority, so a mixed sample
        # does not read as a flip while the counts are unchanged.
        prevailing = max(tallies.items(), key=lambda item: (item[1], item[0]))[0]
        if prevailing != _normalise(statement):
            return False
    return True


def _normalise(text: str) -> str:
    return " ".join((text or "").lower().split())


# --------------------------------------------------------------------------- #
# layout: the structure a repository has, counted from its directories
# --------------------------------------------------------------------------- #

LAYOUT_DEPTH = 2


def structure_fingerprint(root: Path) -> str:
    """A fingerprint of the directory structure, two levels deep.

    Names only, never contents: an architectural convention is about where
    things live, and this changes exactly when something is moved, added
    or removed — not when a file inside it is edited.
    """
    import hashlib

    names = sorted(_directories(root))
    digest = hashlib.sha256("\n".join(names).encode("utf-8", errors="replace"))
    return digest.hexdigest()[:16]


def layout_ref(root: Path) -> str:
    return "layout:" + ",".join(sorted(_directories(root, depth=1)))


def _directories(root: Path, depth: int = LAYOUT_DEPTH) -> list[str]:
    found: list[str] = []

    def walk(folder: Path, level: int) -> None:
        try:
            children = sorted(folder.iterdir())
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.name in SKIP_DIRS or child.name.startswith("."):
                continue
            found.append(child.relative_to(root).as_posix())
            if level + 1 < depth:
                walk(child, level + 1)

    walk(Path(root), 0)
    return found


def layout_signals(root: Path) -> list[Observation]:
    """Structural conventions counted across the repository (FR-107).

    Each one is counted from more than one place — a package directory
    *and* its files, a tests directory *and* what it holds — never
    inferred from a single file. The observation names the structure it
    read and carries its fingerprint, so moving that structure invalidates
    the rule (T108).
    """
    root = Path(root)
    observations: list[Observation] = []
    ref = layout_ref(root)
    fingerprint = structure_fingerprint(root)

    def structural(key: str, statement: str, detail: str) -> None:
        observations.append(Observation(
            key=key, category="workflow", statement=statement, detail=detail,
            weight=3, source_ref=ref, fingerprint=fingerprint))

    src = root / "src"
    packages = [child for child in _children(src)
                if child.is_dir() and (child / "__init__.py").is_file()]
    if packages:
        names = ", ".join(child.name for child in packages[:3])
        plural = "s" if len(packages) > 1 else ""
        structural("layout.src",
                   f"Source lives under src/ (package{plural}: {names}); put new modules there.",
                   f"{len(packages)} package(s) under src/")

    tests = root / "tests"
    test_files = [child for child in _children(tests)
                  if child.is_file() and child.name.startswith("test_")]
    if len(test_files) >= 2:
        structural("layout.tests", "Tests live under tests/ as test_*.py files.",
                   f"{len(test_files)} test files under tests/")

    workspace = [child for child in _children(root / "packages")
                 if child.is_dir() and (child / "package.json").is_file()]
    if len(workspace) >= 2:
        structural("layout.packages", "packages/ holds the workspace packages, one per directory.",
                   f"{len(workspace)} packages under packages/")

    apps = [child for child in _children(root / "apps") if child.is_dir()]
    if len(apps) >= 1 and workspace:
        structural("layout.apps", "apps/ holds the applications; shared code goes under packages/.",
                   f"{len(apps)} app(s) under apps/")

    return observations


def _children(folder: Path) -> list[Path]:
    try:
        return sorted(Path(folder).iterdir())
    except OSError:
        return []


# --------------------------------------------------------------------------- #
# what the user says: terminology and standing instructions
# --------------------------------------------------------------------------- #

_QUOTE = "\"'`\u201c\u201d\u2018\u2019"
_DEFINES = re.compile(
    r"[" + _QUOTE + r"](?P<term>[^" + _QUOTE + r"\n]{1,40})[" + _QUOTE + r"]\s+"
    r"(?:means|is|refers to|stands for|=)\s+(?P<definition>[^.\n;]{3,100})",
    re.IGNORECASE)
_CALLS = re.compile(
    r"\b(?:we|i|they)\s+call\s+(?P<definition>(?:the|our|this|that|a|an)\s+[\w\s-]{2,60}?)\s+"
    r"[" + _QUOTE + r"](?P<term>[^" + _QUOTE + r"\n]{1,40})[" + _QUOTE + r"]",
    re.IGNORECASE)
_MEANS_BY = re.compile(
    r"\bby\s+[" + _QUOTE + r"](?P<term>[^" + _QUOTE + r"\n]{1,40})[" + _QUOTE + r"]"
    r"\s+(?:i|we)\s+mean\s+(?P<definition>[^.\n;]{3,100})",
    re.IGNORECASE)


def analyse_terminology(text: str) -> list[Observation]:
    """Definitions the user gave in their own words (FR-106).

    Only an explicit definition counts — a word the user quoted and then
    explained. A term that merely recurs is usage, not a definition, and a
    term the model coined never comes through here at all: this reads the
    user's text and nothing else.
    """
    observations: list[Observation] = []
    seen: set[str] = set()
    for pattern in (_DEFINES, _CALLS, _MEANS_BY):
        for match in pattern.finditer(text or ""):
            term = " ".join(match.group("term").split())
            definition = " ".join(match.group("definition").split()).rstrip(" ,")
            if not term or not definition or term.lower() in seen:
                continue
            if len(term.split()) > 4:
                continue
            seen.add(term.lower())
            observations.append(Observation(
                key=f"term.{term.lower()}"[:80], category="terminology",
                statement=f"\"{term}\" means {definition}",
                detail="you defined it", weight=1))
    return observations


_INSTRUCTS = re.compile(
    r"(?:^|[.!?\n]\s*)(?:please,?\s+)?"
    r"(?P<lead>always|never|do not|don't|make sure (?:to|you)|remember to)\s+"
    r"(?P<tail>[^.!?\n]{6,120})",
    re.IGNORECASE)
_NEVER = ("never", "do not", "don't")


def analyse_instructions(text: str) -> list[Observation]:
    """Standing instructions in a user message (FR-108).

    One sentence in the imperative, led by a word that makes it standing
    rather than situational — *always*, *never*, *make sure*. The key
    carries the polarity and the instruction's subject, so a later
    instruction of the opposite polarity on the same subject is found as a
    contradiction and supersedes it.
    """
    observations: list[Observation] = []
    seen: set[str] = set()
    for match in _INSTRUCTS.finditer(text or ""):
        lead = match.group("lead").lower()
        tail = " ".join(match.group("tail").split()).rstrip(" ,")
        polarity = "never" if lead.startswith(_NEVER) else "always"
        slug = "-".join(re.findall(r"[a-z0-9]+", tail.lower())[:6])
        if not slug or slug in seen:
            continue
        seen.add(slug)
        wording = "Never" if polarity == "never" else "Always"
        observations.append(Observation(
            key=f"instruction.{polarity}.{slug}"[:80], category="preference",
            statement=f"{wording} {tail}.", detail="you asked for this more than once",
            weight=1))
    return observations


def opposite_key(key: str) -> str:
    """The key of the contradicting instruction, or ""."""
    if key.startswith("instruction.always."):
        return "instruction.never." + key[len("instruction.always."):]
    if key.startswith("instruction.never."):
        return "instruction.always." + key[len("instruction.never."):]
    return ""


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
        "its output. Generated automatically — edit freely, or retire a rule you",
        "disagree with: `comodor journey remove rule:ID`.",
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
