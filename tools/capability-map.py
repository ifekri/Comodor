#!/usr/bin/env python3
"""Write CAPABILITIES.md by asking the code what it can do.

Generated, not written. A hand-maintained inventory is a snapshot of what
somebody believed on the day they wrote it, and this file exists precisely
because "I thought that part worked" is expensive to discover mid-task.

    python tools/capability-map.py            # rewrite CAPABILITIES.md
    python tools/capability-map.py --check    # fail if anything is broken

The `--check` form is what a CI job or a pre-commit hook would run. It
checks the *substance* rather than diffing against the file: the map is
git-ignored, so a clean checkout has no baseline and a diff would fail every
time on the machine the mode is meant for. Instead it asks whether every
channel is connectable, every command in the smoke list is real, and every one
of them answers.

Everything in the output comes from importing the package and reading its
registries. Nothing is typed in twice, so nothing can disagree with itself.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "CAPABILITIES.md"
sys.path.insert(0, str(ROOT / "src"))


# --------------------------------------------------------------------------- #
# gathering
# --------------------------------------------------------------------------- #


def commands() -> list[tuple[str, str]]:
    """Every CLI command and sub-command, with its help line."""
    from comodor.cli import build_parser

    found: list[tuple[str, str]] = []
    for action in build_parser()._actions:
        # A subparsers action holds a dict; an ordinary `--flag` with fixed
        # values holds a tuple. Only the first kind is a command.
        top = getattr(action, "choices", None)
        if not isinstance(top, dict):
            continue
        # `help=` is what `add_parser` is usually given and it lands on the
        # subparsers action, not on the parser it makes. Reading only
        # `description` produced a table of a hundred empty cells.
        helps = {choice.dest: (choice.help or "")
                 for choice in getattr(action, "_choices_actions", [])}
        for name, parser in top.items():
            found.append((name, _one_line(helps.get(name) or parser.description)))
            for inner in getattr(parser, "_actions", []):
                nested = getattr(inner, "choices", None)
                if not isinstance(nested, dict):
                    continue
                inner_helps = {choice.dest: (choice.help or "")
                               for choice in
                               getattr(inner, "_choices_actions", [])}
                for leaf, sub in nested.items():
                    found.append((
                        f"{name} {leaf}",
                        _one_line(inner_helps.get(leaf) or sub.description)))
    return sorted(set(found))


def _one_line(text: str | None) -> str:
    """A help string as one table cell: first line, pipes escaped."""
    first = (text or "").strip().split("\n")[0].strip()
    return first.replace("|", "\\|")


def tools_by_mode() -> dict[str, list[str]]:
    """What the agent is offered, per mode, in a default registry."""
    from comodor.tools import ToolRegistry

    registry = ToolRegistry()
    return {mode: sorted(spec.name for spec in registry.specs(mode))
            for mode in ("act", "plan", "ask", "chat")}


def optional_tools() -> list[tuple[str, str]]:
    """Tools that exist but are not in a bare registry, and what turns them on.

    Read from the registry's own source: it is the only place that knows, and
    a list kept anywhere else would be the thing that goes stale.
    """
    import inspect

    from comodor.tools import ToolRegistry

    source = inspect.getsource(ToolRegistry.__init__)
    bare = {name for names in tools_by_mode().values() for name in names}

    everything = {}
    for path in sorted((ROOT / "src" / "comodor" / "tools").glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("name = \"") and stripped.endswith("\""):
                everything[stripped[8:-1]] = path.stem
                break

    out = []
    for name, module in sorted(everything.items()):
        if name in bare:
            continue
        # The condition guarding it, taken from the line above where it is
        # added, so this says *why* it is absent rather than only that it is.
        why = ""
        for index, line in enumerate(source.splitlines()):
            if module in line or name in line:
                for back in range(index - 1, max(index - 6, -1), -1):
                    candidate = source.splitlines()[back].strip()
                    if candidate.startswith("if "):
                        why = candidate[3:].rstrip(":")
                        break
                break
        out.append((name, why or f"see tools/{module}.py"))
    return out


def channels() -> list[dict]:
    from comodor.channels import CHANNELS
    from comodor.web.session import Session

    out = []
    for channel in CHANNELS:
        settings_type = type(getattr(__import__("comodor.config",
                                                fromlist=["Config"]).Config(),
                                     channel.section))
        out.append({
            "name": channel.name,
            "label": channel.label,
            "form": [field["key"] for field in
                     Session._channel_needs(channel.name)],
            "bot": _has(f"comodor.{channel.name}.bot"),
            "cli": _has(f"comodor.{channel.name}.commands"),
            "settings": settings_type.__name__,
        })
    return out


def _has(dotted: str) -> bool:
    try:
        importlib.import_module(dotted)
        return True
    except Exception:
        return False


def providers() -> list[tuple[str, str, str]]:
    from comodor import catalogue

    return [(spec.id, spec.label, spec.env_key or "—")
            for spec in catalogue.CATALOGUE]


def sections() -> list[str]:
    from comodor.config import SECTIONS

    return list(SECTIONS)


def coverage() -> dict[str, object]:
    """How much of the suite there is, and what nothing names."""
    tests = list((ROOT / "tests").glob("test_*.py"))
    text = " ".join(path.read_text(encoding="utf-8", errors="replace")
                    for path in tests)

    unnamed = []
    for path in sorted((ROOT / "src" / "comodor").rglob("*.py")):
        if "__pycache__" in str(path) or path.name == "__init__.py":
            continue
        dotted = (str(path.relative_to(ROOT / "src"))
                  .replace("\\", ".").replace("/", ".")[:-3])
        leaf = dotted.rsplit(".", 1)[-1]
        if dotted not in text and f"import {leaf}" not in text \
                and f"{leaf}." not in text:
            unnamed.append(dotted)

    return {
        "files": len(tests),
        "tests": sum(path.read_text(encoding="utf-8", errors="replace")
                     .count("\ndef test_") for path in tests),
        "unnamed": unnamed,
    }


#: Commands that report rather than change anything: safe to run on the
#: machine generating this, in any state, without a key or a network.
#:
#: Chosen by what they touch, not by what they are called. `--help` on every
#: command would prove only that argparse works; these each reach into a
#: subsystem and come back, which is the difference between "it parses" and
#: "it runs".
#: `doctor` is the one command that reports a finding as exit 1, and it does
#: so on a healthy install with an unconfigured provider. Every other command
#: exiting 1 has failed — including the one that matters most here, a child
#: that cannot import the package at all: `python -m comodor` exits 1 with
#: "No module named comodor" and no traceback, which an "exit 0 or 1 is fine"
#: rule reports as twenty working subsystems.
MAY_EXIT_ONE = {"comodor doctor"}

SAFE_COMMANDS = [
    ("comodor --version", ["--version"]),
    ("comodor --help", ["--help"]),
    ("comodor help", ["help"]),
    ("comodor doctor", ["doctor"]),
    ("comodor cron list", ["cron", "list"]),
    ("comodor cron status", ["cron", "status"]),
    ("comodor skills list", ["skills", "list"]),
    ("comodor mcp list", ["mcp", "list"]),
    ("comodor telegram status", ["telegram", "status"]),
    ("comodor slack status", ["slack", "status"]),
    ("comodor whatsapp status", ["whatsapp", "status"]),
    ("comodor discord status", ["discord", "status"]),
    ("comodor curator report", ["curator", "report"]),
    ("comodor insights", ["insights"]),
    ("comodor approvals", ["approvals"]),
    ("comodor plugins list", ["plugins", "list"]),
    ("comodor memory-provider status", ["memory-provider", "status"]),
    ("comodor journey", ["journey", "--help"]),
    ("comodor webhook list", ["webhook", "list"]),
]


def smoke() -> list[tuple[str, bool, str]]:
    """Run each one and record what happened.

    A non-zero exit is not automatically a failure: `doctor` exits 1 when it
    has something to report, which is a working doctor. What is always a
    failure is a traceback, because that is the program falling over rather
    than answering.
    """
    # The child gets `src` on its path explicitly. `sys.path.insert` at the
    # top of this file changes *this* interpreter and nothing else, and `cwd`
    # does not make a src-layout package importable — so without this the
    # child imports whatever is in site-packages, which is precisely the stale
    # copy this file exists to catch. An uninstalled checkout could not import
    # it at all.
    environment = dict(os.environ)
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        str(ROOT / "src") + (os.pathsep + existing if existing else ""))

    out = []
    for label, args in SAFE_COMMANDS:
        try:
            # `encoding` and `errors` explicitly: the banner is drawn with box
            # characters, and on a Windows console `text=True` decodes with
            # cp1252 and raises on the first one — which reads as the command
            # having failed when it printed its output perfectly.
            done = subprocess.run([sys.executable, "-m", "comodor", *args],
                                  cwd=ROOT, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  env=environment, timeout=180)
            output = (done.stdout or "") + (done.stderr or "")
            allowed = {0, 1} if label in MAY_EXIT_ONE else {0}

            if "Traceback (most recent call last)" in output:
                last = [line for line in output.strip().splitlines()
                        if line.strip()][-1]
                out.append((label, False, f"crashed — {last.strip()[:90]}"))
            elif done.returncode not in allowed:
                # The last line, because "exit 1" alone is what let "No module
                # named comodor" read as a working command.
                said = ""
                if output.strip():
                    said = " — " + output.strip().splitlines()[-1][:70]
                out.append((label, False, f"exit {done.returncode}{said}"))
            else:
                out.append((label, True, f"exit {done.returncode}"))
        except subprocess.TimeoutExpired:
            out.append((label, False, "did not finish in 180s"))
        except Exception as problem:
            out.append((label, False, f"{type(problem).__name__}: {problem}"))
    return out


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #


def render() -> str:
    modes = tools_by_mode()
    cover = coverage()
    lines: list[str] = []
    w = lines.append

    w("# What Comodor can do, and where each part lives")
    w("")
    w("**Generated by `tools/capability-map.py`. Do not edit by hand.**")
    w("")
    w("Regenerate after adding a command, a tool, a channel or a provider:")
    w("")
    w("```")
    w("python tools/capability-map.py")
    w("python tools/capability-map.py --check   # fails if out of date")
    w("```")
    w("")
    w("Git-ignored. This is a map of the machine for whoever is working on")
    w("it — `docs/` is what users read, and `PROJECT.md` is why the code is")
    w("shaped the way it is. This one answers *what exists and does it work*.")
    w("")
    w("---")
    w("")

    # -- commands ------------------------------------------------------- #
    entries = commands()
    w(f"## The command line — {len(entries)} commands")
    w("")
    w("Everything reachable from `comodor`. Sub-commands are indented under")
    w("the group that registers them.")
    w("")
    w("| Command | What it does |")
    w("| --- | --- |")
    for name, help_line in entries:
        shown = f"`{name}`" if " " not in name else f"&nbsp;&nbsp;`{name}`"
        w(f"| {shown} | {help_line or '—'} |")
    w("")

    # -- tools ---------------------------------------------------------- #
    w("## What the agent may use")
    w("")
    w("The mode decides. This is a registry built with nothing optional")
    w("attached, which is what a plain `comodor run` produces.")
    w("")
    w("| Mode | Tools |")
    w("| --- | --- |")
    for mode in ("act", "plan", "ask", "chat"):
        names = modes[mode]
        w(f"| `{mode}` | {', '.join(f'`{n}`' for n in names) or '— none —'} |")
    w("")

    extra = optional_tools()
    if extra:
        w("### Only where something supplies them")
        w("")
        w("These exist and are not in the list above. A registry built inside")
        w("a delegate or a scheduled run deliberately has fewer.")
        w("")
        w("| Tool | Offered when |")
        w("| --- | --- |")
        for name, why in extra:
            w(f"| `{name}` | `{why}` |")
        w("")

    # -- channels ------------------------------------------------------- #
    found = channels()
    w(f"## Channels — {len(found)}")
    w("")
    w("| Channel | Panel form | Bot | CLI | Config |")
    w("| --- | --- | --- | --- | --- |")
    for entry in found:
        form = ", ".join(f"`{key}`" for key in entry["form"]) or "**none**"
        w(f"| {entry['label']} | {form} | {'yes' if entry['bot'] else '**no**'} "
          f"| {'yes' if entry['cli'] else '**no**'} | `{entry['settings']}` |")
    w("")
    w("A channel with no panel form is one the web panel lists and cannot")
    w("connect — worth catching here rather than from a bug report.")
    w("")

    # -- providers ------------------------------------------------------ #
    catalogue_rows = providers()
    w(f"## Providers — {len(catalogue_rows)}")
    w("")
    w("| Id | Name | Key from |")
    w("| --- | --- | --- |")
    for provider_id, label, env in catalogue_rows:
        w(f"| `{provider_id}` | {label} | `{env}` |")
    w("")

    # -- config --------------------------------------------------------- #
    w(f"## Configuration — {len(sections())} sections")
    w("")
    w(" ".join(f"`{name}`" for name in sections()))
    w("")
    w("Each is a dataclass in `config.py` and a block in `config.json`.")
    w("`load()` merges the user's file, then the project's `.comodor/`, then")
    w("the environment — see `PROJECT.md` for what a project file may not do.")
    w("")

    # -- what runs ------------------------------------------------------ #
    results = smoke()
    broken = [row for row in results if not row[1]]
    w("## Does it run")
    w("")
    w("Each of these was actually run while this file was written — not")
    w("`--help` on everything, which would prove only that argparse works,")
    w("but commands that reach into a subsystem and come back.")
    w("")
    if broken:
        w(f"**{len(broken)} of {len(results)} are broken right now.**")
    else:
        w(f"All {len(results)} answered.")
    w("")
    w("| Check | Result |")
    w("| --- | --- |")
    for label, ok, detail in results:
        w(f"| `{label}` | {'ok' if ok else '**BROKEN**'} — {detail} |")
    w("")
    w("An exit code of 1 is not a failure here: `doctor` uses it to mean it")
    w("found something to report. A traceback always is.")
    w("")

    # -- coverage ------------------------------------------------------- #
    w("## Test coverage")
    w("")
    w(f"**{cover['tests']} tests across {cover['files']} files.**")
    w("")
    w("Run them with `pytest`. The parallel settings are in `pyproject.toml`,")
    w("and tests that measure wall-clock time are marked `performance` and")
    w("run separately — `pytest -m performance -n 0`.")
    w("")
    unnamed = cover["unnamed"]
    if unnamed:
        w(f"### {len(unnamed)} modules no test file names")
        w("")
        w("Not proof of no coverage — a module can be exercised through")
        w("another one — but each is worth a look.")
        w("")
        for dotted in unnamed:
            w(f"- `{dotted}`")
        w("")

    w("---")
    w("")
    w("*Generated from the source. If something here is wrong, the code is")
    w("what changed — regenerate rather than editing this file.*")
    return "\n".join(lines) + "\n"


def check() -> int:
    """Whether the things the map reports are actually true, right now.

    Not a diff against the file on disk. The map is git-ignored — it records
    what answered on one machine at one moment — so a clean checkout has no
    baseline, and comparing against a missing file would fail every time on
    the exact machine this mode is meant for.

    What can be checked anywhere is the *substance*: every channel connectable,
    every command in the smoke list real, and every one of them answering.
    That is what a CI job or a hook wants to know.
    """
    problems: list[str] = []

    for entry in channels():
        if not entry["form"]:
            problems.append(
                f"channel {entry['name']} has no form — the panel lists it "
                f"and cannot connect it")
        if not entry["bot"]:
            problems.append(f"channel {entry['name']} has no bot module")
        if not entry["cli"]:
            problems.append(f"channel {entry['name']} has no CLI")

    # Every command named in the smoke list must exist. A name that does not
    # reports a working subsystem as broken, which is the same lie reversed.
    top: dict = {}
    for action in _parser()._actions:
        if isinstance(getattr(action, "choices", None), dict):
            top = action.choices
            break
    for label, args in SAFE_COMMANDS:
        if args[0].startswith("--"):
            continue
        command, *rest = args
        if command not in top:
            problems.append(f"{label}: there is no `{command}` command")
            continue
        if rest and not rest[0].startswith("--"):
            nested: dict = {}
            for inner in top[command]._actions:
                if isinstance(getattr(inner, "choices", None), dict):
                    nested = inner.choices
                    break
            if rest[0] not in nested:
                problems.append(
                    f"{label}: `{command}` has no `{rest[0]}` sub-command")

    for label, ok, detail in smoke():
        if not ok:
            problems.append(f"{label}: {detail}")

    if problems:
        print(f"{len(problems)} problems:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print("every channel is connectable and every checked command answered")
    return 0


def _parser():
    from comodor.cli import build_parser

    return build_parser()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="fail if any checked capability is broken")
    parser.add_argument("--json", action="store_true",
                        help="print the gathered facts instead of the page")
    args = parser.parse_args()

    if args.json:
        print(json.dumps({
            "commands": commands(),
            "tools": tools_by_mode(),
            "optional_tools": optional_tools(),
            "channels": channels(),
            "providers": providers(),
            "sections": sections(),
            "coverage": coverage(),
        }, indent=2))
        return 0

    if args.check:
        return check()

    fresh = render()
    OUT.write_text(fresh, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(fresh.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
