"""Getting protocol messages from one process to another.

Split from `comodor.protocol` on purpose. The protocol is what the messages
*are*; this is how they travel. Today there is one way — newline-delimited
JSON over a pipe, which is what a terminal client spawning a private core
needs and the least machinery that works. A named pipe on Windows, a Unix
socket elsewhere, or a WebSocket for a remote client are further modules here,
and none of them require the protocol to change.

That is the reason for the split rather than a tidiness argument: a protocol
defined in terms of its pipe acquires stdio assumptions — ordering guarantees,
one client, a process lifetime — and then a socket cannot be added without a
second protocol.
"""

from __future__ import annotations

from ..protocol import PROTOCOL_LABEL
from .jsonl import Channel, own_stdout
from .server import Server

__all__ = ["Channel", "own_stdout", "Server", "serve_stdio"]


def serve_stdio(config, *, name: str = "comodor-core") -> int:
    """Run a core on this process's stdin and stdout.

    Everything that is not a protocol message is moved to stderr before the
    first line is read, and stdout is put back on the way out so an embedded
    core does not leave the interpreter rewired.
    """
    import sys

    from ..application import CoreService

    channel_out, restore = own_stdout()
    channel = Channel(reader=sys.stdin, writer=channel_out, log=sys.stderr)
    service = CoreService(config)
    server = Server(service, channel, name=name)
    # Derived, like every other place a person is told which protocol this is:
    # a greeting that names a version the core stopped speaking is the first
    # thing somebody reads when a client and a core disagree.
    channel.warn(f"comodor core — {PROTOCOL_LABEL} on stdio, pid {_pid()}")
    try:
        server.serve()
    except KeyboardInterrupt:
        pass
    finally:
        service.close()
        restore()
    return 0


def _pid() -> int:
    import os

    return os.getpid()
