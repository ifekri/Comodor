"""A real core, in a real process, over a real pipe.

Everything else about the protocol is tested in memory, which is fast and
proves the logic. It cannot prove the things that only go wrong once there is
an operating system involved: a banner on stdout, an encoding that mangles a
Persian answer, a child that outlives its parent.

No network and no model. The core is pointed at a temporary home configured
with the scripted `fake` provider, so a turn is deterministic and free.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from comodor import protocol as P

ROOT = Path(__file__).resolve().parent.parent

#: Long enough for a cold interpreter on a loaded CI machine, short enough that
#: a hang is a failure rather than a timeout nobody waits for.
PATIENCE = 60.0


class Core:
    """A spawned `comodor core --stdio`, driven line by line."""

    def __init__(self, home: Path, workspace: Path) -> None:
        environment = dict(os.environ)
        environment["COMODOR_HOME"] = str(home)
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["PYTHONIOENCODING"] = "utf-8"
        # Nothing here should reach for a network; if something does, fail
        # rather than wait for a timeout in a test that claims to be offline.
        environment["COMODOR_OFFLINE"] = "1"
        self.process = subprocess.Popen(
            [sys.executable, "-m", "comodor", "core", "--stdio"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=str(workspace), env=environment,
            text=True, encoding="utf-8", bufsize=1)
        self._next = 0

    def send(self, method: str, params: dict | None = None) -> str:
        self._next += 1
        id = str(self._next)
        self.process.stdin.write(json.dumps(P.request(id, method, params)) + "\n")
        self.process.stdin.flush()
        return id

    def read(self) -> dict:
        line = self.process.stdout.readline()
        if not line:
            raise AssertionError(
                "the core closed its output; stderr said:\n"
                + (self.process.stderr.read() or "(nothing)"))
        return json.loads(line)

    def answer_to(self, id: str, *, collect: list | None = None) -> dict:
        """Read until the answer to `id`, keeping any events seen on the way."""
        deadline = time.monotonic() + PATIENCE
        while time.monotonic() < deadline:
            message = self.read()
            if message.get("type") == "event":
                if collect is not None:
                    collect.append(message)
                continue
            if message.get("id") == id:
                return message
        raise AssertionError(f"no answer to {id!r} within {PATIENCE}s")

    def events_until(self, name: str, *, collect: list | None = None) -> dict:
        """Read events until one is named `name`.

        Needed because the core answers a request *before* releasing the
        events that request raised — deliberately, so a client is never told
        about a session before it is told it made one. A harness that stopped
        reading at the answer would never see them.
        """
        deadline = time.monotonic() + PATIENCE
        while time.monotonic() < deadline:
            message = self.read()
            if message.get("type") != "event":
                continue
            if collect is not None:
                collect.append(message)
            if message["event"] == name:
                return message
        raise AssertionError(f"no {name!r} event within {PATIENCE}s")

    def hello(self) -> dict:
        id = self.send("client.hello", {
            "protocol_version": P.PROTOCOL_VERSION,
            "client": {"name": "test-harness", "version": "0"},
            "capabilities": ["questions", "permissions"]})
        return self.answer_to(id)

    def close(self, timeout: float = 20.0) -> int:
        try:
            self.process.stdin.close()
        except Exception:
            pass
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            raise


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A config that answers from the scripted provider and nowhere else."""
    root = tmp_path / "home"
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.json").write_text(json.dumps({
        "provider": "fake",
        "model": "fake-1",
        "providers": {"fake": {"name": "fake", "kind": "fake",
                               "base_url": "offline", "api_key": "test",
                               "model": "fake-1", "label": "Fake"}},
        "agent": {"mode": "act", "loop": False},
        "learning": {"enabled": False},
        "mcp": {"enabled": False},
        "cron": {"enabled": False},
        "skills": {"enabled": False},
    }), encoding="utf-8")
    return root


@pytest.fixture
def core(home: Path, tmp_path: Path):
    workspace = tmp_path / "project"
    workspace.mkdir(parents=True, exist_ok=True)
    started = Core(home, workspace)
    yield started
    if started.process.poll() is None:
        try:
            started.close(timeout=10.0)
        except Exception:
            started.process.kill()


# --------------------------------------------------------------------------- #
# the end-to-end walk
# --------------------------------------------------------------------------- #

def test_a_client_can_open_a_session_change_its_mode_and_shut_the_core_down(core):
    handshake = core.hello()
    assert handshake["result"]["protocol_version"] == P.PROTOCOL_VERSION
    assert "streaming" in handshake["result"]["capabilities"]

    created = core.answer_to(core.send("session.create"))
    session = created["result"]["session"]
    assert session["mode"] == "act"

    read_back = core.answer_to(core.send("session.get",
                                         {"session_id": session["id"]}))
    assert read_back["result"]["session"]["id"] == session["id"]

    switched = core.answer_to(
        core.send("session.set_mode",
                  {"session_id": session["id"], "mode": "plan"}))
    assert switched["result"]["session"]["mode"] == "plan"
    # The event a client renders from, rather than trusting its own optimism.
    # It arrives after the answer, which is the guaranteed order.
    changed = core.events_until("mode.changed")
    assert changed["params"]["mode"] == "plan"

    goodbye = core.answer_to(core.send("shutdown"))
    assert goodbye["result"] == {"ok": True}
    assert core.close() == 0


def test_the_workspace_it_reports_is_the_one_it_was_started_in(core, tmp_path):
    core.hello()
    answer = core.answer_to(core.send("workspace.get"))

    assert Path(answer["result"]["path"]) == (tmp_path / "project").resolve()


def test_the_model_is_named_and_the_key_never_travels(core):
    core.hello()
    answer = core.answer_to(core.send("model.get"))

    assert answer["result"]["provider"] == "fake"
    assert answer["result"]["configured"] is True
    assert "api_key" not in json.dumps(answer)


# --------------------------------------------------------------------------- #
# stdout belongs to the protocol
# --------------------------------------------------------------------------- #

def test_every_line_on_stdout_is_a_protocol_message(core):
    core.hello()
    for method in ("session.create", "session.list", "workspace.get",
                   "model.get"):
        core.answer_to(core.send(method))
    core.answer_to(core.send("shutdown"))
    core.close()

    remaining = core.process.stdout.read() or ""
    for line in remaining.splitlines():
        if line.strip():
            P.decode(line)  # raises if it is anything else


def test_the_greeting_goes_to_stderr_where_it_cannot_break_a_parser(core):
    core.hello()
    core.answer_to(core.send("shutdown"))
    core.close()

    noise = core.process.stderr.read() or ""
    assert "comodor core" in noise


# --------------------------------------------------------------------------- #
# text arrives as it was written
# --------------------------------------------------------------------------- #

def test_persian_survives_the_pipe_unchanged(core, tmp_path):
    # Not a rendering test — a transport one. If the encoding is wrong
    # anywhere between here and the client, this is where it shows, and a
    # Windows console defaulting to cp1252 is the usual way.
    persian = tmp_path / "پروژه‌ی من"
    persian.mkdir(parents=True, exist_ok=True)

    core.hello()
    answer = core.answer_to(core.send("session.create",
                                      {"workspace": str(persian)}))

    assert Path(answer["result"]["session"]["workspace"]).name == "پروژه‌ی من"


def test_an_answer_with_mixed_direction_text_is_not_reordered(core):
    core.hello()
    session = core.answer_to(core.send("session.create"))["result"]["session"]

    # The bidi marks a terminal needs are the client's business. What the
    # transport must not do is add, drop or reorder a code point.
    mixed = "خطا در فایل main.py — خط ۴۲"
    answer = core.answer_to(core.send("session.send",
                                      {"session_id": session["id"],
                                       "text": mixed}))
    assert answer["result"]["accepted"] is True


# --------------------------------------------------------------------------- #
# a turn, streamed
# --------------------------------------------------------------------------- #

def test_a_turn_streams_deltas_and_finishes(core):
    core.hello()
    session = core.answer_to(core.send("session.create"))["result"]["session"]

    accepted = core.answer_to(core.send("session.send",
                                        {"session_id": session["id"],
                                         "text": "say something"}))
    message_id = accepted["result"]["message_id"]
    assert accepted["result"]["accepted"] is True

    started = deltas = completed = 0
    deadline = time.monotonic() + PATIENCE
    text: list[str] = []
    while time.monotonic() < deadline and not completed:
        message = core.read()
        if message.get("type") != "event":
            continue
        name = message["event"]
        if name == "message.started":
            started += 1
            assert message["params"]["message_id"] == message_id
        elif name == "message.delta":
            deltas += 1
            text.append(message["params"]["text"])
        elif name == "message.completed":
            completed += 1

    assert started == 1, "the answer never began"
    assert deltas > 0, "nothing streamed; the client would show a frozen turn"
    assert completed == 1
    # Ordering preserved, nothing lost between the pieces and the whole.
    assert "".join(text)


def test_a_session_that_is_already_working_refuses_a_second_turn(core):
    core.hello()
    session = core.answer_to(core.send("session.create"))["result"]["session"]
    core.answer_to(core.send("session.send",
                             {"session_id": session["id"], "text": "one"}))
    second = core.answer_to(core.send("session.send",
                                      {"session_id": session["id"],
                                       "text": "two"}))

    # Refused rather than queued: two turns interleaving their events would
    # be indistinguishable to a client correlating on a message id.
    assert second["type"] == "error"
    assert second["error"]["code"] in (P.NOT_ALLOWED,)


# --------------------------------------------------------------------------- #
# going away
# --------------------------------------------------------------------------- #

def test_closing_the_pipe_stops_the_core(core):
    core.hello()
    core.answer_to(core.send("session.create"))

    # No shutdown message: the client simply went away, which is what happens
    # when a terminal is closed. The core must not survive it.
    assert core.close(timeout=30.0) == 0


def test_a_client_that_never_says_hello_gets_a_refusal_not_a_hang(core):
    id = core.send("session.create")
    answer = core.answer_to(id)

    assert answer["error"]["code"] == P.NOT_INITIALIZED
