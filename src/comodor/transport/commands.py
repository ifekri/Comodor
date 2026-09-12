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

from ..config import Config
from ..protocol import PROTOCOL_LABEL


def register(sub) -> None:
    core = sub.add_parser(
        "core", help="run the agent as a protocol server for a client to drive")
    core.add_argument("--stdio", action="store_true",
                      help=f"speak {PROTOCOL_LABEL} on stdin and stdout")

    # The production interface lives here rather than in its own module
    # because it is the other half of one story — a core to drive, and the
    # thing that drives it. `tui-v2` is kept as a compatibility alias for the
    # same canonical launcher the bare command uses; two entry paths, one
    # implementation.
    sub.add_parser(
        "tui-v2", help="alias for `comodor` — the terminal interface")


def run_tui(config: Config, args: argparse.Namespace) -> int:
    """Start the production TUI, or say plainly why it cannot start.

    Setup-aware, because the renderer spawns a core over the protocol, and a
    core with no configured provider renders a conversation that cannot be
    answered. A first run asks the same questions `comodor setup` asks —
    through the same canonical setup path, in the same invocation — and
    starts only once they are answered. The launcher's own requirements (a
    renderer artifact, Bun) are checked first, so nobody answers setup only
    to be told the interface cannot start.

    The renderer runs from the installed package's own artifact when there is
    one, and from the development tree in a source checkout. Nothing is
    downloaded here: the package already carries everything Comodor itself is
    responsible for shipping.
    """
    import os
    import subprocess

    from ..tui import runtime as tui_runtime

    target, origin = tui_runtime.renderer()
    if target is None:
        print("comodor: no TUI renderer is available in this install.\n\n"
              "The production renderer ships inside the package at "
              "`comodor/tui/dist`; it is missing here. Reinstall Comodor, "
              "or run from a source checkout where `apps/tui` is present.",
              file=sys.stderr)
        return 2

    executable = tui_runtime.bun()
    if executable is None:
        print("comodor needs Bun to draw the interface.\n\n"
              "OpenTUI draws through native code bound with `bun:ffi`. Node "
              "has no equivalent — `node:ffi` is not a module in any released "
              "version — so the renderer cannot start under it.\n\n"
              "  Install Bun from https://bun.sh, then run `comodor` again.\n\n"
              "Without it: `comodor run \"...\"` does one task with no "
              "interface, and `comodor web` serves one to a browser.",
              file=sys.stderr)
        return 2

    # Present is not enough. `bun:ffi` arrived in 1.3, and a Bun older than
    # that gets as far as the bundled JavaScript before failing inside it —
    # a stack trace from the renderer, where a sentence from here was
    # possible. Unreadable is treated the same way: a `bun --version` that
    # cannot be parsed is not one the renderer has been proven on.
    found = tui_runtime.bun_version(executable)
    wanted = ".".join(str(part) for part in tui_runtime.MIN_BUN)
    if found is None or found < tui_runtime.MIN_BUN:
        have = ".".join(str(part) for part in found) if found else "unknown"
        print(f"comodor needs Bun {wanted} or newer to draw the interface; "
              f"the one on the path ({executable}) reports {have}.\n\n"
              "  Upgrade it — `bun upgrade`, or https://bun.sh — then run "
              "`comodor` again.\n\n"
              "Without it: `comodor run \"...\"` does one task with no "
              "interface, and `comodor web` serves one to a browser.",
              file=sys.stderr)
        return 2

    if origin == "package":
        # The same check `comodor doctor` makes, made before anything is
        # spawned. An installed artifact can be incomplete — a wheel built
        # for another platform, a file that did not survive the install —
        # and `renderer()` hands such an artifact back on purpose so the
        # refusal can name what is wrong with it, rather than starting Bun
        # and letting the renderer discover the same thing less clearly.
        problems = tui_runtime.verify(target)
        if problems:
            listed = "\n".join(f"  - {problem}" for problem in problems)
            print("comodor: the packaged renderer cannot run on this "
                  f"machine.\n\n{listed}\n\n"
                  "Reinstall Comodor to repair it. Until then: `comodor run "
                  "\"...\"` does one task with no interface, and `comodor "
                  "web` serves one to a browser.",
                  file=sys.stderr)
            return 2

    if config.needs_setup:
        from ..setup import run_setup

        try:
            config = run_setup(config)
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled; the interface was not started.",
                  file=sys.stderr)
            return 130
        if config.needs_setup:
            # run_setup stopped short of a usable configuration — it says why
            # itself. Starting now would spawn a core with nothing to talk to.
            print("Setup did not finish, so there is no configured provider "
                  "for the interface to drive. Run `comodor setup` when you "
                  "are ready.", file=sys.stderr)
            return 1

    if not getattr(args, "demo", False) and not (
            sys.stdin.isatty() and sys.stdout.isatty()):
        # A renderer writes terminal control. Into a pipeline that is not a
        # screen, it is garbage; into a log, worse. `--demo` is the one
        # deliberate exception, because it is the scripted smoke path.
        print("comodor needs an interactive terminal for the interface.\n\n"
              "For one task without it: `comodor run \"...\"`. For a browser: "
              "`comodor web`.",
              file=sys.stderr)
        return 2

    entry = (target / tui_runtime.ENTRY_NAME) if origin == "package" else target
    environment = dict(os.environ)
    # The child spawns its own core, and it must be this one rather than
    # whatever `comodor` happens to be on the path. The flags that configure
    # the core travel with it: the spawned process parses them itself, so
    # `comodor --provider X --mode plan` means the core is answering as X
    # in plan, not merely that the launcher agreed to say so.
    forward = ["-m", "comodor"]
    for flag in ("provider", "model", "mode"):
        value = getattr(args, flag, None)
        if value:
            forward += [f"--{flag}", str(value)]
    if getattr(args, "no_loop", False):
        forward += ["--no-loop"]
    environment.setdefault("COMODOR_BIN", sys.executable)
    environment["COMODOR_ARGS"] = " ".join(forward)
    if getattr(args, "demo", False):
        # Demo is a contract the spawned core honours itself; see `cli.main`.
        environment["COMODOR_DEMO"] = "1"
    resume = getattr(args, "resume", None)
    if resume:
        # Reopening is the client's to ask of the core; the launcher names
        # which. `__pick__` is the flag with no id and means "the newest".
        environment["COMODOR_RESUME"] = "" if resume == "__pick__" else resume

    for printing_flag in ("theme", "ascii"):
        if getattr(args, printing_flag, None):
            # Both are real: they set how `setup`, `doctor`, `help` and the
            # channel commands print. The interface draws from its own design
            # tokens and reads neither, which is worth one line rather than a
            # flag that is quietly ignored.
            print(f"note: --{printing_flag} sets how the commands print; the "
                  "interface has its own colours and does not read it.",
                  file=sys.stderr)
            break
    command = [executable, "run", str(entry)]
    # The workspace is the user's project — never the artifact's directory.
    return subprocess.call(command, cwd=str(config.paths.project),
                           env=environment)


def run(config: Config, args: argparse.Namespace) -> int:
    if not getattr(args, "stdio", False):
        print("comodor core: choose a transport.\n\n"
              f"  comodor core --stdio    {PROTOCOL_LABEL} on stdin and stdout\n\n"
              "A client spawns this and drives the agent over the pipe; "
              "there is nothing to read here by hand.", file=sys.stderr)
        return 2

    from . import serve_stdio

    return serve_stdio(config)
