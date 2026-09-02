"""Image generation: the fuse, the adapter, and the tool's gating.

The acceptance from the spec: without ``image_gen.enabled = true`` the tool
is never advertised at all; every generation is visible in ``/cost``; going
over the daily ceiling refuses in words; and the image lands on disk with
its provenance in the transcript rather than as a base64 blob. The provider
here is a fake images-API service over a real socket, so the HTTP layer is
exercised honestly.
"""

from __future__ import annotations

import base64
import json
import struct
import threading
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from comodor.image_gen import ImageGenError
from comodor.image_gen.registry import (
    check_fuse,
    generate,
    used_today,
)

# --------------------------------------------------------------------------- #
# the fake images API
# --------------------------------------------------------------------------- #

def _png() -> bytes:
    """A real one-pixel PNG, so `sniff` sees honest bytes."""
    row = b"\x00" + b"\x10\x20\x30"
    idat = zlib.compress(row)
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))
    return b"".join((
        b"\x89PNG\r\n\x1a\n",
        chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)),
        chunk(b"IDAT", idat),
        chunk(b"IEND", b""),
    ))


class _FakeImages(BaseHTTPRequestHandler):
    received: list = []
    status = 200
    error = "the model refused for its own reasons"

    def log_message(self, *args):            # silence the test output
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).received.append((self.path, body, dict(self.headers)))
        if type(self).status != 200:
            payload = {"error": {"message": type(self).error}}
            code = type(self).status
        else:
            payload = {"data": [
                {"b64_json": base64.b64encode(_png()).decode("ascii")}]}
            code = 200
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))


@pytest.fixture
def fake_images():
    try:
        server = HTTPServer(("127.0.0.1", 0), _FakeImages)
    except PermissionError:
        pytest.skip("cannot bind a socket in this environment")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _FakeImages.received = []
    _FakeImages.status = 200
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def config(tmp_path):
    from comodor.config import load

    return load(str(tmp_path))


def _enable(config, base_url, *, model="test-image", key_env="IMAGE_KEY",
            max_per_day=10):
    config.image_gen.enabled = True
    config.image_gen.base_url = base_url
    config.image_gen.model = model
    config.image_gen.key_env = key_env
    config.image_gen.max_per_day = max_per_day
    return config


class _Store:
    """The slice of the brain store the fuse uses, over a real dict."""

    def __init__(self):
        self.meta: dict[str, str] = {}

    def get_meta(self, key):
        return self.meta.get(key)

    def set_meta(self, key, value):
        self.meta[key] = value


# --------------------------------------------------------------------------- #
# the fuse
# --------------------------------------------------------------------------- #

def test_an_empty_counter_says_zero():
    assert used_today(_Store()) == 0

def test_the_fuse_refuses_in_words_when_spent():
    store = _Store()
    with pytest.raises(ImageGenError) as caught:
        check_fuse(store, 0)
    assert "daily limit" in str(caught.value)
    assert "max_per_day" in str(caught.value)

def test_the_fuse_bumps_only_today(tmp_path):
    store = _Store()
    from comodor.image_gen import registry

    registry._bump(store)
    registry._bump(store)
    assert used_today(store) == 2
    # Older days are trimmed on the way through: the counter is a fuse, not
    # a log, and last January's number has no reader left.
    store.set_meta("image_gen.usage", '{"2020-01-01": 9}')
    registry._bump(store)
    data = json.loads(store.meta["image_gen.usage"])
    assert "2020-01-01" not in data
    assert data[registry.time.strftime("%Y-%m-%d")] == 1


# --------------------------------------------------------------------------- #
# the adapter
# --------------------------------------------------------------------------- #

def test_a_disabled_generator_refuses_and_says_how(config, fake_images):
    with pytest.raises(ImageGenError) as caught:
        generate(config, _Store(), "a lighthouse", tmp_path_art(config))
    assert "image_gen.enabled" in str(caught.value)
    assert "off by default" in str(caught.value)

def tmp_path_art(config):
    return config.paths.user / "media" / "generated"

def test_an_empty_prompt_is_refused(config, fake_images):
    _enable(config, fake_images)
    with pytest.raises(ImageGenError):
        generate(config, _Store(), "   ", tmp_path_art(config))

def test_the_key_comes_from_the_environment_not_the_config(config,
                                                           monkeypatch):
    """A remote endpoint with no key in the environment must refuse and say
    where the key belongs.

    The endpoint here is deliberately *not* the loopback one the other tests
    use: `127.0.0.1` needs no key by design, which is what the test below
    checks, so pointing this at it would assert the opposite of that rule and
    pass only while the code was wrong."""
    _enable(config, "https://images.example.invalid/v1")
    monkeypatch.delenv("IMAGE_KEY", raising=False)
    with pytest.raises(ImageGenError) as caught:
        generate(config, _Store(), "a lighthouse", tmp_path_art(config))
    assert "$IMAGE_KEY" in str(caught.value)
    assert "never read from the config file" in str(caught.value)

def test_a_local_endpoint_needs_no_key(config, fake_images, monkeypatch):
    _enable(config, fake_images)
    monkeypatch.delenv("IMAGE_KEY", raising=False)
    path = generate(config, _Store(), "a lighthouse", tmp_path_art(config))
    assert path.exists() and path.read_bytes() == _png()

def test_the_request_carries_the_model_and_the_key(config, fake_images,
                                                   monkeypatch):
    _enable(config, fake_images, model="test-image")
    monkeypatch.setenv("IMAGE_KEY", "sekrit")
    generate(config, _Store(), "a lighthouse", tmp_path_art(config))
    path, body, headers = _FakeImages.received[-1]
    assert path.endswith("/images/generations")
    assert body["model"] == "test-image"
    assert body["prompt"] == "a lighthouse"
    assert body["response_format"] == "b64_json"
    assert headers.get("Authorization") == "Bearer sekrit"

def test_a_refusal_names_the_status_and_the_reason(config, fake_images):
    _enable(config, fake_images)
    _FakeImages.status = 402
    with pytest.raises(ImageGenError) as caught:
        generate(config, _Store(), "a lighthouse", tmp_path_art(config))
    assert "402" in str(caught.value)
    assert "the model refused" in str(caught.value)

def test_a_success_writes_the_file_and_bumps_the_fuse(config, fake_images,
                                                      monkeypatch):
    _enable(config, fake_images)
    monkeypatch.setenv("IMAGE_KEY", "k")
    store = _Store()
    path = generate(config, store, "a lighthouse", tmp_path_art(config))
    assert path.exists() and path.suffix == ".png"
    assert used_today(store) == 1

def test_the_ceiling_stops_a_second_call(config, fake_images, monkeypatch):
    _enable(config, fake_images, max_per_day=1)
    monkeypatch.setenv("IMAGE_KEY", "k")
    store = _Store()
    generate(config, store, "one", tmp_path_art(config))
    with pytest.raises(ImageGenError) as caught:
        generate(config, store, "two", tmp_path_art(config))
    assert "daily limit of 1" in str(caught.value)
    assert len(_FakeImages.received) == 1, "the second call must not reach \
the provider at all"


# --------------------------------------------------------------------------- #
# the tool: advertised only when on, returning the image it made
# --------------------------------------------------------------------------- #

def test_the_tool_is_absent_until_enabled():
    from comodor.config import Config
    from comodor.paths import Paths
    from comodor.tools.registry import ToolRegistry

    off = ToolRegistry(config=Config(paths=Paths(user=__import__("pathlib").
                                                 Path("/nonexistent-test-home"),
                                                 project=__import__("pathlib").
                                                 Path("/nonexistent-test-proj"))))
    assert "image_gen" not in off


def test_the_tool_runs_and_returns_the_image(config, fake_images, monkeypatch,
                                             tool_context):
    from comodor.tools.image_gen import ImageGen

    class _Memory:
        store = _Store()

    _enable(config, fake_images)
    monkeypatch.setenv("IMAGE_KEY", "k")
    tool_context.brain_store = _Memory.store
    result = ImageGen().run(tool_context, prompt="a lighthouse")
    assert result.ok
    assert result.meta["image"]
    assert base64.b64decode(result.meta["image"]) == _png()
    assert "[the image follows]" in result.content
    assert "a lighthouse" in result.content, "the prompt is the provenance"


def test_the_tool_without_a_brain_refuses_clearly(tool_context, config,
                                                  fake_images):
    from comodor.tools.image_gen import ImageGen

    _enable(config, fake_images)
    result = ImageGen().run(tool_context, prompt="a lighthouse")
    assert not result.ok
    assert "brain" in result.content


def test_a_dangeroous_risk_keeps_it_behind_approval():
    from comodor.safety import Risk
    from comodor.tools.image_gen import ImageGen

    assert ImageGen.risk is Risk.DANGEROUS
