"""The optional external memory provider.

The acceptance list, from the spec: with the service fully down, everything
works as before and only a warning is logged; a fact written locally shows
up in the external service (against a fake); and no key ever lands on disk
— the build refuses without one and `doctor` confirms it. The provider here
is the generic HTTP dialect, driven against a fake in-process service.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from comodor.events import Kind
from comodor.learning.providers import ProviderError, build
from comodor.learning.providers.base import Settings, provider_from_config
from comodor.learning.providers.http_generic import HttpGeneric, _capped


@pytest.fixture
def config(tmp_path):
    from comodor.config import load

    return load(str(tmp_path))

# --------------------------------------------------------------------------- #
# the fake service: a real socket, so the HTTP layer is exercised honestly
# --------------------------------------------------------------------------- #

class _Fake(BaseHTTPRequestHandler):
    received: list = []
    healthy = True

    def log_message(self, *args):            # silence the test output
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).received.append((self.path, body,
                                    dict(self.headers)))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def do_GET(self):
        if self.path.startswith("/search"):
            query = self.path.split("q=", 1)[-1]
            payload = {"results": [
                {"text": f"about {query} one"},
                {"text": f"about {query} two"},
            ]}
        elif self.path.startswith("/health"):
            if not type(self).healthy:
                self.send_response(503)
                self.end_headers()
                return
            payload = {"ok": True}
        else:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

@pytest.fixture
def fake_service():
    try:
        server = HTTPServer(("127.0.0.1", 0), _Fake)
    except PermissionError:
        pytest.skip("cannot bind a socket in this environment")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _Fake.received = []
    _Fake.healthy = True
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()

def _configure(config, base_url, *, kind="http_generic", key_env="PROVIDER_KEY",
               read_augment=False, mirror_writes=True):
    config.learning.provider.kind = kind
    config.learning.provider.base_url = base_url
    config.learning.provider.key_env = key_env
    config.learning.provider.read_augment = read_augment
    config.learning.provider.mirror_writes = mirror_writes
    return config

# --------------------------------------------------------------------------- #
# building one: the refusals are the security story
# --------------------------------------------------------------------------- #

def test_no_kind_means_no_provider(config):
    assert build(config) is None

def test_a_kind_without_a_key_is_refused_and_names_the_variable(config,
                                                                fake_service):
    _configure(config, fake_service, key_env="PROVIDER_KEY")
    with pytest.raises(ProviderError) as caught:
        build(config)
    assert "$PROVIDER_KEY" in str(caught.value)
    assert "never read from the config file" in str(caught.value)

def test_a_kind_and_key_without_a_base_url_is_refused(config, monkeypatch):
    monkeypatch.setenv("PROVIDER_KEY", "k")
    config.learning.provider.kind = "http_generic"
    config.learning.provider.key_env = "PROVIDER_KEY"
    with pytest.raises(ProviderError) as caught:
        build(config)
    assert "base_url" in str(caught.value)

def test_an_unknown_kind_is_refused_and_names_the_known_ones(config, monkeypatch):
    monkeypatch.setenv("PROVIDER_KEY", "k")
    _configure(config, "http://127.0.0.1:1", kind="fancyservice")
    with pytest.raises(ProviderError) as caught:
        build(config)
    assert "http_generic" in str(caught.value)

def test_mem0_is_an_alias_of_the_generic_dialect(config, monkeypatch,
                                                 fake_service):
    monkeypatch.setenv("PROVIDER_KEY", "k")
    _configure(config, fake_service, kind="mem0")
    assert isinstance(build(config), HttpGeneric)

def test_provider_from_config_absorbs_setup_problems_by_default(config,
                                                                monkeypatch,
                                                                fake_service):
    _configure(config, fake_service)
    monkeypatch.delenv("PROVIDER_KEY", raising=False)
    assert provider_from_config(config) is None

def test_provider_from_config_raises_when_needed(config, monkeypatch,
                                                 fake_service):
    _configure(config, fake_service)
    monkeypatch.delenv("PROVIDER_KEY", raising=False)
    with pytest.raises(ProviderError):
        provider_from_config(config, needed=True)

# --------------------------------------------------------------------------- #
# the dialect: mirror writes land, search answers, down is fail-open
# --------------------------------------------------------------------------- #

def test_a_mirrored_write_arrives_with_text_kind_and_key(fake_service,
                                                         monkeypatch):
    monkeypatch.setenv("PROVIDER_KEY", "k")
    provider = HttpGeneric(Settings(kind="http_generic",
                                    base_url=fake_service,
                                    key_env="PROVIDER_KEY"), "k")
    assert provider.mirror_write("the deploy script needs python 3.12",
                                 "memory") is True
    path, body, headers = _Fake.received[-1]
    assert path == "/entries"
    assert body["text"] == "the deploy script needs python 3.12"
    assert body["kind"] == "memory"
    assert headers.get("Authorization") == "Bearer k"

def test_a_write_to_a_dead_service_is_false_not_an_exception(fake_service):
    provider = HttpGeneric(Settings(kind="http_generic",
                                    base_url="http://127.0.0.1:1",
                                    key_env="PROVIDER_KEY"), "k")
    assert provider.mirror_write("anything", "memory") is False

def test_search_returns_the_texts(fake_service):
    provider = HttpGeneric(Settings(kind="http_generic",
                                    base_url=fake_service,
                                    key_env="PROVIDER_KEY"), "k")
    lines = provider.augment_recall("deploys")
    assert lines == ["about deploys one", "about deploys two"]

def test_a_dead_service_augments_nothing_and_raises_nothing(fake_service):
    provider = HttpGeneric(Settings(kind="http_generic",
                                    base_url="http://127.0.0.1:1",
                                    key_env="PROVIDER_KEY"), "k")
    assert provider.augment_recall("anything") == []

def test_status_reports_a_live_service_by_kind(fake_service):
    provider = HttpGeneric(Settings(kind="http_generic",
                                    base_url=fake_service,
                                    key_env="PROVIDER_KEY"), "k")
    assert "reachable (http_generic)" in provider.status()

def test_status_reports_a_dead_service_honestly(fake_service):
    _Fake.healthy = False
    provider = HttpGeneric(Settings(kind="http_generic",
                                    base_url=fake_service,
                                    key_env="PROVIDER_KEY"), "k")
    assert "answered 503" in provider.status()

def test_status_names_an_unreachable_service(fake_service):
    provider = HttpGeneric(Settings(kind="http_generic",
                                    base_url="http://127.0.0.1:1",
                                    key_env="PROVIDER_KEY"), "k")
    assert "unreachable" in provider.status()

# --------------------------------------------------------------------------- #
# the augmentation budget
# --------------------------------------------------------------------------- #

def test_the_budget_stops_at_a_whole_line():
    assert _capped(["short", "x" * 1700]) == ["short"]

def test_nothing_gets_in_over_the_budget():
    assert _capped(["x" * 1700, "tiny"]) == []

# --------------------------------------------------------------------------- #
# wired into the brain: a local fact lands in the external service
# --------------------------------------------------------------------------- #

def test_a_local_fact_is_mirrored_to_the_service(config, bus, monkeypatch,
                                                 fake_service):
    monkeypatch.setenv("PROVIDER_KEY", "k")
    _configure(config, fake_service)
    from comodor.learning.memory import LearningEngine

    engine = LearningEngine(config, bus)
    try:
        engine.add_fact("staging speaks to the beta api only")
    finally:
        engine.close()
    path, body, _headers = _Fake.received[-1]
    assert path == "/entries"
    assert "staging speaks to the beta api only" in body["text"]

def test_the_service_being_down_changes_nothing_but_a_notice(config, bus,
                                                             monkeypatch):
    monkeypatch.setenv("PROVIDER_KEY", "k")
    _configure(config, "http://127.0.0.1:1")
    from comodor.learning.memory import LearningEngine

    engine = LearningEngine(config, bus)
    notices = []
    try:
        engine.bus.subscribe(lambda event: notices.append(event)
                             if event.kind == Kind.NOTICE else None)
        fact = engine.add_fact("the fact is true regardless")
        assert fact.text == "the fact is true regardless"
    finally:
        engine.close()
    assert notices, "a down mirror must be said, not swallowed"

def test_recall_gains_nothing_without_read_augment(config, bus, monkeypatch,
                                                   fake_service):
    monkeypatch.setenv("PROVIDER_KEY", "k")
    _configure(config, fake_service, read_augment=False)
    from comodor.learning.memory import LearningEngine

    engine = LearningEngine(config, bus)
    try:
        assert engine.external_briefing("anything") == ""
    finally:
        engine.close()

def test_read_augment_adds_marked_capped_lines(config, bus, monkeypatch,
                                               fake_service):
    monkeypatch.setenv("PROVIDER_KEY", "k")
    _configure(config, fake_service, read_augment=True)
    from comodor.learning.memory import LearningEngine

    engine = LearningEngine(config, bus)
    try:
        briefing = engine.external_briefing("deploys")
    finally:
        engine.close()
    assert briefing.startswith("From your external memory service")
    assert "- about deploys one" in briefing
    assert "- about deploys two" in briefing

def test_a_down_service_returns_an_empty_briefing(config, bus, monkeypatch):
    _configure(config, "http://127.0.0.1:1", read_augment=True)
    monkeypatch.delenv("PROVIDER_KEY", raising=False)
    from comodor.learning.memory import LearningEngine

    engine = LearningEngine(config, bus)
    try:
        assert engine.external_briefing("anything") == ""
    finally:
        engine.close()

# --------------------------------------------------------------------------- #
# no key on disk, and doctor confirms it
# --------------------------------------------------------------------------- #

def test_a_saved_config_holds_no_key(config, fake_service, monkeypatch):
    _configure(config, fake_service)
    monkeypatch.setenv("PROVIDER_KEY", "k")
    config.save()
    document = json.loads(config.paths.config_file.read_text(encoding="utf-8"))
    blob = json.dumps(document)
    assert "api_key" not in blob and '"key"' not in blob

def test_doctor_reports_a_provider_with_no_key(config, monkeypatch):
    _configure(config, "http://127.0.0.1:9310", key_env="MEM0_API_KEY")
    monkeypatch.delenv("MEM0_API_KEY", raising=False)
    from comodor.doctor import run_checks

    report = run_checks(config, online=False)
    said = [f.detail for f in report.findings if f.name == "memory provider"]
    assert any("$MEM0_API_KEY" in message for message in said)

def test_doctor_reports_an_unreachable_service(config, monkeypatch):
    _configure(config, "http://127.0.0.1:1", key_env="MEM0_API_KEY")
    monkeypatch.setenv("MEM0_API_KEY", "k")
    from comodor.doctor import run_checks

    report = run_checks(config, online=False)
    said = [f.detail for f in report.findings if f.name == "memory provider"]
    assert any("unreachable" in message for message in said)

def test_doctor_says_nothing_when_no_provider_is_configured(config):
    from comodor.doctor import run_checks

    report = run_checks(config, online=False)
    assert not [f for f in report.findings if f.name == "memory provider"]
