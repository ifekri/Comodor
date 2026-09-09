"""`comodor core` — the agent with no interface at all.

A client spawns this, speaks the versioned protocol over the pipe, and renders
whatever it likes. It prints nothing a person is meant to read: the first line
on stdout is a protocol message, and the greeting goes to stderr where a client
can log it or ignore it.

    comodor core --stdio

`--stdio` is explicit rather than implied, because a future named pipe or
socket is a second flag on this command and not a second command. There is no
default: a bare `comodor core` says which transports it knows instead of
guessing at one.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import Config
from ..protocol import PROTOCOL_LABEL


def register(sub) -> None:
    core = sub.add_parser(
        "core", help="run the agent as a protocol server for a client to drive")
    core.add_argument("--stdio", action="store_true",
                      help=f"speak {PROTOCOL_LABEL} on stdin and stdout")

    # The new client lives here rather than in its own module because it is
    # the other half of one story — a core to drive, and the thing that
    # drives it — and a package holding one function would say less.
    sub.add_parser(
        "tui-v2", help="the new terminal interface (in development; the "
                       "stable one is still `comodor`)")


def run_tui(config: Config, args: argparse.Namespace) -> int:
    """Start TUI v2, or say plainly why it cannot start.

    Deliberately a separate command from `comodor`. The stable interface is
    not replaced until this one has been proven at parity — a migration that
    swaps the default first is one where every gap is discovered by a person
    trying to work.

    Setup-aware, because the renderer spawns a core over the protocol, and a
    core with no configured provider renders a conversation that cannot be
    answered. A first run of `comodor tui-v2` therefore asks the same questions
    `comodor` asks — through the same canonical setup path, in the same
    invocation — and starts only if they were answered. This is not a second
    setup wizard: it reuses `SetupPlan`, the terminal adapter and the trusted
    secret boundary, so there is nothing to keep in step and no second shell
    command to run. The launcher's own requirements (a source checkout, Bun)
    are checked first, so nobody answers setup only to be told the renderer
    cannot start.
    """
    import os
    import shutil
    import subprocess

    root = Path(__file__).resolve().parents[3]
    entry = root / "apps" / "tui" / "src" / "main.tsx"
    if not entry.exists():
        print("comodor tui-v2 runs from a source checkout; this install has "
              "no apps/tui.", file=sys.stderr)
        return 2

    runtime = shutil.which("bun")
    if not runtime:
        # Named exactly, because "install the dependencies" is not actionable.
        print(
            "comodor tui-v2 needs Bun.\n\n"
            "OpenTUI draws through native code bound with `bun:ffi`. Node has "
            "no equivalent — `node:ffi` is not a module in any released "
            "version — so the renderer cannot start under it. Every other "
            "part of this workspace runs on Node.\n\n"
            "  https://bun.sh\n\n"
            "Then, from the repository root:  bun run apps/tui/src/main.tsx",
            file=sys.stderr)
        return 2

    if config.needs_setup:
        from ..setup import run_setup

        try:
            config = run_setup(config)
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled; TUI v2 was not started.", file=sys.stderr)
            return 130
        if config.needs_setup:
            # run_setup stopped short of a usable configuration — it says why
            # itself. Starting now would spawn a core with nothing to talk to.
            print("Setup did not finish, so there is no configured provider "
                  "for TUI v2 to drive. Run `comodor setup` when you are "
                  "ready.", file=sys.stderr)
            return 1

    environment = dict(os.environ)
    # The child spawns its own core, and it must be this one rather than
    # whatever `comodor` happens to be on the path.
    environment.setdefault("COMODOR_BIN", sys.executable)
    environment.setdefault("COMODOR_ARGS", "-m comodor")
    return subprocess.call([runtime, "run", str(entry)], cwd=str(
        config.paths.project), env=environment)


def run(config: Config, args: argparse.Namespace) -> int:
    if not getattr(args, "stdio", False):
        print("comodor core: choose a transport.\n\n"
              f"  comodor core --stdio    {PROTOCOL_LABEL} on stdin and stdout\n\n"
              "A client spawns this and drives the agent over the pipe; "
              "there is nothing to read here by hand.", file=sys.stderr)
        return 2

    from . import serve_stdio

    return serve_stdio(config)
