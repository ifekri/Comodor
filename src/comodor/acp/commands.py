"""`comodor acp` — be an agent an editor can drive.

Not a command anybody types twice. An editor launches it as a subprocess and
talks JSON-RPC down the pipe, so the useful thing this file does is take
stdout away from the rest of the program before anything can write to it.

That is the one requirement that will break an integration silently: the
protocol says the agent **MUST NOT** write anything to stdout that is not an
ACP message, and Comodor is a program with a banner, warnings, progress and a
`doctor`. One `print` on the wrong stream is a parse error at the far end and
the end of the session, with nothing on screen to say why — the editor just
shows a disconnected agent.

So `sys.stdout` is replaced with `sys.stderr` for the whole process, and the
real stdout is handed to the connection and to nothing else. Anything that
prints keeps working and its output turns into a log line, which is what the
specification sets stderr aside for.
"""

from __future__ import annotations

import argparse
import io
import sys

from ..config import Config


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "acp", help="run as an agent your editor can drive (Agent Client Protocol)")
    parser.add_argument("--print-config", action="store_true",
                        help="print the JSON an editor needs to launch this, "
                             "then exit")


def run(config: Config, args: argparse.Namespace) -> int:
    if getattr(args, "print_config", False):
        _print_launch_config()
        return 0

    from .agent import ComodorAgent
    from .jsonrpc import Connection

    # The real stdout, before anything else can reach it.
    #
    # Reconfigured rather than wrapped: the framing is UTF-8 and line-based,
    # and a Windows console that defaults to cp1252 would mangle a Persian
    # prompt on its way back to the editor. `write_through` because a message
    # sitting in a buffer is a message the editor is still waiting for.
    channel = sys.stdout
    try:
        channel.reconfigure(encoding="utf-8", newline="\n", write_through=True)
    except (AttributeError, ValueError):
        channel = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                   newline="\n", write_through=True)
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    # Everything else that prints now goes to the log stream. This is the line
    # that keeps a stray `print` from ending the session.
    sys.stdout = sys.stderr

    rpc = Connection(reader=sys.stdin, writer=channel, log=sys.stderr)
    agent = ComodorAgent(config, rpc)
    rpc.warn(f"comodor acp — speaking ACP v{agent.__class__ and 2} on stdio")

    try:
        rpc.serve()
    except KeyboardInterrupt:
        pass
    finally:
        agent.close()
        sys.stdout = channel
    return 0


def _print_launch_config() -> None:
    """What to paste into an editor that asks for a command.

    Printed rather than written anywhere: which file it belongs in differs by
    editor, and guessing wrong means editing somebody's settings for them.
    """
    import json
    import shutil

    where = shutil.which("comodor") or "comodor"
    block = {
        "agent_servers": {
            "Comodor": {
                "command": where,
                "args": ["acp"],
                "env": {},
            }
        }
    }
    print(json.dumps(block, indent=2))
    print()
    print("Zed:  put this in your settings.json", file=sys.stderr)
    print("Others: give them the command and the `acp` argument.",
          file=sys.stderr)
