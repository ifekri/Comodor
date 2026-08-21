"""`comodor web` — the same agent, in a browser.

The one thing worth being loud about: this serves a program that runs shell
commands. On the loopback address that is exactly as dangerous as the terminal
it replaces, which is to say not at all. Bound anywhere else it is a shell,
open to whoever can route to the port, and the only thing between them and it
is a token travelling in the clear.

So the address is loopback unless the user names another one, and naming
another one prints what that means before it starts.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser

from ..config import Config
from .server import Server


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "web", help="use Comodor from a browser, on this machine or a server")
    parser.add_argument("--port", type=int, default=8765,
                        help="port to listen on (0 picks a free one)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="address to bind. Anything but a loopback address "
                             "puts a shell on the network — see --help")
    parser.add_argument("--token", default="",
                        help="use this token instead of a generated one")
    parser.add_argument("--no-browser", action="store_true",
                        help="do not open a browser window")


def run(config: Config, args: argparse.Namespace) -> int:
    server = Server(config, host=args.host, port=args.port, token=args.token)

    try:
        server.bind()
    except OSError as error:
        print(f"Could not listen on {args.host}:{args.port} — {error}",
              file=sys.stderr)
        server.session.close()
        return 1

    _announce(server)
    if not args.no_browser and server.local:
        try:
            webbrowser.open(server.url)
        except Exception:
            pass

    try:
        server.serve()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.stop()
    return 0


def _announce(server: Server) -> None:
    print()
    print(f"  Comodor is at  {server.url}")
    print(f"  Working in     {server.config.paths.project}")
    print(f"  Model          {server.config.active_model()}")
    print()

    if server.local:
        print("  Only this machine can reach it. Ctrl-C to stop.")
    else:
        print("  ⚠  This is bound to a public address.")
        print()
        print("     Comodor runs shell commands and edits files, so this port")
        print("     is a shell. Anyone who can reach it and guess the token has")
        print("     one. There is no TLS here: the token, your prompts and")
        print("     everything the agent reads cross the network in the clear.")
        print()
        print("     Put it behind an SSH tunnel instead, and keep the bind local:")
        print(f"       ssh -N -L {server.port}:127.0.0.1:{server.port} you@host")
        print()
        print("  Ctrl-C to stop.")
    print()
