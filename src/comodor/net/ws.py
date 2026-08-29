"""RFC 6455, client side, over TCP or TLS.

Lifted out of the browser package, where it was written for Chrome's debugging
protocol and grew a second caller: Slack's Socket Mode, which is a websocket
the app opens outward so that no public URL is needed. Two hand-rolled
implementations of the same frame format in one wheel would be one too many —
and the browser's could not have served, because it speaks plain TCP and Slack
is `wss://`.

Only what a client actually needs. No extensions, no compression, no
fragmented *sends* — every caller here sends JSON text, which fits one frame.
Incoming fragments are reassembled, because a large accessibility tree and a
busy Slack workspace both arrive in pieces.

The masking is not optional and is a common thing to get wrong: a client must
mask every frame it sends and a server must not mask what it sends back.
Chrome enforces the first and Slack enforces both.
"""

from __future__ import annotations

import base64
import os
import socket
import ssl
import struct
import threading
from urllib.parse import urlsplit

DEFAULT_TIMEOUT = 30.0


class WebSocketError(RuntimeError):
    """The connection failed, refused the upgrade, or went away."""


class WebSocket:
    """One connection. Thread-safe to send on, single-reader to receive."""

    def __init__(self, url: str, timeout: float = DEFAULT_TIMEOUT,
                 headers: dict[str, str] | None = None) -> None:
        parts = urlsplit(url)
        secure = parts.scheme in ("wss", "https")
        host = parts.hostname or ""
        port = parts.port or (443 if secure else 80)
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"

        try:
            raw = socket.create_connection((host, port), timeout=timeout)
        except OSError as error:
            raise WebSocketError(f"could not connect to {host}: {error}") \
                from error

        if secure:
            try:
                context = ssl.create_default_context()
                raw = context.wrap_socket(raw, server_hostname=host)
            except OSError as error:
                raw.close()
                raise WebSocketError(f"TLS to {host} failed: {error}") from error

        self._socket = raw
        self._socket.settimeout(timeout)
        self._buffer = b""
        self._send_lock = threading.Lock()

        key = base64.b64encode(os.urandom(16)).decode()
        request = [
            f"GET {path} HTTP/1.1",
            f"Host: {host}" + ("" if port in (80, 443) else f":{port}"),
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
        ]
        for name, value in (headers or {}).items():
            request.append(f"{name}: {value}")
        try:
            self._socket.sendall(("\r\n".join(request) + "\r\n\r\n").encode())
        except OSError as error:
            raise WebSocketError(f"could not send the handshake: {error}") \
                from error

        header = b""
        while b"\r\n\r\n" not in header:
            try:
                chunk = self._socket.recv(1)
            except OSError as error:
                raise WebSocketError(f"handshake failed: {error}") from error
            if not chunk:
                raise WebSocketError("closed during the handshake")
            header += chunk
            if len(header) > 8192:
                raise WebSocketError("the server sent a handshake we cannot read")

        first = header.split(b"\r\n")[0]
        if b" 101" not in first:
            raise WebSocketError(f"the upgrade was refused: {first[:120]!r}")

    # -- frames ------------------------------------------------------------ #

    def send(self, text: str) -> None:
        payload = text.encode()
        frame = bytearray([0x81])                 # FIN + text
        length = len(payload)
        if length < 126:
            frame.append(0x80 | length)
        elif length < 65536:
            frame.append(0x80 | 126)
            frame += struct.pack(">H", length)
        else:
            frame.append(0x80 | 127)
            frame += struct.pack(">Q", length)
        mask = os.urandom(4)
        frame += mask
        frame += bytes(byte ^ mask[index % 4]
                       for index, byte in enumerate(payload))
        with self._send_lock:
            try:
                self._socket.sendall(bytes(frame))
            except OSError as error:
                raise WebSocketError(f"the connection went away: {error}") \
                    from error

    def receive(self) -> str:
        """One complete message, reassembled if it arrived in fragments."""
        parts: list[bytes] = []
        while True:
            first, second = self._exactly(2)
            final = bool(first & 0x80)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._exactly(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._exactly(8))[0]
            mask = self._exactly(4) if second & 0x80 else b""
            payload = self._exactly(length)
            if mask:
                payload = bytes(byte ^ mask[index % 4]
                                for index, byte in enumerate(payload))

            if opcode == 0x8:                     # close
                raise WebSocketError("the server closed the connection")
            if opcode == 0x9:                     # ping -> pong
                self._pong(payload)
                continue
            if opcode == 0xA:                     # pong
                continue

            parts.append(payload)
            if final:
                return b"".join(parts).decode("utf-8", "replace")

    def _pong(self, payload: bytes) -> None:
        frame = bytearray([0x8A, 0x80 | len(payload)])
        mask = os.urandom(4)
        frame += mask
        frame += bytes(byte ^ mask[index % 4]
                       for index, byte in enumerate(payload))
        with self._send_lock:
            try:
                self._socket.sendall(bytes(frame))
            except OSError:
                pass

    def ping(self, payload: bytes = b"") -> None:
        """Say we are still here.

        Slack closes a socket it has not heard from, and its own pings are not
        enough on a quiet workspace — a bot nobody messaged for an hour is
        exactly the case that must survive.
        """
        frame = bytearray([0x89, 0x80 | len(payload)])
        mask = os.urandom(4)
        frame += mask
        frame += bytes(byte ^ mask[index % 4]
                       for index, byte in enumerate(payload))
        with self._send_lock:
            try:
                self._socket.sendall(bytes(frame))
            except OSError as error:
                raise WebSocketError(f"the connection went away: {error}") \
                    from error

    def _exactly(self, count: int) -> bytes:
        while len(self._buffer) < count:
            try:
                chunk = self._socket.recv(65536)
            except socket.timeout as error:
                raise WebSocketError("the server stopped answering") from error
            except OSError as error:
                raise WebSocketError(f"the connection went away: {error}") \
                    from error
            if not chunk:
                raise WebSocketError("the server closed the connection")
            self._buffer += chunk
        taken, self._buffer = self._buffer[:count], self._buffer[count:]
        return taken

    def settimeout(self, timeout: float) -> None:
        self._socket.settimeout(timeout)

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass
