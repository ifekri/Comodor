"""The agent, served to a browser.

Comodor runs shell commands and edits files, so a web interface to it is
literally a remote code execution endpoint — the feature *is* running arbitrary
commands on this machine. What separates that from a catastrophe is entirely
who can reach it, so most of what is checked here is who cannot.

Everything runs against the real server on a real socket, using the standard
library's HTTP client. A mock would have been written to pass.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from comodor.web.server import COOKIE, GUARD, Server


@pytest.fixture
def served(config):
    """A running server on a free port, torn down after the test."""
    server = Server(config, host="127.0.0.1", port=0)
    from http.server import ThreadingHTTPServer

    from comodor.web.server import _handler_for

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(server))
    server.port = httpd.server_address[1]
    server._httpd = httpd
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    yield server
    httpd.shutdown()
    httpd.server_close()
    server.session.close()


def call(server, path, *, method="GET", body=None, token=None, guard=True,
         headers=None):
    """One HTTP request, returning (status, parsed body or text)."""
    url = f"http://127.0.0.1:{server.port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token is not None:
        request.add_header("Cookie", f"{COOKIE}={token}")
    if guard and method == "POST":
        request.add_header(GUARD, "1")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode()
            try:
                return response.status, json.loads(raw)
            except ValueError:
                return response.status, raw
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, raw


# --------------------------------------------------------------------------- #
# who cannot reach it
# --------------------------------------------------------------------------- #


def test_nothing_is_served_without_the_token(served):
    """The whole security model in one assertion."""
    for path, method in (("/", "GET"), ("/api/state", "GET"),
                         ("/api/events", "GET")):
        status, _ = call(served, path, method=method)
        assert status == 401, f"{path} answered {status} to a stranger"


def test_no_action_is_taken_without_the_token(served):
    for path in ("/api/send", "/api/answer", "/api/interrupt", "/api/mode"):
        status, _ = call(served, path, method="POST", body={"text": "rm -rf /"})
        assert status == 401


def test_a_wrong_token_is_a_wrong_token(served):
    status, _ = call(served, "/api/state", token="not-the-token")
    assert status == 401


def test_the_token_is_compared_in_constant_time(served):
    """A prefix must not be worth more than a wrong first character."""
    import inspect

    from comodor.web import server as module

    source = inspect.getsource(module.Server.authorised)
    assert "compare_digest" in source


def test_a_post_from_another_site_is_refused_even_with_the_cookie(served):
    """SameSite should stop the browser sending the cookie at all. This is the
    second lock: a cross-origin form can post, but it cannot set a header."""
    status, body = call(served, "/api/send", method="POST",
                        body={"text": "hello"}, token=served.token, guard=False)

    assert status == 403
    assert "did not come from the page" in body["error"]


def test_no_cross_origin_permissions_are_handed_out(served):
    """A preflight that grants nothing means a cross-origin fetch cannot set
    the header the POST routes require."""
    status, _ = call(served, "/api/send", method="OPTIONS")

    assert status == 405


def test_the_page_says_nothing_useful_to_a_stranger(served):
    status, body = call(served, "/")

    assert status == 401
    assert "Comodor" not in str(body) or "token" in str(body)


# --------------------------------------------------------------------------- #
# how the token gets into the browser
# --------------------------------------------------------------------------- #


def test_the_token_arrives_in_the_url_and_moves_into_a_cookie(served):
    """So it stops appearing in the address bar, in history, and in the
    referrer of anything the page links to."""
    url = f"http://127.0.0.1:{served.port}/?token={served.token}"
    request = urllib.request.Request(url)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=10) as response:
            status, headers = response.status, response.headers
    except urllib.error.HTTPError as error:
        status, headers = error.code, error.headers

    assert status == 303
    cookie = headers.get("Set-Cookie") or ""
    assert served.token in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert headers.get("Location") == "/"


def test_the_page_is_served_once_the_cookie_is_held(served):
    status, body = call(served, "/", token=served.token)

    assert status == 200
    assert "<title>Comodor</title>" in body


def test_the_page_needs_nothing_from_the_internet(served):
    """No CDN, no font host, no analytics: it has to work on a machine that
    cannot reach anything but the agent itself."""
    _, body = call(served, "/", token=served.token)

    assert "http://" not in body.replace("http://127.0.0.1", "")
    assert "https://" not in body
    assert "<script src" not in body
    assert "<link" not in body


def test_the_default_bind_is_loopback(config):
    assert Server(config).local is True
    assert Server(config, host="0.0.0.0").local is False


def test_each_run_has_its_own_token(config):
    assert Server(config).token != Server(config).token


# --------------------------------------------------------------------------- #
# what it does once you are in
# --------------------------------------------------------------------------- #


def test_the_state_describes_the_session(served):
    status, state = call(served, "/api/state", token=served.token)

    assert status == 200
    assert state["mode"] in ("act", "plan", "chat")
    assert state["project"]
    assert "usage" in state


def test_a_message_starts_a_turn_and_the_events_come_back(served):
    from comodor.providers.fake import Script

    served.session.agent.gateway = served.session.gateway
    served.session.gateway.scripts = [Script(text="Hello from the agent.")]

    status, started = call(served, "/api/send", method="POST",
                           body={"text": "say hello"}, token=served.token)
    assert status == 200 and started["started"] is True

    seen, cursor = [], 0
    for _ in range(20):
        _, data = call(served, f"/api/events?cursor={cursor}", token=served.token)
        seen.extend(data["events"])
        cursor = data["cursor"]
        if any(event["kind"] == "turn_end" for event in seen):
            break

    kinds = [event["kind"] for event in seen]
    assert "turn_start" in kinds
    assert "turn_end" in kinds


def test_two_tabs_cannot_start_two_turns(served):
    """A terminal enforces one turn at a time by having one keyboard."""
    served.session._turn.acquire()
    try:
        status, body = call(served, "/api/send", method="POST",
                            body={"text": "anything"}, token=served.token)
        assert status == 409
        assert body["started"] is False
    finally:
        served.session._turn.release()


def test_an_empty_message_starts_nothing(served):
    status, body = call(served, "/api/send", method="POST",
                        body={"text": "   "}, token=served.token)

    assert body["started"] is False


def test_the_mode_can_be_changed_and_a_nonsense_one_cannot(served):
    status, _ = call(served, "/api/mode", method="POST",
                     body={"mode": "plan"}, token=served.token)
    assert status == 200
    assert served.session.config.agent.mode == "plan"

    status, _ = call(served, "/api/mode", method="POST",
                     body={"mode": "rm -rf"}, token=served.token)
    assert status == 400
    assert served.session.config.agent.mode == "plan"


# --------------------------------------------------------------------------- #
# a browser that reloads, or arrives late
# --------------------------------------------------------------------------- #


def test_a_browser_that_arrives_late_still_gets_the_transcript(served):
    from comodor.events import Kind

    for index in range(5):
        served.session.bus.emit(Kind.NOTICE, text=f"note {index}")

    _, data = call(served, "/api/events?cursor=0", token=served.token)

    assert [event["text"] for event in data["events"]] == \
        [f"note {index}" for index in range(5)]


def test_a_cursor_only_returns_what_came_after_it(served):
    from comodor.events import Kind

    served.session.bus.emit(Kind.NOTICE, text="first")
    _, first = call(served, "/api/events?cursor=0", token=served.token)
    served.session.bus.emit(Kind.NOTICE, text="second")

    _, second = call(served, f"/api/events?cursor={first['cursor']}",
                     token=served.token)

    assert [event["text"] for event in second["events"]] == ["second"]


def test_a_quiet_session_ends_the_request_rather_than_hanging_forever(served):
    """A stream held open forever is one a proxy eventually kills, and a client
    that cannot tell a dead connection from a quiet one reconnects too late."""
    import time

    started = time.monotonic()
    events = served.session.wait_for(cursor=10**9, timeout=0.4)

    assert events == []
    assert time.monotonic() - started < 5


def test_the_log_does_not_grow_without_end(served):
    from comodor.events import Kind
    from comodor.web.session import HISTORY

    for index in range(HISTORY + 200):
        served.session.bus.emit(Kind.NOTICE, text=str(index))

    assert len(served.session._log) <= HISTORY


# --------------------------------------------------------------------------- #
# permission prompts, which is where a browser could wedge the agent
# --------------------------------------------------------------------------- #


def test_a_permission_prompt_reaches_the_browser_and_can_be_answered(served):
    from comodor.events import Request

    request = Request(id="r1", prompt="Run this?", options=["yes", "no"],
                      detail="rm -rf /tmp/x")
    answers: list[str] = []
    threading.Thread(target=lambda: answers.append(request.wait(10.0)),
                     daemon=True).start()
    served.session.bus.ask(request)

    _, data = call(served, "/api/events?cursor=0", token=served.token)
    asked = [event for event in data["events"] if event["kind"] == "request"]
    assert asked and asked[0]["prompt"] == "Run this?"
    assert asked[0]["options"] == ["yes", "no"]

    status, body = call(served, "/api/answer", method="POST",
                        body={"id": "r1", "choice": "yes"}, token=served.token)
    assert status == 200 and body["answered"] is True

    for _ in range(50):
        if answers:
            break
        import time
        time.sleep(0.05)
    assert answers == ["yes"]


def test_answering_something_nobody_asked_is_not_an_error_that_matters(served):
    status, body = call(served, "/api/answer", method="POST",
                        body={"id": "nope", "choice": "yes"}, token=served.token)

    assert status == 410
    assert body["answered"] is False


def test_shutting_down_does_not_leave_a_worker_blocked_on_a_prompt(config):
    """A browser that closes mid-prompt would otherwise wedge the thread until
    the prompt's own timeout, holding a shell open."""
    from comodor.events import Request
    from comodor.web.session import Session

    session = Session(config)
    request = Request(id="r9", prompt="Allow?", options=["yes", "no"])
    session.bus.ask(request)

    session.close()

    assert request.answered
    assert request.wait(0.1) == "no"


def test_an_events_own_fields_cannot_overwrite_its_kind(served):
    """A Request carries a `kind` of its own — "permission" — and spreading it
    into the frame renamed the event, so the page never saw a prompt at all."""
    from comodor.events import Request

    served.session.bus.ask(Request(id="r2", prompt="Allow?", options=["yes"]))

    _, data = call(served, "/api/events?cursor=0", token=served.token)
    frames = [event for event in data["events"] if event.get("id") == "r2"]

    assert frames and frames[0]["kind"] == "request"
    assert frames[0]["about"] == "permission"
