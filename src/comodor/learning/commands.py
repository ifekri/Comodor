"""The `comodor curator` command line.

The curator works on its own schedule and reports what it did; these verbs
are the human's hand on it: run a pass now, read the report, restore an
archived skill, pin a lesson so it is never marked stale, or pause the
whole thing. Every verb prints what it actually did — a maintenance pass
that claims to have worked without saying what it touched is not
maintenance, it is a shrug.
"""

from __future__ import annotations

import argparse

from ..config import Config


def register(sub: argparse._SubParsersAction) -> None:
    curator = sub.add_parser(
        "curator", help="run, read, or steer the brain's maintenance pass")
    verbs = curator.add_subparsers(dest="verb")

    verbs.add_parser("run", help="do a pass now, regardless of the interval")
    verbs.add_parser("report", help="print the last pass's report")
    verbs.add_parser("pause", help="stop the curator from running on its own")
    verbs.add_parser("resume", help="let the curator run on its own again")

    pin = verbs.add_parser("pin", help="exempt a skill from stale/archive")
    pin.add_argument("name", help="the skill's folder name")
    unpin = verbs.add_parser("unpin", help="let the curator curate a skill again")
    unpin.add_argument("name")

    restore = verbs.add_parser("restore",
                               help="bring an archived skill back")
    restore.add_argument("name", help="the skill's folder name")


def run(config: Config, args: argparse.Namespace) -> int:
    from ..ui import console as console_module

    theme = console_module.prepare_theme(config.ui.theme,
                                         config.ui.ascii_borders, no_color=False)
    console = console_module.build(theme)
    verb = getattr(args, "verb", None) or "report"

    if verb == "run":
        return _run(config, console)
    if verb == "report":
        return _report(config, console)
    if verb == "pause":
        return _pause(config, console, paused=True)
    if verb == "resume":
        return _pause(config, console, paused=False)
    if verb == "pin":
        return _pin(config, console, args.name, pinned=True)
    if verb == "unpin":
        return _pin(config, console, args.name, pinned=False)
    if verb == "restore":
        return _restore(config, console, args.name)
    return _report(config, console)


def _store(config: Config):
    from .store import BrainStore

    return BrainStore(config.paths.brain_db)


def _run(config: Config, console) -> int:
    from . import curator

    report = curator.run(_store(config), config, skills_root=config.paths.skills)
    if not report.actions:
        console.print("\n  Nothing needed doing. The brain is tidy.\n")
        return 0
    console.print(f"\n  {report.line()}\n")
    console.print(f"  [dim]details: {curator.report_path(config)}[/dim]\n")
    return 0


def _report(config: Config, console) -> int:
    from . import curator

    path = curator.report_path(config)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        console.print("\n  No report yet — the curator has not run.\n")
        return 0
    console.print(f"\n{text}")
    return 0


def _pause(config: Config, console, *, paused: bool) -> int:
    from . import curator

    store = _store(config)
    state = curator.load_state(store)
    state["paused"] = paused
    curator.save_state(store, state)
    console.print(f"\n  {'Paused.' if paused else 'Running again.'}\n")
    return 0


def _pin(config: Config, console, name: str, *, pinned: bool) -> int:
    from ..skills.usage import UsageStore

    store = UsageStore(config.paths.skills)
    record = store.get(name)
    if not record and pinned:
        console.print(f"\n  [bad]no skill named {name!r}[/bad]\n")
        return 1

    def change(entry):
        entry.pinned = pinned
        entry.note = "pinned — exempt from the curator" if pinned else ""
        return entry

    store.update(name, change)
    console.print(f"\n  {'Pinned' if pinned else 'Unpinned'} {name}.\n")
    return 0


def _restore(config: Config, console, name: str) -> int:
    from . import curator

    console.print(f"\n  {curator.rollback_skill(config.paths.skills, name)}\n")
    return 0
