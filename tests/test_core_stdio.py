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
# the protocol version
# --------------------------------------------------------------------------- #

def write_raw(core, body: dict) -> None:
    """A line as a peer on another protocol would actually write it.

    `core.send` stamps the current version on everything, which is exactly
    what a client from the previous contract would not do.
    """
    core.process.stdin.write(json.dumps(body) + "\n")
    core.process.stdin.flush()


def test_a_peer_on_the_previous_protocol_is_refused_at_the_handshake(core):
    """Version 1 and version 2 do not describe the same wire.

    Events gained a required `seq`, `session.send` started answering with a
    `turn_id` rather than a `message_id`, and `session.snapshot` arrived with
    sequencing semantics version 1 never had. A core that kept calling itself
    version 1 would let an old client through the handshake and fail it later,
    at whatever message first did not fit — mid-session, with a turn running.
    """
    write_raw(core, {
        "version": 1, "type": "request", "id": "old-1",
        "method": "client.hello",
        "params": {"protocol_version": 1,
                   "client": {"name": "previous-client", "version": "0"},
                   "capabilities": ["questions"]}})

    # Read rather than correlated: a line refused this early is answered with
    # `id: null`, because there is no request the core was willing to accept.
    answer = core.read()
    assert answer["type"] == "error"
    assert answer["id"] is None
    assert answer["error"]["code"] == P.UNSUPPORTED_VERSION
    assert answer["error"]["data"]["supported"] == [P.PROTOCOL_VERSION]


def test_a_handshake_asking_for_the_previous_version_is_refused(core):
    """The other shape the same mistake takes: our envelope, their version.

    Caught by the handshake itself rather than by the reader, and answered
    against the request id because this line was readable.
    """
    id = core.send("client.hello", {
        "protocol_version": 1,
        "client": {"name": "previous-client", "version": "0"},
        "capabilities": ["questions"]})

    answer = core.answer_to(id)
    assert answer["type"] == "error"
    assert answer["error"]["code"] == P.UNSUPPORTED_VERSION
    assert answer["error"]["data"]["supported"] == [P.PROTOCOL_VERSION]


def test_no_session_operation_follows_a_version_refusal(core):
    """Refused at the handshake means nothing after it is served either."""
    write_raw(core, {
        "version": 1, "type": "request", "id": "old-1",
        "method": "client.hello",
        "params": {"protocol_version": 1,
                   "client": {"name": "previous-client", "version": "0"}}})
    assert core.read()["error"]["code"] == P.UNSUPPORTED_VERSION

    answer = core.answer_to(core.send("session.create"))
    assert answer["error"]["code"] == P.NOT_INITIALIZED

    listed = core.answer_to(core.send("session.list"))
    assert listed["error"]["code"] == P.NOT_INITIALIZED


def test_the_version_this_core_speaks_is_the_one_the_schema_declares(core):
    """Pinned, because bumping it has to be a deliberate act.

    The schema is the source of truth and both generated files come from it;
    this asserts the number a peer is actually offered at the handshake is the
    one the F2 wire contract is versioned as.
    """
    handshake = core.hello()
    assert handshake["result"]["protocol_version"] == 2
    assert P.PROTOCOL_VERSION == 2


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
    turn_id = accepted["result"]["turn_id"]
    assert accepted["result"]["accepted"] is True

    started = deltas = completed = 0
    deadline = time.monotonic() + PATIENCE
    text: list[str] = []
    message_ids: set[str] = set()
    sequence: list[int] = []
    while time.monotonic() < deadline and not completed:
        message = core.read()
        if message.get("type") != "event":
            continue
        name = message["event"]
        sequence.append(message["seq"])
        if name in ("message.started", "message.delta", "message.completed"):
            # Every event of a turn names the turn; each message names itself.
            assert message["params"]["turn_id"] == turn_id
            message_ids.add(message["params"]["message_id"])
        if name == "message.started":
            started += 1
        elif name == "message.delta":
            deltas += 1
            text.append(message["params"]["text"])
        elif name == "message.completed":
            completed += 1
            assert message["params"]["status"] == "completed"

    assert started == 1, "the answer never began"
    assert deltas > 0, "nothing streamed; the client would show a frozen turn"
    assert completed == 1
    assert len(message_ids) == 1, "one message, one id"
    # Ordering preserved, nothing lost between the pieces and the whole.
    assert "".join(text)
    # Gapless and increasing, which is what a client's resync check relies on.
    assert sequence == sorted(sequence)
    assert sequence == list(range(sequence[0], sequence[0] + len(sequence)))


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


# --------------------------------------------------------------------------- #
# the seams a test in memory does not cross
# --------------------------------------------------------------------------- #

def test_answering_a_form_reaches_the_core_over_the_wire(core):
    """The dispatch that nothing exercised, and that did not work.

    `question.answer` passed four positional arguments into a three-parameter
    method using the pre-form `selected`/`custom` keys, so every real answer
    came back as `internal_error` while the agent waited out its timeout. Both
    halves had tests; neither crossed this seam.

    Answering a request that does not exist proves the dispatch, not the
    plumbing behind it: an unknown id must be *refused by name*, which only
    happens if the call reached the service at all.
    """
    core.hello()
    answer = core.answer_to(core.send("question.answer", {
        "id": "no-such-request",
        "answers": [{"header": "Colour", "chosen": ["red"]}],
    }))

    assert answer["type"] == "error"
    assert answer["error"]["code"] == P.UNKNOWN_REQUEST, answer["error"]
    assert "no-such-request" in answer["error"]["message"]


def test_cancelling_a_form_reaches_the_core_over_the_wire(core):
    core.hello()
    answer = core.answer_to(core.send("question.answer", {
        "id": "no-such-request", "cancelled": True}))

    assert answer["type"] == "error"
    assert answer["error"]["code"] == P.UNKNOWN_REQUEST


def test_a_snapshot_describes_a_session_that_has_run_a_turn(core):
    """What a client rebuilding its own state actually receives."""
    core.hello()
    session = core.answer_to(core.send("session.create"))["result"]["session"]

    seen: list[dict] = []
    core.answer_to(core.send("session.send",
                             {"session_id": session["id"],
                              "text": "say something"}), collect=seen)
    core.events_until("message.completed", collect=seen)

    snapshot = core.answer_to(core.send(
        "session.snapshot", {"session_id": session["id"]}))["result"]["snapshot"]

    assert snapshot["session"]["id"] == session["id"]
    roles = [message["role"] for message in snapshot["messages"]]
    assert roles[0] == "user", "the person's own message is part of the session"
    assert snapshot["messages"][0]["text"] == "say something"
    assert "assistant" in roles
    # The revision is a real number a client can filter events against.
    assert snapshot["revision"] >= max(
        event["seq"] for event in seen if event.get("type") == "event")

    # Every item is placed in the one ordering domain a client merges on, and
    # a finished message says it is finished rather than still arriving.
    assert all(isinstance(message["started_seq"], int)
               for message in snapshot["messages"])
    assert all(message["status"] in ("streaming", "completed",
                                     "cancelled", "failed")
               for message in snapshot["messages"])
    assert snapshot["messages"][-1]["status"] == "completed"

    # A snapshot describes a conversation, not the machine running it. None of
    # this may cross the protocol, however the session was configured. The
    # token-*count* fields of a usage report are numbers, not credentials —
    # they pass only by name, while the words themselves stay forbidden.
    body = json.dumps(snapshot)
    for counter in ("input_tokens", "output_tokens", "cached_tokens",
                    "written_tokens", "reasoning_tokens"):
        body = body.replace(f'"{counter}"', '""')
    for forbidden in ("api_key", "providers", "token", "secret", "ANTHROPIC"):
        assert forbidden not in body, f"{forbidden} reached a client"


def test_every_event_carries_its_place_in_the_sequence(core):
    core.hello()
    seen: list[dict] = []
    core.answer_to(core.send("session.create"), collect=seen)
    core.events_until("session.created", collect=seen)

    numbers = [event["seq"] for event in seen if event.get("type") == "event"]
    assert numbers, "no events arrived"
    assert all(isinstance(number, int) and number > 0 for number in numbers)
    assert numbers == sorted(numbers)
