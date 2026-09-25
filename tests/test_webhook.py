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


# --------------------------------------------------------------------------- #
# T204 — a webhook event is a stateless run; it keeps a hidden continuation
# only when it stops, and no later event resumes it
# --------------------------------------------------------------------------- #


def _isolated_config(tmp_path):
    """A config wholly inside tmp_path, on the fake provider: nothing here may
    reach the real user's home, where continuations would otherwise land."""
    from comodor.config import Config, ProviderConfig
    from comodor.paths import Paths

    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "home").mkdir()
    cfg = Config(paths=Paths(user=tmp_path / "home", project=project))
    cfg.providers = {"fake": ProviderConfig(name="fake", kind="fake", base_url="offline",
                                            api_key="test", model="fake-1", label="Fake")}
    cfg.provider, cfg.model = "fake", "fake-1"
    cfg.agent.context_limit = 100_000
    cfg.learning.enabled = False
    return cfg


@pytest.fixture
def iso(tmp_path):
    return _isolated_config(tmp_path)


@pytest.fixture
def iso_server(iso, tmp_path):
    from comodor.webhook.server import Server
    from comodor.webhook.subs import Sub, Subscriptions

    made = Server(iso, host="127.0.0.1", port=0, subs=Subscriptions(tmp_path / "hook"))
    made.subs.add(Sub(name="ci", path="/ci", secret="s3cret", template="Build: {.status}"))
    return made


def _stopping_plans(monkeypatch, *plans):
    from comodor.providers.gateway import Gateway as RealGateway

    queue = [list(plan) for plan in plans]

    def factory(configuration, scripts=None):
        return RealGateway(configuration, scripts=queue.pop(0) if queue else [])

    monkeypatch.setattr("comodor.cron.runner.Gateway", factory)
    monkeypatch.setattr("comodor.providers.gateway.Gateway", factory)


def _ask_branch():
    from comodor.providers.base import ToolCall

    return ToolCall(id="q1", name="ask", arguments={"questions": [{
        "question": "Which environment is this build for?", "header": "Environment",
        "affects": ["behaviour"],
        "options": [{"label": "staging", "source": "request", "evidence": "staging"},
                    {"label": "production", "source": "request",
                     "evidence": "production"}]}]})


def _continuations(config):
    from comodor.session.store import SessionStore

    return SessionStore(config.paths.user / "sessions").list_sessions(
        include_continuations=True)


def test_a_webhook_event_that_stops_keeps_one_plan_mode_continuation(iso_server, iso, monkeypatch):
    server, config = iso_server, iso
    from comodor.providers.fake import Script
    from comodor.webhook.server import Event

    _stopping_plans(monkeypatch, [Script(text="A question.", tool_calls=[_ask_branch()])])
    server._run(Event(sub=server.subs.by_path("/ci"),
                      payload={"status": "staging or production"}))
    (meta,) = _continuations(config)
    assert meta.continuation["mode"] == "plan"
    from comodor.session.store import SessionStore

    assert SessionStore(config.paths.user / "sessions").list_sessions() == []


def test_a_later_unrelated_webhook_event_does_not_resume_it(iso_server, iso, monkeypatch):
    server, config = iso_server, iso
    from comodor.providers.fake import Script
    from comodor.session.store import SessionStore
    from comodor.webhook.server import Event

    _stopping_plans(monkeypatch, [Script(text="A question.", tool_calls=[_ask_branch()])],
                    [Script(text="Build noted.")])
    server._run(Event(sub=server.subs.by_path("/ci"), payload={"status": "red"}))
    (meta,) = _continuations(config)
    ref = meta.continuation["decision_refs"][0]
    store = SessionStore(config.paths.user / "sessions")
    before = store.path_for(meta.id).read_bytes()
    server._run(Event(sub=server.subs.by_path("/ci"), payload={"status": "green"}))
    assert [m.id for m in _continuations(config)] == [meta.id]
    assert store.path_for(meta.id).read_bytes() == before
    assert store.decisions(meta.id)[ref].status == "open"


def test_the_webhooks_stopped_run_resumes_only_by_explicit_ref_in_its_mode(
        iso_server, iso, monkeypatch):
    server, config = iso_server, iso
    import argparse
    import io
    import json
    from contextlib import redirect_stderr, redirect_stdout

    from comodor import cli
    from comodor.providers.fake import Script
    from comodor.session.store import SessionStore
    from comodor.webhook.server import Event

    config.learning.enabled = False
    _stopping_plans(monkeypatch, [Script(text="A question.", tool_calls=[_ask_branch()])],
                    [Script(text="Planned for staging.")])
    server._run(Event(sub=server.subs.by_path("/ci"), payload={"status": "red"}))
    (meta,) = _continuations(config)
    ref = meta.continuation["decision_refs"][0]
    answers = config.paths.user / "answers.json"
    answers.write_text(json.dumps([{"decision_ref": ref, "written": "staging"}]),
                       encoding="utf-8")

    def resume(mode):
        config.agent.mode = mode
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = cli.run_headless(config, argparse.Namespace(
                task="", yes=False, json=True, max_steps=5,
                decision_answers=str(answers)))
        return code, json.loads(out.getvalue())

    code, report = resume("act")
    assert code == 1 and report["error"]["kind"] == "mode", \
        "act capability is never granted to work that stopped in plan mode"
    code, report = resume("plan")
    assert code == 0 and report["stopped"] == "done"
    store = SessionStore(config.paths.user / "sessions")
    assert store.decisions(meta.id)[ref].status == "stale"
