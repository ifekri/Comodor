#!/usr/bin/env python3
"""A minimal but real MCP server, used to test the client against a process.

Speaks the actual protocol over stdin and stdout — a real subprocess, real
JSON-RPC, real pipe buffering. Mocking the transport would test the mock.

Behaviours it can be told to exhibit, so the client's failure paths are
exercised rather than assumed:

    --noise         write a log banner to stdout before the handshake
    --slow N        wait N seconds before answering initialize
    --die-on-call   exit as soon as a tool is called
    --no-tools      offer nothing
    --paginate      return its tools across two pages
"""

import json
import sys
import time

ARGS = sys.argv[1:]


def flag(name):
    return name in ARGS


def value(name, default):
    if name in ARGS:
        index = ARGS.index(name)
        if index + 1 < len(ARGS):
            return ARGS[index + 1]
    return default


TOOLS = [
    {
        "name": "echo",
        "description": "Return whatever text is given.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "write_note",
        "description": "Create a note. This modifies stored data.",
        "inputSchema": {"type": "object", "properties": {"body": {"type": "string"}}},
    },
    {
        "name": "broken_schema",
        "description": "A tool whose schema a server got wrong.",
        "inputSchema": {"properties": "not a dict", "required": "also wrong"},
    },
]


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def reply(identifier, result):
    send({"jsonrpc": "2.0", "id": identifier, "result": result})


def main():
    if flag("--noise"):
        # Servers really do this: a startup banner on the wrong stream.
        sys.stdout.write("starting up, listening on stdio\n")
        sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue

        method = message.get("method")
        identifier = message.get("id")

        if method == "initialize":
            if flag("--slow"):
                time.sleep(float(value("--slow", "0")))
            reply(identifier, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-server", "version": "1.0.0"},
            })

        elif method == "notifications/initialized":
            continue                       # a notification has no reply

        elif method == "tools/list":
            if flag("--no-tools"):
                reply(identifier, {"tools": []})
            elif flag("--paginate"):
                cursor = (message.get("params") or {}).get("cursor")
                if not cursor:
                    reply(identifier, {"tools": TOOLS[:1], "nextCursor": "page2"})
                else:
                    reply(identifier, {"tools": TOOLS[1:]})
            else:
                reply(identifier, {"tools": TOOLS})

        elif method == "tools/call":
            if flag("--die-on-call"):
                sys.stderr.write("the server crashed on purpose\n")
                sys.stderr.flush()
                raise SystemExit(3)

            params = message.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments") or {}

            if name == "echo":
                reply(identifier, {
                    "content": [{"type": "text", "text": arguments.get("text", "")}]
                })
            elif name == "write_note":
                reply(identifier, {
                    "content": [{"type": "text", "text": "note created"}]
                })
            elif name == "explodes":
                reply(identifier, {
                    "content": [{"type": "text", "text": "it went wrong"}],
                    "isError": True,
                })
            else:
                send({"jsonrpc": "2.0", "id": identifier,
                      "error": {"code": -32602, "message": f"no tool {name!r}"}})

        elif identifier is not None:
            send({"jsonrpc": "2.0", "id": identifier,
                  "error": {"code": -32601, "message": f"no method {method!r}"}})


if __name__ == "__main__":
    main()
