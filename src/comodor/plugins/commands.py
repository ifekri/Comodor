"""`comodor plugins` — what is installed, and who is allowed to run.

The trust decision is the command's whole reason to exist: `list` shows what
was found and what it would add, `trust` prints what a scan of the file
turned up *before* asking anything, and `untrust` takes the permission back.
Nothing here runs a plugin's code.
"""

from __future__ import annotations

import argparse

from ..config import Config


def register(subparsers: argparse._SubParsersAction) -> None:
    """Wire `comodor plugins ...` into the argument parser."""
    parser = subparsers.add_parser(
        "plugins", help="plugins: the user's own tools, hooks and commands")
    actions = parser.add_subparsers(dest="plugins_action")

    actions.add_parser("list", help="what is installed, and whether it loads")

    trust = actions.add_parser(
        "trust", help="allow a project's plugins to load, after showing "
                      "what a scan found")
    trust.add_argument("name")

    untrust = actions.add_parser(
        "untrust", help="revoke trust from a project's plugins")
    untrust.add_argument("name")

    actions.add_parser("doctor", help="why a plugin is not loading")


def run(config: Config, args: argparse.Namespace) -> int:
    from .manager import PluginManager

    manager = PluginManager(
        config.paths,
        trusted_folders=list(getattr(config.safety, "trusted_folders", ())),
    )
    manager.discover()
    action = getattr(args, "plugins_action", None) or "list"
    handlers = {"list": _list, "trust": _trust, "untrust": _untrust,
                "doctor": _doctor}
    handler = handlers.get(action)
    if handler is None:
        return 2

    code = handler(config, args, manager)
    if manager.trusted_folders != list(getattr(config.safety,
                                               "trusted_folders", ())):
        # Trust changed: remember it the way the workspace guard does, in the
        # same list, so one place answers "what has this user said yes to".
        config.safety.trusted_folders = manager.trusted_folders
        config.save()
    return code


# --------------------------------------------------------------------------- #
# the actions
# --------------------------------------------------------------------------- #

def _list(config: Config, args: argparse.Namespace, manager) -> int:
    states = manager.load_all()
    if not states:
        print("No plugins installed.")
        print("\nA plugin is a folder with a plugin.py in it, defining "
              "register(ctx):")
        print(f"  {manager.paths.user / 'plugins' / '<name>' / 'plugin.py'}")
        return 0

    width = max(len(state.name) for state in states)
    for state in states:
        where = "user" if state.source == "user" else "project"
        if state.source == "project" and not state.trusted:
            mark = "untrusted"
        else:
            mark = "trusted"
        print(f"  {state.name:<{width}}  {where:<8} {mark}")
        if state.context:
            for spec in state.context.tools:
                print(f"  {'':<{width}}    tool: {spec['name']} "
                      f"({spec['risk'].lower()})")
            for kind, _ in state.context.hooks:
                print(f"  {'':<{width}}    hook: {kind}")
            for note in state.context.notes[:3]:
                print(f"  {'':<{width}}    {note}")
        if state.error:
            print(f"  {'':<{width}}    error: {state.error}")
        if state.source == "project" and not state.trusted:
            print(f"  {'':<{width}}    comodor plugins trust {state.name} "
                  f"to allow it")
    return 0


def _trust(config: Config, args: argparse.Namespace, manager) -> int:
    state = manager.states.get(args.name)
    if state is None:
        print(f"no plugin called {args.name!r}.", file=__import__("sys").stderr)
        return 1
    if state.source == "user":
        print("Plugins in your own directory are already trusted.")
        return 0

    print(f"Scanning {state.path}…")
    findings = manager.scan(args.name)
    if findings:
        print("\nThe scan found things worth reading before you decide:")
        for finding in findings:
            print(f"  - {finding}")
    else:
        print("\nThe scan found nothing notable — which is not a "
              "certificate. Reading the file yourself is.")
    print(f"\nTrusting lets the plugin run code on this machine whenever "
          f"Comodor starts in {state.path.parents[2]}.")
    print("Its tools will still ask permission before they act, exactly "
          "like built-in ones.")
    print("\nTo confirm, run the same command with --yes.")
    return 0 if not findings else 1


def _untrust(config: Config, args: argparse.Namespace, manager) -> int:
    if manager.untrust(args.name):
        print(f"{args.name} will not load again. The files are untouched.")
        return 0
    print(f"{args.name!r} is not a trusted project plugin.",
          file=__import__("sys").stderr)
    return 1


def _doctor(config: Config, args: argparse.Namespace, manager) -> int:
    states = manager.load_all()
    if not states:
        print("No plugins installed, so nothing to diagnose.")
        return 0
    problems = 0
    for state in states:
        if state.ok:
            continue
        problems += 1
        print(f"{state.name}: not running.")
        if not state.trusted:
            print("  it is from a project and has not been trusted — "
                  f"`comodor plugins trust {state.name}`")
        if state.error:
            print(f"  {state.error}")
    if not problems:
        print("Every installed plugin loaded.")
    return 1 if problems else 0
