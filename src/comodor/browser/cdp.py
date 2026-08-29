"""Driving a real Chrome, with nothing but the standard library.

The Chrome DevTools Protocol is JSON-RPC over a WebSocket. Everything that
speaks it — Playwright, Puppeteer, Selenium's newer bits — is a large
dependency wrapped around that one fact, and this project has one dependency
and intends to keep it. So the WebSocket is here: a handshake and a frame
format, about a hundred lines, and no node runtime to install on a user's
machine before they can look at a web page.

What this is *not* is a browser automation framework. There is no page object
model, no selector engine, no auto-waiting DSL. There is a connection, a way to
call a method, and a way to wait for an event, because that is the whole of
what a browsing agent needs and every line past it is a line to maintain.

Two things about the protocol that are easy to get wrong:

* **Replies and events share the socket.** A reply carries the id you sent; an
  event carries a method and no id. Reading the next frame and calling it your
  answer works until the page fires something, which is immediately.
* **Chrome's discovery endpoint moved.** `/json/new` answers 405 to a GET on
  current versions and wants a PUT. A client written against a tutorial from
  two years ago fails at the first call with a status nobody expects.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from ..net.ws import WebSocket as _WebSocket
from ..net.ws import WebSocketError

DEFAULT_TIMEOUT = 30.0
#: Long enough for a slow page on a slow machine, short enough that a hung
#: renderer does not hold the turn until the agent's own deadline.
NAVIGATE_TIMEOUT = 45.0


class BrowserError(RuntimeError):
    """Anything that went wrong with the browser or the protocol."""


# --------------------------------------------------------------------------- #
# the socket
# --------------------------------------------------------------------------- #


class WebSocket(_WebSocket):
    """The general client, with the browser's vocabulary on its failures.

    The frame handling moved to `net.ws` when Slack's Socket Mode became a
    second caller for it. This keeps the errors saying "the browser", because
    everything above catches `BrowserError` and a person reading a traceback
    about a websocket is a person who has to work out which websocket.
    """

    def __init__(self, url: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        try:
            super().__init__(url, timeout=timeout)
        except WebSocketError as error:
            raise BrowserError(
                f"could not connect to the browser: {error}") from error

    def send(self, text: str) -> None:
        try:
            super().send(text)
        except WebSocketError as error:
            raise BrowserError(f"the browser went away: {error}") from error

    def receive(self) -> str:
        try:
            return super().receive()
        except WebSocketError as error:
            raise BrowserError(
                f"the browser closed the connection: {error}") from error


# --------------------------------------------------------------------------- #
# the protocol
# --------------------------------------------------------------------------- #


class Session:
    """One tab, and the calls made against it."""

    def __init__(self, socket_url: str, target_id: str = "",
                 port: int = 0) -> None:
        self.target_id = target_id
        self.port = port
        self._ws = WebSocket(socket_url)
        self._id = 0
        self._lock = threading.Lock()
        #: Events that arrived while we were waiting for a reply. Kept, because
        #: the one we want is usually the one that arrived a millisecond early.
        self._events: list[dict[str, Any]] = []

    def call(self, method: str, timeout: float = DEFAULT_TIMEOUT,
             **params: Any) -> dict[str, Any]:
        """Send one command and return its result."""
        with self._lock:
            self._id += 1
            identifier = self._id
            self._ws.send(json.dumps({"id": identifier, "method": method,
                                      "params": params}))
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BrowserError(f"{method} took longer than {timeout:.0f}s")
                self._ws.settimeout(remaining)
                message = json.loads(self._ws.receive())
                if message.get("id") != identifier:
                    # A reply and an event look nothing alike, and treating the
                    # next frame as the answer breaks the moment a page loads.
                    self._remember(message)
                    continue
                error = message.get("error")
                if error:
                    raise BrowserError(
                        f"{method}: {error.get('message') or error}")
                return message.get("result") or {}

    def wait_for(self, method: str, timeout: float = NAVIGATE_TIMEOUT,
                 match: Callable[[dict[str, Any]], bool] | None = None) -> dict[str, Any]:
        """Wait for one event, including one that already arrived."""
        with self._lock:
            for index, event in enumerate(self._events):
                if event.get("method") == method and (match is None or match(event)):
                    return self._events.pop(index).get("params") or {}

            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BrowserError(f"{method} did not arrive within "
                                       f"{timeout:.0f}s")
                self._ws.settimeout(remaining)
                message = json.loads(self._ws.receive())
                if message.get("method") == method and (match is None or match(message)):
                    return message.get("params") or {}
                self._remember(message)

    def drain(self) -> None:
        """Forget buffered events. Called before an action whose result is an
        event, so a stale one from the last action is not mistaken for it."""
        with self._lock:
            self._events.clear()

    def _remember(self, message: dict[str, Any]) -> None:
        if "method" not in message:
            return
        self._events.append(message)
        if len(self._events) > 400:
            del self._events[:200]

    def close(self) -> None:
        self._ws.close()


# --------------------------------------------------------------------------- #
# finding and starting a browser
# --------------------------------------------------------------------------- #


def http_json(url: str, method: str = "GET", timeout: float = 10.0) -> Any:
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except (urllib.error.URLError, OSError) as error:
        raise BrowserError(f"the browser did not answer at {url}: {error}") from error
    try:
        return json.loads(body or b"null")
    except ValueError:
        return None


def open_tab(port: int) -> Session:
    """A new blank tab, and a session on it.

    `/json/new` wants a PUT on current Chrome; it answered a GET for years and
    now returns 405, which is the first thing a client written from an old
    example gets wrong.
    """
    target = http_json(f"http://127.0.0.1:{port}/json/new?about:blank",
                       method="PUT")
    if not isinstance(target, dict) or not target.get("webSocketDebuggerUrl"):
        raise BrowserError("the browser would not open a tab")
    return Session(target["webSocketDebuggerUrl"], target.get("id", ""), port)


def close_tab(port: int, target_id: str) -> None:
    if not target_id:
        return
    try:
        http_json(f"http://127.0.0.1:{port}/json/close/{target_id}")
    except BrowserError:
        pass


def version(port: int) -> dict[str, Any]:
    found = http_json(f"http://127.0.0.1:{port}/json/version")
    return found if isinstance(found, dict) else {}
