"""`comodor memory-provider` — the one optional external memory service.

Three verbs, matching the spec's setup|status|off. The local brain needs
none of this; everything here exists so a user who *wants* a cloud mirror
can turn it on, see that it answers, and turn it off again — and so the
key travels through the environment only, never through the config file
this program writes.
"""

from __future__ import annotations

import argparse

from rich.panel import Panel
from rich.text import Text

from ...config import Config


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "memory-provider",
        help="point the brain at one external memory service (optional)")
    actions = parser.add_subparsers(dest="provider_action")

    setup = actions.add_parser(
        "setup", help="configure the service and test that it answers")
    setup.add_argument("--kind", default="http_generic",
                       help="http_generic (or mem0, which speaks the same "
                            "dialect); default: http_generic")
    setup.add_argument("--base-url", required=True,
                       help="the service's root, e.g. http://127.0.0.1:9310")
    setup.add_argument("--key-env", default="MEM0_API_KEY",
                       help="which environment variable holds the key "
                            "(default: MEM0_API_KEY)")
    setup.add_argument("--augment", action="store_true",
                       help="also let the service add lines to recall "
                            "(default: writes only)")
    setup.add_argument("--no-mirror", action="store_true",
                       help="stop mirroring new facts (search-only use)")

    actions.add_parser("status",
                       help="what is configured, and whether it answers")
    actions.add_parser("off", help="forget the external service entirely")


def run(config: Config, args: argparse.Namespace) -> int:
    from ...ui import console as console_module

    theme = console_module.prepare_theme(config.ui.theme,
                                         config.ui.ascii_borders, no_color=False)
    console = console_module.build(theme)
    verb = getattr(args, "provider_action", None) or "status"

    if verb == "setup":
        return _setup(config, console, args)
    if verb == "off":
        return _off(config, console)
    return _status(config, console)

def _setup(config, console, args) -> int:
    section = config.learning.provider
    section.kind = str(args.kind).strip()
    section.base_url = str(args.base_url).strip().rstrip("/")
    section.key_env = str(args.key_env).strip() or "MEM0_API_KEY"
    section.mirror_writes = not args.no_mirror
    section.read_augment = bool(args.augment)

    from . import build

    try:
        provider = build(config)
    except Exception as problem:
        section.kind = ""
        console.print(Panel(
            Text(str(problem), style="red"),
            title="not set up — nothing was saved"))
        return 1
    answer = provider.status()
    config.save()
    if "unreachable" in answer or "answered " in answer:
        console.print(Panel(
            Text(f"saved, but the service did not answer: {answer}",
                 style="yellow"),
            title=f"memory provider — {section.base_url}"))
        return 0
    console.print(Panel(
        Text(f"saved. {answer}\n"
             f"new facts mirror to the service"
             f"{', and recall asks it for additions' if section.read_augment else ''}.\n"
             f"the key stays in ${section.key_env}; it is never written to disk.",
             style="green"),
        title=f"memory provider — {section.base_url}"))
    return 0

def _status(config, console) -> int:
    section = config.learning.provider
    if not section.kind:
        console.print(Panel(
            Text("no external memory service is configured — the local "
                 "brain is the whole of memory",
                 style="dim"),
            title="memory provider"))
        return 0
    from . import build

    try:
        provider = build(config)
    except Exception as problem:
        console.print(Panel(Text(str(problem), style="red"),
                            title=f"memory provider — {section.kind}"))
        return 1
    console.print(Panel(
        Text(f"{provider.status()}\n"
             f"mirror writes: {'yes' if section.mirror_writes else 'no'} · "
             f"augment recall: {'yes' if section.read_augment else 'no'}"),
        title=f"memory provider — {section.base_url}"))
    return 0

def _off(config, console) -> int:
    section = config.learning.provider
    had = bool(section.kind)
    section.kind = ""
    section.base_url = ""
    if had:
        config.save()
        console.print(Panel(
            Text("the external service is forgotten; the local brain was "
                 "always the source of truth and has lost nothing",
                 style="green"),
            title="memory provider"))
    else:
        console.print(Panel(
            Text("nothing to turn off", style="dim"),
            title="memory provider"))
    return 0
