"""`comodor mcp` — adding, enabling and checking servers.

Adding a server is the part most tools get wrong. The information needed is a
command, some arguments, sometimes a token and sometimes a path, and asking for
all four every time is tedious for the eleven servers we already know about.
So there are two doors: pick one from the catalogue and answer only what it
actually needs, or paste the command for anything else in the world.

Neither door leads anywhere until the server has been started once and asked
what it offers. An entry in a config file that has never worked is not a
feature, and finding out at the start of a real task is the worst time.
"""

from __future__ import annotations

import argparse
import shutil
import sys

from ..config import Config, MCPServerConfig
from . import catalogue
from .manager import _connection_for
from .protocol import MCPError, StdioConnection


def register(subparsers: argparse._SubParsersAction) -> None:
    """Wire `comodor mcp ...` into the argument parser."""
    parser = subparsers.add_parser(
        "mcp", help="connect Comodor to Model Context Protocol servers")
    actions = parser.add_subparsers(dest="mcp_action")

    actions.add_parser("list", help="servers you have, and what they offer")
    actions.add_parser("catalogue", help="servers Comodor can set up for you")

    add = actions.add_parser("add", help="add a server from the catalogue")
    add.add_argument("server", nargs="?", help="catalogue id, or omit to choose")
    add.add_argument("--path", default="", help="the path or URL it needs")
    add.add_argument("--env", action="append", default=[], metavar="KEY=VALUE",
                     help="an environment variable it needs; repeatable")
    add.add_argument("--name", default="", help="call it something else")

    custom = actions.add_parser(
        "custom", help="add any other MCP server by its command")
    custom.add_argument("name", help="what to call it")
    custom.add_argument("command", help="the executable, for example npx or uvx")
    custom.add_argument("args", nargs=argparse.REMAINDER,
                        help="everything after the command is passed to it")
    custom.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
    custom.add_argument("--cwd", default="")

    remote = actions.add_parser(
        "remote", help="add a hosted MCP server by its URL")
    remote.add_argument("name", help="what to call it")
    remote.add_argument("url", help="its endpoint, for example https://host/mcp")
    remote.add_argument("--token", default="",
                        help="a bearer token, if it wants one")
    remote.add_argument("--header", action="append", default=[],
                        metavar="KEY=VALUE", help="any other header it wants")

    for name, help_text in (("enable", "turn a server on"),
                            ("disable", "turn a server off"),
                            ("remove", "forget a server entirely"),
                            ("test", "start it and list its tools")):
        action = actions.add_parser(name, help=help_text)
        action.add_argument("server")


def run(config: Config, args: argparse.Namespace) -> int:
    action = getattr(args, "mcp_action", None) or "list"
    handlers = {
        "list": _list, "catalogue": _catalogue, "add": _add, "custom": _custom,
        "remote": _remote,
        "enable": _enable, "disable": _disable, "remove": _remove, "test": _test,
    }
    handler = handlers.get(action)
    if handler is None:
        print(f"unknown action {action!r}", file=sys.stderr)
        return 2
    return handler(config, args)


# --------------------------------------------------------------------------- #
# showing
# --------------------------------------------------------------------------- #


def _list(config: Config, args: argparse.Namespace) -> int:
    servers = config.mcp.servers
    if not servers:
        print("No MCP servers yet.\n")
        print("  comodor mcp catalogue      what Comodor can set up for you")
        print("  comodor mcp add github     add one of them")
        print("  comodor mcp custom …       add any other server")
        return 0

    if not config.mcp.enabled:
        print("MCP is switched off entirely (mcp.enabled is false).\n")

    width = max(len(name) for name in servers)
    for name, server in sorted(servers.items()):
        state = "on " if server.enabled else "off"
        command = " ".join([server.command, *server.args])
        print(f"  {state}  {name:<{width}}  {command}")

    print(f"\n{sum(1 for s in servers.values() if s.enabled)} of {len(servers)} enabled.")
    print("`comodor mcp test <name>` starts one and lists what it offers.")
    return 0


def _catalogue(config: Config, args: argparse.Namespace) -> int:
    print("Servers Comodor can set up for you:\n")
    for spec in catalogue.offered():
        have = "added" if spec.id in config.mcp.servers else ""
        print(f"  {spec.id:<20} {spec.label}  {have}")
        print(f"  {'':<20} {spec.blurb}")
        if spec.reach:
            print(f"  {'':<20} reach: {spec.reach}")
        needs = catalogue.needing_setup(spec)
        if needs:
            print(f"  {'':<20} needs: {'; '.join(needs)}")
        print()

    print("  comodor mcp add <id>       set one up")
    print("  comodor mcp custom <name> <command> [args…]   anything else")
    return 0


# --------------------------------------------------------------------------- #
# adding
# --------------------------------------------------------------------------- #


def _add(config: Config, args: argparse.Namespace) -> int:
    server_id = (args.server or "").strip()
    if not server_id:
        return _catalogue(config, args)

    spec = catalogue.get(server_id)
    if spec is None:
        print(f"{server_id!r} is not in the catalogue. "
              f"`comodor mcp catalogue` lists it, and `comodor mcp custom` "
              f"adds anything else.", file=sys.stderr)
        return 1

    if shutil.which(spec.command) is None:
        # Said before anything is written, because the fix is to install
        # something and the entry would otherwise sit there not working.
        print(f"{spec.command!r} is not installed, and {spec.label} needs it "
              f"({spec.requires}).", file=sys.stderr)
        print(f"Install it, then run this again.", file=sys.stderr)
        return 1

    environment = _parse_env(args.env)
    missing = [name for name, _ in spec.needs_env if name not in environment]
    if missing:
        print(f"{spec.label} needs: " + ", ".join(missing), file=sys.stderr)
        for name, why in spec.needs_env:
            if name in missing:
                print(f"  {name} — {why}", file=sys.stderr)
        print(f"\n  comodor mcp add {spec.id} --env {missing[0]}=…", file=sys.stderr)
        return 1

    arguments = list(spec.args)
    if spec.needs_path:
        if not args.path:
            print(f"{spec.label} needs a path: {spec.needs_path}", file=sys.stderr)
            print(f"\n  comodor mcp add {spec.id} --path <path>", file=sys.stderr)
            return 1
        arguments.append(args.path)

    name = (args.name or spec.id).strip()
    config.mcp.servers[name] = MCPServerConfig(
        name=name, command=spec.command, args=arguments, env=environment,
        enabled=False, spec=spec.id)

    print(f"Added {name}. Checking that it starts…\n")
    if not _probe(config.mcp.servers[name]):
        print(f"\nLeft disabled. Fix the above, then: comodor mcp enable {name}")
        config.save()
        return 1

    config.mcp.servers[name].enabled = True
    config.save()
    print(f"\nEnabled. {spec.reach}" if spec.reach else "\nEnabled.")
    return 0


def _remote(config: Config, args: argparse.Namespace) -> int:
    """Add a server reached over HTTP rather than launched.

    Probed before it is enabled, for the same reason a command is: an entry
    that cannot connect is worse than no entry, because it fails once per
    session in a place nobody is looking.
    """
    name = args.name.strip()
    url = args.url.strip()
    if not url.lower().startswith(("http://", "https://")):
        print(f"{url!r} is not an http or https URL.", file=sys.stderr)
        return 1
    if url.lower().startswith("http://") and "localhost" not in url \
            and "127.0.0.1" not in url:
        print("Refusing a plain http:// endpoint that is not local — the token "
              "and everything the tools return would cross the network in the "
              "clear.", file=sys.stderr)
        return 1

    config.mcp.servers[name] = MCPServerConfig(
        name=name, url=url, token=args.token,
        headers=_parse_env(args.header), enabled=False)

    print(f"Added {name}. Checking that it answers…\n")
    if not _probe(config.mcp.servers[name]):
        print(f"\nLeft disabled. Fix the above, then: comodor mcp enable {name}")
        config.save()
        return 1

    config.mcp.servers[name].enabled = True
    config.save()
    print("\nEnabled.")
    return 0


def _custom(config: Config, args: argparse.Namespace) -> int:
    name = args.name.strip()
    arguments = [item for item in (args.args or []) if item != "--"]

    if shutil.which(args.command) is None:
        print(f"{args.command!r} is not on PATH.", file=sys.stderr)
        return 1

    config.mcp.servers[name] = MCPServerConfig(
        name=name, command=args.command, args=arguments,
        env=_parse_env(args.env), cwd=args.cwd, enabled=False)

    print(f"Added {name}. Checking that it starts…\n")
    if not _probe(config.mcp.servers[name]):
        print(f"\nLeft disabled. Fix the above, then: comodor mcp enable {name}")
        config.save()
        return 1

    config.mcp.servers[name].enabled = True
    config.save()
    print("\nEnabled.")
    return 0


# --------------------------------------------------------------------------- #
# switching
# --------------------------------------------------------------------------- #


def _enable(config: Config, args: argparse.Namespace) -> int:
    server = config.mcp.servers.get(args.server)
    if server is None:
        return _unknown(config, args.server)
    print(f"Checking that {args.server} starts…\n")
    if not _probe(server):
        return 1
    server.enabled = True
    config.save()
    print(f"\n{args.server} is enabled.")
    return 0


def _disable(config: Config, args: argparse.Namespace) -> int:
    server = config.mcp.servers.get(args.server)
    if server is None:
        return _unknown(config, args.server)
    server.enabled = False
    config.save()
    print(f"{args.server} is disabled. Its settings are kept.")
    return 0


def _remove(config: Config, args: argparse.Namespace) -> int:
    if args.server not in config.mcp.servers:
        return _unknown(config, args.server)
    del config.mcp.servers[args.server]
    config.save()
    print(f"Removed {args.server}.")
    return 0


def _test(config: Config, args: argparse.Namespace) -> int:
    server = config.mcp.servers.get(args.server)
    if server is None:
        return _unknown(config, args.server)
    return 0 if _probe(server, verbose=True) else 1


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _probe(server: MCPServerConfig, verbose: bool = True) -> bool:
    """Start it, list its tools, stop it. Prints what happened."""
    # Whichever transport the entry describes; a URL server has no command to
    # launch and probing it as one would report the wrong failure.
    connection = _connection_for(server)
    try:
        connection.start(timeout=90.0)
        result = connection.request("tools/list", {}, timeout=30.0)
        tools = result.get("tools") or []

        info = connection.server_info or {}
        label = info.get("name") or server.command or server.url
        print(f"  {label} {info.get('version', '')}".rstrip())
        print(f"  {len(tools)} tool(s)")
        if verbose:
            for tool in tools[:25]:
                summary = " ".join(str(tool.get("description", "")).split())[:70]
                print(f"    {tool.get('name', '?'):<28} {summary}")
            if len(tools) > 25:
                print(f"    … and {len(tools) - 25} more")
        return True
    except MCPError as error:
        print(f"  it did not start: {error}", file=sys.stderr)
        return False
    except Exception as error:
        print(f"  it did not start: {type(error).__name__}: {error}", file=sys.stderr)
        return False
    finally:
        connection.close()


def _parse_env(pairs: list[str]) -> dict[str, str]:
    environment: dict[str, str] = {}
    for pair in pairs or []:
        key, _, value = str(pair).partition("=")
        if key.strip():
            environment[key.strip()] = value
    return environment


def _unknown(config: Config, name: str) -> int:
    known = ", ".join(sorted(config.mcp.servers)) or "none"
    print(f"no server called {name!r}. You have: {known}", file=sys.stderr)
    return 1
