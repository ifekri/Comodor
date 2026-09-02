"""The general webhook channel.

The acceptance list, from the spec: a genuine signature gets a turn, one
flipped byte gets a 404 that reveals nothing, an oversized body is dropped
before it is parsed, and ten simultaneous events queue in order rather
than anyone's work vanishing. The template engine is tested against the
payloads that make it lie — missing fields, nested ones, arrays.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat

import pytest

from comodor.webhook.server import Server, signature_ok
from comodor.webhook.subs import Sub, Subscriptions, render


@pytest.fixture
def config(tmp_path):
    from comodor.config import load

    return load(str(tmp_path))


# --------------------------------------------------------------------------- #
# signatures, on raw bytes
# --------------------------------------------------------------------------- #

def _signed(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_a_genuine_signature_passes():
    body = b'{"a": 1}'
    assert signature_ok(body, _signed(body, "s3cret"), "s3cret")


def test_one_flipped_byte_fails():
    body = b'{"a": 1}'
    assert not signature_ok(body, _signed(b'{"a": 2}', "s3cret"), "s3cret")


def test_no_secret_fails_closed():
    body = b'{"a": 1}'
    assert not signature_ok(body, _signed(body, "s3cret"), "")
    assert not signature_ok(body, "", "s3cret")


def test_a_tampered_digest_is_not_accepted():
    body = b'{"a": 1}'
    signed = _signed(body, "s3cret")
    # Flip the last hex digit.
    bad = signed[:-1] + ("0" if signed[-1] != "0" else "1")
    assert not signature_ok(body, bad, "s3cret")


# --------------------------------------------------------------------------- #
# templates, against the payloads that make them lie
# --------------------------------------------------------------------------- #

def test_the_whole_payload_fills_in():
    out = render("CI says: {payload}", {"ok": True})
    assert '"ok": true' in out


def test_a_field_path_picks_one_value():
    out = render("PR: {.pull_request.title}",
                 {"pull_request": {"title": "fix the lock"}})
    assert out == "PR: fix the lock"


def test_a_missing_field_is_named_not_crashed():
    out = render("PR: {.pull_request.title}", {"action": "opened"})
    assert "missing" in out, "the agent must know the event was half-formed"
    assert "pull_request.title" in out


def test_a_nested_object_travels_as_json():
    out = render("changed: {.commits}", {"commits": [{"id": "a"}, {"id": "b"}]})
    assert json.loads(out.removeprefix("changed: ")) == [
        {"id": "a"}, {"id": "b"}]


def test_a_null_field_is_empty_not_the_word_none():
    out = render("who: {.actor}", {"actor": None})
    assert out == "who: "


# --------------------------------------------------------------------------- #
# subscriptions: the file, its secrets, its honesty
# --------------------------------------------------------------------------- #

def test_subscriptions_round_trip(tmp_path):
    subs = Subscriptions(tmp_path / "hook")
    subs.add(Sub(name="ci", path="/ci", secret="s3cret",
                 template="{payload}"))
    assert subs.by_path("/ci").secret == "s3cret"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions only")
def test_the_subscriptions_file_is_not_readable_by_anybody_else(tmp_path):
    """It holds every webhook secret. Windows has no mode bits to set, and
    `chmod` there is a no-op that would fail this rather than report it."""
    subs = Subscriptions(tmp_path / "hook")
    subs.add(Sub(name="ci", path="/ci", secret="s3cret",
                 template="{payload}"))

    mode = (tmp_path / "hook" / "subs.json").stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


def test_adding_replaces_by_name_not_duplicates(tmp_path):
    subs = Subscriptions(tmp_path / "hook")
    subs.add(Sub(name="ci", path="/one", secret="a", template="x"))
    subs.add(Sub(name="ci", path="/two", secret="b", template="y"))
    found = subs.load()
    assert len(found) == 1
    assert found[0].path == "/two"


def test_a_broken_subscriptions_file_is_empty_not_fatal(tmp_path):
    root = tmp_path / "hook"
    root.mkdir()
    (root / "subs.json").write_text("{ not json", encoding="utf-8")
    assert Subscriptions(root).load() == []


# --------------------------------------------------------------------------- #
# the server: accept, refuse, queue
# --------------------------------------------------------------------------- #

@pytest.fixture
def server(config, tmp_path):
    made = Server(config, host="127.0.0.1", port=0,
                  subs=Subscriptions(tmp_path / "hook"))
    made.subs.add(Sub(name="ci", path="/ci", secret="s3cret",
                      template="Build: {.status}"))
    return made


@pytest.fixture
def listening(server):
    """The same server, with something actually answering the socket.

    `bind` takes the port and nothing more; `serve` is what reads from it.
    A test that binds and then sends a request is talking to a socket whose
    accept queue nobody drains, and waits out its own client timeout.
    """
    import threading

    try:
        server.bind()
    except (OSError, PermissionError):
        pytest.skip("cannot bind a socket in this environment")

    thread = threading.Thread(target=server._httpd.serve_forever,
                              kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield server
    server._httpd.shutdown()
    server._httpd.server_close()


def test_a_verified_event_is_queued_not_run_inline(server):
    ok, why = server.accept(server.subs.by_path("/ci"), {"status": "green"})
    assert ok and why == ""
    assert server._queue.qsize() == 1


def test_a_full_queue_refuses_with_503_language(server):
    for number in range(32):
        ok, _ = server.accept(server.subs.by_path("/ci"), {"n": number})
        assert ok
    ok, why = server.accept(server.subs.by_path("/ci"), {"n": 33})
    assert not ok and "full" in why


def test_the_recent_log_says_what_happened(server):
    server.accept(server.subs.by_path("/ci"), {"status": "green"})
    assert server.recent[-1]["event"] == "accepted"
    assert server.recent[-1]["path"] == "/ci"


def test_the_run_uses_the_cron_runner_with_the_rendered_prompt(server,
                                                               monkeypatch):
    """One accepted event is one fresh agent turn, plan mode, no writes."""
    seen = {}

    class FakeOutcome:
        ok = True
        answer = "done"
        error = ""
        tool_calls = 0
        steps = 1
        model = "m"
        tools_used = []

    def fake_run(cfg, job):
        seen["mode"] = cfg.agent.mode
        seen["prompt"] = job.prompt
        seen["writes"] = cfg.safety.auto_approve_writes
        return FakeOutcome()

    monkeypatch.setattr("comodor.cron.runner.run_job", fake_run)
    from comodor.webhook.server import Event

    server._run(Event(sub=server.subs.by_path("/ci"),
                      payload={"status": "green"}))
    assert seen["prompt"] == "Build: green"
    assert seen["mode"] == "plan", "a webhook reads and plans unless told"
    assert seen["writes"] is False


def test_an_allow_writes_subscription_actually_writes(server, monkeypatch):
    seen = {}
    server.subs.add(Sub(name="writer", path="/w", secret="x",
                        template="{payload}", allow_writes=True))

    class FakeOutcome:
        ok = True
        answer = ""
        error = ""
        tool_calls = 0
        steps = 1
        model = ""
        tools_used = []

    def fake_run(cfg, job):
        seen["writes"] = cfg.safety.auto_approve_writes
        seen["mode"] = cfg.agent.mode
        return FakeOutcome()

    monkeypatch.setattr("comodor.cron.runner.run_job", fake_run)
    from comodor.webhook.server import Event

    server._run(Event(sub=server.subs.by_path("/w"), payload={"x": 1}))
    assert seen["writes"] is True
    assert seen["mode"] != "plan"


# --------------------------------------------------------------------------- #
# the HTTP layer, where a socket may be bound
# --------------------------------------------------------------------------- #

def _deliver(port: int, path: str, secret: str, body: bytes,
             sign: bool = True) -> tuple[int, str]:
    import urllib.error
    import urllib.request

    headers = {"Content-Type": "application/json"}
    if sign:
        headers["X-Comodor-Signature-256"] = _signed(body, secret)
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                     data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as answer:
            return answer.status, answer.read().decode("utf-8")
    except urllib.error.HTTPError as problem:
        return problem.code, problem.read().decode("utf-8")


def test_a_valid_delivery_is_accepted(listening):
    status, body = _deliver(listening.port, "/ci", "s3cret",
                            b'{"status": "green"}')
    assert status == 202
    assert json.loads(body)["status"] == "accepted"


def test_a_forged_signature_is_a_404_that_says_nothing(listening):
    status, body = _deliver(listening.port, "/ci", "wrong",
                            b'{"status": "green"}')
    assert status == 404
    assert json.loads(body) == {"error": "not found"}


def test_an_unknown_path_and_a_bad_signature_look_identical(listening):
    known = _deliver(listening.port, "/ci", "wrong", b'{"a": 1}')
    unknown = _deliver(listening.port, "/never-existed", "wrong", b'{"a": 1}')
    assert known == unknown, "a prober must not learn which paths exist"


def test_an_unsigned_delivery_is_refused(listening):
    status, _ = _deliver(listening.port, "/ci", "s3cret",
                         b'{"status": "green"}', sign=False)
    assert status == 404
