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

    assert status == 409
    assert body["answered"] is False
    assert "nothing is waiting" in body["error"]


def test_a_choice_that_was_never_offered_is_refused(served):
    """It used to be accepted and reported as a success. The permission engine
    then did not recognise the word, treated the turn as refused, and the
    caller was told it had worked — found by driving the API by hand and
    watching nothing happen."""
    from comodor.events import Request

    request = Request(id="r3", prompt="Run this?",
                      options=["allow", "allow_always", "deny"])
    served.session.bus.ask(request)

    status, body = call(served, "/api/answer", method="POST",
                        body={"id": "r3", "choice": "yes"}, token=served.token)

    assert status == 409
    assert body["answered"] is False
    assert "not one of the choices" in body["error"]
    assert "allow" in body["error"]
    assert not request.answered, "the worker must still be waiting"


def test_a_choice_that_was_offered_is_taken(served):
    from comodor.events import Request

    request = Request(id="r4", prompt="Run this?", options=["allow", "deny"])
    served.session.bus.ask(request)

    status, body = call(served, "/api/answer", method="POST",
                        body={"id": "r4", "choice": "deny"}, token=served.token)

    assert status == 200 and body["answered"] is True
    assert request.wait(1.0) == "deny"


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


# --------------------------------------------------------------------------- #
# a refusal must still leave the connection usable
# --------------------------------------------------------------------------- #


def test_a_refused_post_leaves_the_connection_clean(served):
    """The bug this exists for. A verdict reached before the body is read
    leaves those bytes in the socket; the next request on the connection reads
    them as its own request line, and a socket closed with unread data sends a
    reset — which the caller sees as an aborted connection rather than the 401
    that was actually sent."""
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", served.port, timeout=15)
    try:
        payload = json.dumps({"text": "x" * 50_000})
        # Rejected for the missing guard header, with a body already in flight.
        connection.request("POST", "/api/send", body=payload,
                           headers={"Content-Type": "application/json",
                                    "Cookie": f"{COOKIE}={served.token}"})
        first = connection.getresponse()
        first.read()
        assert first.status == 403

        # The same connection, reused. If the body was not drained this reads
        # the leftover as a request line and fails.
        connection.request("GET", "/api/state",
                           headers={"Cookie": f"{COOKIE}={served.token}"})
        second = connection.getresponse()
        state = json.loads(second.read())

        assert second.status == 200
        assert "mode" in state
    finally:
        connection.close()


def test_an_unauthorised_post_leaves_the_connection_clean(served):
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", served.port, timeout=15)
    try:
        connection.request("POST", "/api/send",
                           body=json.dumps({"text": "y" * 20_000}),
                           headers={"Content-Type": "application/json",
                                    "X-Comodor": "1"})
        first = connection.getresponse()
        first.read()
        assert first.status == 401

        connection.request("GET", "/api/state",
                           headers={"Cookie": f"{COOKIE}={served.token}"})
        second = connection.getresponse()
        second.read()

        assert second.status == 200
    finally:
        connection.close()


def test_a_body_over_the_cap_is_drained_rather_than_left_in_the_socket(served):
    """Refusing to read is what breaks the connection, so an oversized body is
    read and dropped instead."""
    import http.client

    from comodor.web.server import MAX_BODY

    connection = http.client.HTTPConnection("127.0.0.1", served.port, timeout=30)
    try:
        connection.request("POST", "/api/send", body="z" * (MAX_BODY + 5_000),
                           headers={"Content-Type": "application/json",
                                    "Cookie": f"{COOKIE}={served.token}",
                                    "X-Comodor": "1"})
        first = connection.getresponse()
        first.read()

        connection.request("GET", "/api/state",
                           headers={"Cookie": f"{COOKIE}={served.token}"})
        second = connection.getresponse()
        second.read()

        assert second.status == 200
    finally:
        connection.close()


# --------------------------------------------------------------------------- #
# inside a container, a wide bind is the correct one
# --------------------------------------------------------------------------- #


def test_a_container_is_recognised(monkeypatch, tmp_path):
    from comodor.web import server as module

    marker = tmp_path / "dockerenv"
    marker.write_text("", encoding="utf-8")
    monkeypatch.setattr(module, "Path", lambda p: marker if p == "/.dockerenv"
                        else tmp_path / "absent")

    assert module.in_a_container() is True


def test_a_plain_machine_is_not_mistaken_for_one(monkeypatch, tmp_path):
    from comodor.web import server as module

    monkeypatch.setattr(module, "Path", lambda p: tmp_path / "absent")
    monkeypatch.delenv("container", raising=False)

    assert module.in_a_container() is False


def test_the_environment_variable_podman_sets_counts(monkeypatch, tmp_path):
    from comodor.web import server as module

    monkeypatch.setattr(module, "Path", lambda p: tmp_path / "absent")
    monkeypatch.setenv("container", "podman")

    assert module.in_a_container() is True


def test_a_container_binding_wide_is_not_called_reckless(config, monkeypatch, capsys):
    """A container has its own network namespace, so binding 127.0.0.1 there
    hides the port from the machine that started it. Binding everything is
    correct, and the boundary is how the port was published."""
    from comodor.web import commands
    from comodor.web import server as module

    monkeypatch.setattr(module, "in_a_container", lambda: True)
    served = module.Server(config, host="0.0.0.0", port=8765)
    try:
        commands._announce(served)
        printed = capsys.readouterr().out

        assert "public address" not in printed
        assert "-p 127.0.0.1:8765:8765" in printed
        # And it still says what the careless form costs.
        assert "shell on the network" in printed
    finally:
        served.session.close()


def test_a_real_machine_binding_wide_still_gets_the_warning(config, monkeypatch,
                                                            capsys):
    from comodor.web import commands
    from comodor.web import server as module

    monkeypatch.setattr(module, "in_a_container", lambda: False)
    served = module.Server(config, host="0.0.0.0", port=8765)
    try:
        commands._announce(served)
        printed = capsys.readouterr().out

        assert "public address" in printed
        assert "ssh -N -L" in printed
    finally:
        served.session.close()


# --------------------------------------------------------------------------- #
# starting it with nothing configured
# --------------------------------------------------------------------------- #


def test_it_refuses_to_serve_when_no_provider_is_configured(config, monkeypatch,
                                                            capsys):
    """The browser interface can change the mode and nothing else, so a server
    started without a key produces a URL, a browser window, and a failure on
    the first task with nothing on screen to act on. The Docker image sends
    people straight here, which is exactly the audience that has configured
    nothing yet."""
    import argparse

    from comodor.web import commands

    for entry in config.providers.values():
        entry.api_key = ""
        entry.configured = False
    assert config.needs_setup
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    code = commands.run(config, argparse.Namespace(
        host="127.0.0.1", port=0, token="", no_browser=True))

    assert code == 1
    said = capsys.readouterr().err
    assert "no provider configured" in said
    assert "ANTHROPIC_API_KEY" in said, "the message has to carry the answer"
    assert str(config.paths.config_file) in said


def test_at_a_terminal_it_asks_instead(config, monkeypatch):
    """Somebody who typed `comodor web` is sitting in front of a prompt."""
    import argparse

    from comodor.web import commands

    for entry in config.providers.values():
        entry.api_key = ""
        entry.configured = False
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    asked = []

    def wizard(cfg):
        asked.append(cfg)
        raise KeyboardInterrupt

    monkeypatch.setattr("comodor.setup.run_setup", wizard)

    assert commands.run(config, argparse.Namespace(
        host="127.0.0.1", port=0, token="", no_browser=True)) == 1
    assert asked, "it should have asked the setup questions"


def test_a_container_is_never_asked_a_question(config, monkeypatch, capsys):
    """Compose sets `tty: true`, so `isatty` is true inside a container whether
    or not anybody is reading it. `docker compose up -d` would otherwise sit
    forever on the first setup question - a hung container rather than a
    message somebody can act on."""
    import argparse

    from comodor.web import commands

    for entry in config.providers.values():
        entry.api_key = ""
        entry.configured = False
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("comodor.web.server.in_a_container", lambda: True)

    def wizard(cfg):
        raise AssertionError("a container was asked a question")

    monkeypatch.setattr("comodor.setup.run_setup", wizard)

    assert commands.run(config, argparse.Namespace(
        host="127.0.0.1", port=0, token="", no_browser=True)) == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
