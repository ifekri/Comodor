"""Signing in to a provider instead of finding a key.

Getting an API key is the tedious part of setting an agent up: a billing page,
a new secret to keep somewhere, and a decision made before you have tried
anything. OpenRouter will hand one over on the user's say-so, and the whole
exchange is four HTTP requests.

It is PKCE, which is the flow designed for exactly this shape of program: one
that runs on somebody's own machine and therefore cannot keep a client secret.
Nothing is registered with anybody — there is no client id to obtain, no app to
create — because what proves the exchange is genuine is a random number this
process made up and kept, not a credential a vendor issued.

Two ways round, and both are needed:

**With a browser.** A one-shot server on a loopback port catches the redirect.
The code never leaves the machine.

**Without one.** Over SSH, in a container, on a server: no callback is given,
the page shows the code, and the person pastes it in. The same exchange, the
same proof, and it works where a redirect cannot arrive.

What comes back is a real key on the user's own account. It is saved the way a
typed one is, so nothing downstream needs to know which way it arrived.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

#: Where the user is sent, and where the code is exchanged.
AUTHORIZE = "https://openrouter.ai/auth"
EXCHANGE = "https://openrouter.ai/api/v1/auth/keys"

#: OpenRouter expires a code ten minutes after issuing it. A flow that outlives
#: that is a flow holding a verifier for a code that can no longer be used.
GOOD_FOR = 600

#: What the account page calls the key it creates. Somebody looking at a list
#: of keys later should be able to tell which program asked for this one.
KEY_LABEL = "Comodor"

#: Ports to try for the callback. Fixed rather than zero, because the redirect
#: is registered by URL and the URL has to be known before the browser opens —
#: and a handful of choices survives one of them being taken.
PORTS = (51423, 51424, 51425, 8767, 8768)


class OAuthError(RuntimeError):
    """The exchange did not produce a key."""


@dataclass
class Flow:
    """One sign-in, from the moment the browser opens until a key comes back."""

    provider: str
    verifier: str
    challenge: str
    url: str
    #: Where the redirect will land, when there is a browser to redirect.
    callback: str = ""
    started_at: float = field(default_factory=time.time)
    #: Filled in by the callback server, or pasted by the user.
    code: str = ""
    error: str = ""
    _done: threading.Event = field(default_factory=threading.Event, repr=False)
    _server: Any = field(default=None, repr=False)

    @property
    def expired(self) -> bool:
        return time.time() - self.started_at > GOOD_FOR

    @property
    def headless(self) -> bool:
        return not self.callback

    def finish(self, code: str = "", error: str = "") -> None:
        self.code, self.error = code, error
        self._done.set()

    def wait(self, timeout: float) -> bool:
        return self._done.wait(timeout)

    def close(self) -> None:
        server, self._server = self._server, None
        if server is None:
            return
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# the proof
# --------------------------------------------------------------------------- #


def _pkce() -> tuple[str, str]:
    """A secret this process invents, and the hash it publishes.

    The verifier never leaves the machine until the exchange; the challenge is
    the only part the provider sees first. That is what makes a client secret
    unnecessary — nobody who intercepts the redirect can complete the exchange
    without the number that was never sent.
    """
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def begin(callback: str = "", label: str = KEY_LABEL) -> Flow:
    """Start a sign-in. Pass a callback URL when a browser can reach one."""
    verifier, challenge = _pkce()
    query: dict[str, str] = {"code_challenge": challenge,
                             "code_challenge_method": "S256"}
    if callback:
        query["callback_url"] = callback
    else:
        # No redirect to catch it, so the page shows the code instead. The
        # label is what the key is called on the account afterwards.
        query["key_label"] = label

    return Flow(provider="openrouter", verifier=verifier, challenge=challenge,
                url=f"{AUTHORIZE}?{urlencode(query)}", callback=callback)


# --------------------------------------------------------------------------- #
# catching the redirect
# --------------------------------------------------------------------------- #


def begin_with_a_browser(label: str = KEY_LABEL) -> Flow | None:
    """Start a sign-in that a loopback server will complete.

    ``None`` when no port could be taken — the caller falls back to the form
    that needs no callback, which works everywhere.
    """
    from http.server import ThreadingHTTPServer

    for port in PORTS:
        flow = begin(callback=f"http://localhost:{port}/callback", label=label)
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), _handler_for(flow))
        except OSError:
            continue                       # that port is taken; try the next
        flow._server = server
        threading.Thread(target=server.serve_forever,
                         kwargs={"poll_interval": 0.2}, daemon=True).start()
        return flow

    return None


def _handler_for(flow: Flow) -> type:
    """A request handler bound to one flow, so nothing is shared between
    attempts at a port."""
    from http.server import BaseHTTPRequestHandler
    from urllib.parse import parse_qs, urlparse

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            query = parse_qs(urlparse(self.path).query)
            code = (query.get("code") or [""])[0]
            problem = (query.get("error") or [""])[0]
            body = _landing(bool(code) and not problem).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            flow.finish(code=code, error=problem)

    return Handler


def _landing(ok: bool) -> str:
    """What the browser shows when it comes back.

    Plain and self-contained. This page is served by a socket that is about to
    close, so it cannot fetch anything, and it exists for three seconds.
    """
    heading = "You are signed in" if ok else "That did not complete"
    body = ("Comodor has your key. You can close this tab and go back to the "
            "terminal." if ok else
            "No code came back. Close this tab and try again from Comodor.")
    tone = "#e2703a" if ok else "#b3322e"
    return (
        "<!doctype html><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>Comodor</title>"
        "<style>body{margin:0;min-height:100vh;display:grid;place-items:center;"
        "background:#171615;color:#efe9e2;font:16px/1.6 system-ui,sans-serif}"
        "div{max-width:26rem;padding:2rem;text-align:center}"
        f"h1{{margin:0 0 .5rem;font-size:1.25rem;color:{tone}}}"
        "p{margin:0;color:#b3a99f}</style>"
        f"<div><h1>{heading}</h1><p>{body}</p></div>"
    )


# --------------------------------------------------------------------------- #
# the exchange
# --------------------------------------------------------------------------- #


def redeem(flow: Flow, code: str = "") -> str:
    """Trade the code for a key. Raises :class:`OAuthError` with the reason."""
    from ..net import http

    code = (code or flow.code or "").strip()
    if not code:
        raise OAuthError("no code to exchange")
    if flow.expired:
        raise OAuthError("that took longer than ten minutes — start again")

    session = http.Session()
    try:
        response = session.post(EXCHANGE, json={
            "code": code,
            "code_verifier": flow.verifier,
            "code_challenge_method": "S256",
        }, timeout=(5.0, 20.0))
        if response.status_code >= 400:
            raise OAuthError(_why(response))
        payload = response.json()
    except OAuthError:
        raise
    except Exception as error:
        raise OAuthError(f"could not reach OpenRouter ({type(error).__name__})") from error
    finally:
        try:
            session.close()
        except Exception:
            pass

    key = str((payload or {}).get("key") or "").strip()
    if not key:
        raise OAuthError("OpenRouter did not return a key")
    return key


def _why(response: Any) -> str:
    """The provider's own words where it gave any, and never its whole body."""
    try:
        payload = response.json()
        said = payload.get("error") or payload.get("message")
        if isinstance(said, dict):
            said = said.get("message")
        if said:
            return str(said)[:200]
    except Exception:
        pass
    if response.status_code in (400, 403):
        return "that code was refused — it may have been used already"
    return f"OpenRouter answered {response.status_code}"


#: Providers that can be signed in to rather than pasted a key for.
SUPPORTED = ("openrouter",)


def supports(provider: str) -> bool:
    return provider in SUPPORTED
