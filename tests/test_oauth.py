"""Signing in to a provider instead of finding a key.

The exchange runs against a stand-in rather than the real OpenRouter: a real
sign-in mints a real key on a real account, which is not a thing a test does.
The stand-in checks the PKCE proof properly — it recomputes the challenge from
the verifier it is sent — so what is being verified is that this end holds up
its half of it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from comodor.providers import oauth


@pytest.fixture
def openrouter(monkeypatch):
    """Something that behaves like OpenRouter and checks the proof."""
    state = {"code": "code-from-the-page", "challenge": "", "seen": {},
             "verified": False, "answer": None}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _send(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            state["seen"] = {k: v[0] for k, v in query.items()}
            state["challenge"] = state["seen"].get("code_challenge", "")
            self._send(200, {"ok": True})

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            sent = json.loads(self.rfile.read(length) or b"{}")
            if state["answer"] is not None:
                self._send(*state["answer"])
                return
            digest = hashlib.sha256(sent.get("code_verifier", "").encode()).digest()
            recomputed = base64.urlsafe_b64encode(digest).decode().rstrip("=")
            good = (sent.get("code") == state["code"]
                    and recomputed == state["challenge"]
                    and sent.get("code_challenge_method") == "S256")
            state["verified"] = good
            self._send(200 if good else 400,
                       {"key": "sk-or-v1-issued"} if good
                       else {"error": "PKCE check failed"})

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    where = f"http://127.0.0.1:{httpd.server_address[1]}"
    monkeypatch.setattr(oauth, "AUTHORIZE", f"{where}/auth")
    monkeypatch.setattr(oauth, "EXCHANGE", f"{where}/api/v1/auth/keys")
    state["url"] = where
    yield state
    httpd.shutdown()
    httpd.server_close()


# --------------------------------------------------------------------------- #
# the proof
# --------------------------------------------------------------------------- #


def test_the_verifier_never_goes_out_with_the_first_request():
    """That is the whole of why no client secret is needed: what proves the
    exchange is a number that was never sent until the exchange itself."""
    flow = oauth.begin()

    assert flow.verifier not in flow.url
    assert flow.challenge in flow.url
    assert "code_challenge_method=S256" in flow.url


def test_the_challenge_is_the_hash_of_the_verifier():
    flow = oauth.begin()

    digest = hashlib.sha256(flow.verifier.encode("ascii")).digest()
    assert base64.urlsafe_b64encode(digest).decode().rstrip("=") == flow.challenge


def test_every_flow_gets_its_own_secret():
    assert oauth.begin().verifier != oauth.begin().verifier


def test_a_flow_with_no_callback_asks_for_the_code_to_be_shown():
    """The shape that works over SSH and in a container, where no redirect can
    arrive."""
    flow = oauth.begin()

    assert flow.headless is True
    assert "key_label=Comodor" in flow.url
    assert "callback_url" not in flow.url


def test_a_flow_with_a_callback_says_where_to_come_back_to():
    flow = oauth.begin(callback="http://localhost:51423/callback")

    assert flow.headless is False
    assert "callback_url=http" in flow.url
    assert "key_label" not in flow.url


# --------------------------------------------------------------------------- #
# the exchange
# --------------------------------------------------------------------------- #


def test_a_good_code_comes_back_as_a_key(openrouter):
    flow = oauth.begin()
    knock(flow.url)                                 # what the browser does

    key = oauth.redeem(flow, openrouter["code"])

    assert key == "sk-or-v1-issued"
    assert openrouter["verified"] is True, "the provider checked the proof"


def test_a_code_that_does_not_match_the_proof_is_refused(openrouter):
    flow = oauth.begin()
    knock(flow.url)
    # A different flow's verifier: what an attacker who caught the redirect
    # would have.
    flow.verifier = oauth.begin().verifier

    with pytest.raises(oauth.OAuthError):
        oauth.redeem(flow, openrouter["code"])
    assert openrouter["verified"] is False


def test_nothing_to_exchange_is_an_error_not_a_request(openrouter):
    with pytest.raises(oauth.OAuthError, match="no code"):
        oauth.redeem(oauth.begin(), "")


def test_a_flow_that_sat_too_long_is_not_tried(openrouter, monkeypatch):
    """OpenRouter expires a code after ten minutes. Sending one anyway is a
    request that can only fail, with a worse message."""
    flow = oauth.begin()
    flow.started_at -= oauth.GOOD_FOR + 1

    with pytest.raises(oauth.OAuthError, match="ten minutes"):
        oauth.redeem(flow, "anything")


def test_the_providers_own_words_are_used_when_it_gives_any(openrouter):
    openrouter["answer"] = (400, {"error": "code already used"})
    flow = oauth.begin()

    with pytest.raises(oauth.OAuthError, match="code already used"):
        oauth.redeem(flow, "x")


def test_an_answer_with_no_key_in_it_is_not_a_success(openrouter):
    openrouter["answer"] = (200, {"nothing": "here"})
    flow = oauth.begin()

    with pytest.raises(oauth.OAuthError, match="did not return a key"):
        oauth.redeem(flow, "x")


def test_a_provider_that_cannot_be_reached_says_so(monkeypatch):
    monkeypatch.setattr(oauth, "EXCHANGE", "http://127.0.0.1:1/nope")

    with pytest.raises(oauth.OAuthError, match="could not reach"):
        oauth.redeem(oauth.begin(), "x")


# --------------------------------------------------------------------------- #
# catching the redirect
# --------------------------------------------------------------------------- #


def knock(url: str) -> None:
    """One request on its own connection, the way a browser makes it.

    Not the pooled module-level client: these tests reuse the same loopback
    port, so a pooled socket left over from the previous server would carry
    the request to something that is no longer listening.
    """
    from comodor.net import http

    session = http.Session()
    try:
        session.get(url, timeout=(3.0, 5.0))
    finally:
        session.close()


def test_the_callback_server_catches_the_code():
    flow = oauth.begin_with_a_browser()
    if flow is None:
        pytest.skip("no loopback port was free")
    try:
        knock(flow.callback + "?code=abc123")
        assert flow.wait(timeout=3.0) is True
        assert flow.code == "abc123"
        assert flow.error == ""
    finally:
        flow.close()


def test_a_refusal_comes_back_as_a_refusal():
    flow = oauth.begin_with_a_browser()
    if flow is None:
        pytest.skip("no loopback port was free")
    try:
        knock(flow.callback + "?error=access_denied")
        assert flow.wait(timeout=3.0) is True
        assert flow.code == ""
        assert flow.error == "access_denied"
    finally:
        flow.close()


def test_the_landing_page_asks_the_internet_for_nothing():
    """It is served by a socket that is about to close, so it could not fetch
    anything even if it wanted to."""
    for ok in (True, False):
        page = oauth._landing(ok)
        assert "http://" not in page and "https://" not in page
        assert "<script" not in page


def test_the_port_is_given_back():
    first = oauth.begin_with_a_browser()
    if first is None:
        pytest.skip("no loopback port was free")
    port = first.callback
    first.close()

    second = oauth.begin_with_a_browser()
    try:
        assert second is not None
        assert second.callback == port, "the port was not released"
    finally:
        if second is not None:
            second.close()


def test_only_the_providers_that_have_one_are_offered():
    assert oauth.supports("openrouter") is True
    assert oauth.supports("anthropic") is False
    assert oauth.supports("") is False
