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
    config = _configured_or_explain(config)
    if config is None:
        return 1

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


def _configured_or_explain(config: Config) -> Config | None:
    """A usable configuration, or None having said what is missing.

    The browser interface can switch between providers that are already set
    up, but it has nowhere to type a key into and would be a poor place for
    one anyway. Starting with none configured produces a URL, a browser
    window, and a failure on the first task with nothing on screen to act on.
    """
    if not config.needs_setup:
        return config

    # `isatty` is not enough on its own. Compose sets `tty: true`, so a
    # container has one whether or not anybody is reading it - and
    # `docker compose up -d` would sit forever on the first question, which is
    # a hung container instead of a message. In a container the answer is
    # always the message.
    from .server import in_a_container

    if sys.stdin.isatty() and not in_a_container():
        from ..setup import run_setup

        try:
            config = run_setup(config)
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled. Run `comodor setup` when you are ready.",
                  file=sys.stderr)
            return None
        return None if config.needs_setup else config

    # Nobody to ask: a container, a service unit, a pipeline. This message is
    # the only thing that person will see, so it has to carry the answer.
    print("Comodor has no provider configured, and the browser interface has "
          "no way to add one.", file=sys.stderr)
    print(file=sys.stderr)
    print("  In Docker, pass a key in as an environment variable:",
          file=sys.stderr)
    print("    -e ANTHROPIC_API_KEY=...    -e OPENAI_API_KEY=...",
          file=sys.stderr)
    print("  or mount a config file at "
          f"{config.paths.config_file}.", file=sys.stderr)
    print("  Anywhere with a terminal, `comodor setup` asks a few questions.",
          file=sys.stderr)
    return None


def banner_shown(server: Server) -> bool:
    """Whether the wordmark went out, and with it the model's name."""
    from ..ui import banner
    from ..ui import console as console_module

    theme = console_module.prepare_theme(server.config.ui.theme,
                                         server.config.ui.ascii_borders,
                                         no_color=False)
    return banner.wanted(console_module.build(theme), server.config)


def _wordmark(server: Server) -> None:
    """The logo above the address, including in a container's logs.

    `docker compose up` shows this, and a container that says what it is before
    it says where it is reads as something that started, rather than as
    something that emitted a URL.
    """
    from .. import __version__ as release
    from ..ui import banner
    from ..ui import console as console_module

    theme = console_module.prepare_theme(server.config.ui.theme,
                                         server.config.ui.ascii_borders,
                                         no_color=False)
    console = console_module.build(theme)
    if not banner.wanted(console, server.config):
        return
    console.print()
    console.print(banner.render(theme, version=release,
                                model=server.config.active_model(),
                                width=console.size.width))


def _announce(server: Server) -> None:
    _wordmark(server)
    print()
    print(f"  Comodor is at  {server.url}")
    print(f"  Working in     {server.config.paths.project}")
    # The model is on the wordmark above; saying it twice reads as a template
    # rather than as something written.
    if not banner_shown(server):
        print(f"  Model          {server.config.active_model()}")
    print()

    if server.local:
        print("  Only this machine can reach it. Ctrl-C to stop.")
    elif server.contained:
        # Correct, and the warning above would be both alarming and wrong. The
        # real boundary is one layer out, so that is what gets explained.
        print("  Listening on every address inside this container, which is")
        print("  the only way the machine running it can reach the port.")
        print()
        print("  What decides who else can is how the port was published:")
        print(f"    -p 127.0.0.1:{server.port}:{server.port}   only this machine")
        print(f"    -p {server.port}:{server.port}             anyone who can route to it")
        print()
        print("  The second form puts a shell on the network, and there is no")
        print("  TLS here — the token and everything the agent reads would")
        print("  cross in the clear. Use the first, and an SSH tunnel to reach")
        print("  a remote host.")
        print()
        print("  Ctrl-C to stop.")
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
