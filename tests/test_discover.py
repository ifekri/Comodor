"""Finding what this machine already has.

Setting up an agent means finding an API key, which means a billing page, a
new secret and a decision about who to pay. For a lot of people that is
unnecessary — a local runtime is already up, or a key is already exported —
and nobody asked.

Two halves are checked here and they fail in opposite directions. A probe that
is fast when nothing is there and blind when something is proves half of what
it claims; one that finds everything and takes two seconds is a pause on every
first run that has no local model, which is most of them.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from comodor import catalogue
from comodor.providers import discover


def serving(models: list[str], status: int = 200, body: bytes | None = None):
    """Something answering `/v1/models` the way a local runtime does."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if status >= 400:
                self.send_response(status)
                self.end_headers()
                return
            payload = body if body is not None else json.dumps(
                {"object": "list",
                 "data": [{"id": name, "object": "model"} for name in models]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    return httpd


def spec_for(httpd, provider: str = "test-local"):
    port = httpd.server_address[1]
    return catalogue.ProviderSpec(
        id=provider, label="Test runtime",
        base_url=f"http://127.0.0.1:{port}/v1",
        blurb="", default_model="m", needs_key=False)


def absent(*ports: int, host: str = "127.0.0.1"):
    return [catalogue.ProviderSpec(id=f"absent{port}", label="", blurb="",
                                   base_url=f"http://{host}:{port}/v1",
                                   default_model="m", needs_key=False)
            for port in ports]


# --------------------------------------------------------------------------- #
# what is running
# --------------------------------------------------------------------------- #


def test_a_runtime_that_is_up_is_found_with_its_models():
    httpd = serving(["qwen2.5-coder:14b", "llama3.3", "deepseek-r1:14b"])
    try:
        found = discover.running_here([spec_for(httpd)])
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert len(found) == 1
    assert found[0].provider == "test-local"
    assert found[0].usable is True
    assert found[0].models == ["deepseek-r1:14b", "llama3.3", "qwen2.5-coder:14b"]
    assert "qwen2.5-coder:14b" in found[0].summary


def test_a_runtime_with_nothing_pulled_is_found_but_not_offered():
    """Ollama with no models answers happily and then fails the first real
    request. Offering it is worse than not finding it."""
    httpd = serving([])
    try:
        found = discover.running_here([spec_for(httpd)])
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert len(found) == 1
    assert found[0].usable is False
    assert "no models" in found[0].summary


def test_nothing_listening_is_simply_nothing():
    assert discover.running_here(absent(1)) == []


def test_something_that_is_not_a_model_server_is_not_one():
    """A port being open is not a runtime being there — plenty of things
    listen on a high port."""
    httpd = serving([], body=b"<html>hello</html>")
    try:
        assert discover.running_here([spec_for(httpd)]) == []
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_an_error_from_the_port_is_not_a_runtime():
    httpd = serving([], status=503)
    try:
        assert discover.running_here([spec_for(httpd)]) == []
    finally:
        httpd.shutdown()
        httpd.server_close()


# --------------------------------------------------------------------------- #
# and how long it takes to find nothing, which is what most machines pay
# --------------------------------------------------------------------------- #


@pytest.mark.performance
def test_finding_nothing_is_quick():
    """It used to cost 3.7 seconds: the client retried a refused connection
    twice, and `localhost` resolves to two addresses so each attempt was paid
    twice over."""
    started = time.monotonic()
    found = discover.running_here(absent(1, 2, 3, host="localhost"))
    took = time.monotonic() - started

    assert found == []
    assert took < 1.5, f"{took:.2f}s on a machine with nothing running"


@pytest.mark.performance
def test_a_port_that_never_answers_does_not_hold_up_a_first_run():
    """A socket that neither accepts nor refuses is the case a timeout exists
    for, and the case that hangs a wizard if one is missing."""
    listener = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = listener.server_address[1]
    spec = catalogue.ProviderSpec(id="silent", label="", blurb="", default_model="m",
                                  base_url=f"http://127.0.0.1:{port}/v1",
                                  needs_key=False)
    try:
        started = time.monotonic()
        discover.running_here([spec])
        took = time.monotonic() - started
    finally:
        listener.server_close()

    assert took < 4, f"{took:.2f}s waiting on a port that says nothing"


def test_the_probes_run_together_rather_than_one_after_another():
    six = absent(1, 2, 3, 4, 5, 6)

    started = time.monotonic()
    discover.running_here(six)
    many = time.monotonic() - started

    started = time.monotonic()
    discover.running_here(six[:1])
    one = time.monotonic() - started

    assert many < max(one, 0.05) * 3, f"six took {many:.2f}s, one took {one:.2f}s"


# --------------------------------------------------------------------------- #
# keys already exported
# --------------------------------------------------------------------------- #


def test_a_key_in_the_environment_is_reported_without_being_quoted(monkeypatch):
    """A first-run screen has no business reading a secret back at the room."""
    spec = next(item for item in catalogue.CATALOGUE if item.env_key)
    monkeypatch.setenv(spec.env_key, "sk-super-secret-value")

    mine = [item for item in discover.keys_in_the_environment()
            if item.provider == spec.id]

    assert len(mine) == 1
    assert mine[0].variable == spec.env_key
    assert "secret" not in repr(mine[0]), "the value must not travel with it"


def test_no_key_exported_is_an_empty_answer(monkeypatch):
    for spec in catalogue.CATALOGUE:
        if spec.env_key:
            monkeypatch.delenv(spec.env_key, raising=False)

    assert discover.keys_in_the_environment() == []


# --------------------------------------------------------------------------- #
# and it must never be the thing that breaks a first run
# --------------------------------------------------------------------------- #


def test_the_local_specs_are_the_ones_that_need_no_key():
    ids = {spec.id for spec in discover.local_specs()}

    assert "ollama" in ids and "lmstudio" in ids
    assert "anthropic" not in ids and "openrouter" not in ids
    for spec in discover.local_specs():
        assert spec.needs_key is False


def test_it_never_raises_whatever_it_is_handed():
    """It runs on the path that draws the first screen anybody sees, and a
    probe that raises there is a blank page instead of a question."""
    broken = [
        catalogue.ProviderSpec(id="x", label="", base_url="not a url at all",
                               blurb="", default_model="m", needs_key=False),
        catalogue.ProviderSpec(id="y", label="", base_url="",
                               blurb="", default_model="m", needs_key=False),
        catalogue.ProviderSpec(id="z", label="", blurb="", default_model="m",
                               base_url="http://no-such-host.invalid/v1",
                               needs_key=False),
    ]

    assert discover.running_here(broken) == []
