"""Correlation, lifecycle and resynchronisation, against a real core service.

The scripted `fake` provider and purpose-built tools, so every one of these is
deterministic: no network, no model, no spend, and no sleeps. Where two things
have to happen in a particular order relative to each other, a `threading`
primitive says so — a test that passes because of a timer is a test that fails
on somebody else's machine, and this suite already learned that once.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from comodor.agent import AgentLoop, Conversation
from comodor.application import Assembly, CoreService
from comodor.events import EventBus
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.providers.profile import Profile
from comodor.safety import PermissionEngine, Risk
from comodor.tools import Tool, ToolContext, ToolRegistry, ToolResult

PATIENCE = 15.0


# --------------------------------------------------------------------------- #
# harness
# --------------------------------------------------------------------------- #

class Recorder:
    """Every protocol event a session produced, with its sequence number."""

    def __init__(self) -> None:
        self.events: list[tuple[int, str, dict[str, Any]]] = []
        self._lock = threading.Lock()
        self._arrived = threading.Event()

    def __call__(self, _session: str, name: str, params: dict[str, Any],
                 seq: int) -> None:
        with self._lock:
            self.events.append((seq, name, dict(params)))
        self._arrived.set()

    def named(self, name: str) -> list[dict[str, Any]]:
        with self._lock:
            return [params for _, event, params in self.events if event == name]

    def names(self) -> list[str]:
        with self._lock:
            return [name for _, name, _ in self.events]

    def sequence(self) -> list[int]:
        with self._lock:
            return [seq for seq, _, _ in self.events]


def service_for(config, scripts, extra_tools: list[Tool] | None = None,
                recorder: Recorder | None = None,
                parallel: bool = False) -> tuple[CoreService, Recorder]:
    """A `CoreService` whose sessions run scripted answers and given tools.

    `parallel` grants the scripted model the capability the real catalogue
    would: `profile.of` only claims parallel tool calls for a model it has
    heard of, and `fake-1` is in no catalogue. Without it a batch runs one
    call after another, which is a fine default and useless for proving that
    concurrent output stays apart.
    """
    recorder = recorder or Recorder()

    def build(built_config, *, bus=None, plugins=None,
              delegates=False) -> Assembly:
        # `delegates` is accepted and ignored: this assembly is a scripted
        # minimum, with no spawner a delegate manager could run on. A session
        # built here therefore has no background delegates, which is the same
        # "nowhere to deliver" wiring the real assemble produces by default.
        bus = bus or EventBus()
        tools = ToolRegistry(config=built_config)
        for tool in extra_tools or ():
            tools.add(tool)
        agent = AgentLoop(built_config, Gateway(built_config, scripts=scripts),
                          tools, bus, PermissionEngine(built_config, bus),
                          Conversation())
        if parallel:
            agent._profile = Profile(model="fake-1", context=100_000,
                                     source="configured", parallel_tools=True)
        return Assembly(config=built_config, bus=bus, gateway=None, memory=None,
                        permissions=None, skills=None, mcp=None, tools=tools,
                        agent=agent)

    config.safety.auto_approve_safe = True
    return CoreService(config, assemble_with=build, on_event=recorder), recorder


def run_turn(service: CoreService, session_id: str, text: str) -> dict[str, Any]:
    """Send, release the turn barrier, and wait for the session to go idle."""
    accepted = service.send(session_id, text)
    service.release()
    settled(service, session_id)
    return accepted


def settled(service: CoreService, session_id: str) -> None:
    handle = service.session(session_id)
    worker = handle._worker
    if worker is not None:
        worker.join(timeout=PATIENCE)
    assert not handle.busy, "the turn never finished"


# --------------------------------------------------------------------------- #
# tools built for these tests
# --------------------------------------------------------------------------- #

class Streamer(Tool):
    """Emits the lines it is given, waiting on a gate between each.

    The gates are what make interleaving a fact rather than a hope. Two of
    these, wired so that A must publish its first line before B publishes its
    first and B before A's second, produce output in the order `A1 B1 A2 B2`
    every time and on every machine.
    """

    risk = Risk.SAFE
    description = "emits lines for a test"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, name: str, lines: list[str],
                 before: list[threading.Event] | None = None,
                 after: list[threading.Event] | None = None) -> None:
        self.name = name
        self.lines = lines
        self.before = before or []
        self.after = after or []

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        for index, line in enumerate(self.lines):
            if index < len(self.before):
                assert self.before[index].wait(PATIENCE), f"{self.name} waited out"
            ctx.progress(line)
            if index < len(self.after):
                self.after[index].set()
        return ToolResult.success(content=f"{self.name} done")


class Boom(Tool):
    name = "boom"
    risk = Risk.SAFE
    description = "fails on purpose"
    parameters = {"type": "object", "properties": {}}

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        return ToolResult.failure("it went wrong")


# --------------------------------------------------------------------------- #
# a turn is not a message
# --------------------------------------------------------------------------- #

def test_each_assistant_message_in_a_turn_has_its_own_id(config):
    """The defect this phase started from.

    A turn that calls a tool produces two assistant messages. F1 labelled both
    with the turn's id, so the second `message.started` announced an id the
    client had already seen completed — and a client keying on it drew one
    message or two with the same key, depending on which way it guessed.
    """
    scripts = [
        Script(text="Looking.", tool_calls=[
            ToolCall(id="c1", name="list_dir", arguments={"path": "."})]),
        Script(text="Done."),
    ]
    service, seen = service_for(config, scripts)
    session = service.create_session()
    accepted = run_turn(service, session["id"], "look")

    starts = seen.named("message.started")
    assert len(starts) == 2, "a tool round trip is two assistant messages"
    ids = [start["message_id"] for start in starts]
    assert len(set(ids)) == 2, "each message needs its own id"
    assert all(start["turn_id"] == accepted["turn_id"] for start in starts)

    # And every delta names the message it belongs to, not merely the turn.
    for delta in seen.named("message.delta"):
        assert delta["message_id"] in ids
    service.close()


def test_a_delta_belongs_to_exactly_one_message(config):
    scripts = [
        Script(text="first", tool_calls=[
            ToolCall(id="c1", name="list_dir", arguments={"path": "."})]),
        Script(text="second"),
    ]
    service, seen = service_for(config, scripts)
    session = service.create_session()
    run_turn(service, session["id"], "go")

    joined: dict[str, str] = {}
    for delta in seen.named("message.delta"):
        joined[delta["message_id"]] = joined.get(delta["message_id"], "") \
            + delta["text"]
    assert sorted(joined.values()) == ["first", "second"]
    service.close()


# --------------------------------------------------------------------------- #
# tool output correlation — the one that cannot be done by heuristic
# --------------------------------------------------------------------------- #

def test_parallel_tools_do_not_mix_their_output(config):
    """`A1 B1 A2 B2` on the wire must still be A's lines and B's lines.

    This is the test the "most recent tool" heuristic fails. The gates force
    the two tools to interleave, so if output were attributed to whichever
    call started last, `alpha` would end up holding `B1` and `bravo` `A2`.
    """
    go = threading.Event()
    a1_done = threading.Event()
    b1_done = threading.Event()
    a2_done = threading.Event()
    b2_done = threading.Event()
    go.set()

    #        emits          waits for            then releases
    # alpha  A1, A2         go,      b1_done     a1_done, a2_done
    # bravo  B1, B2         a1_done, a2_done     b1_done, b2_done
    alpha = Streamer("alpha", ["A1", "A2"],
                     before=[go, b1_done], after=[a1_done, a2_done])
    bravo = Streamer("bravo", ["B1", "B2"],
                     before=[a1_done, a2_done], after=[b1_done, b2_done])

    scripts = [
        Script(text="Both.", tool_calls=[
            ToolCall(id="ca", name="alpha", arguments={}),
            ToolCall(id="cb", name="bravo", arguments={})]),
        Script(text="Finished."),
    ]
    service, seen = service_for(config, scripts, extra_tools=[alpha, bravo],
                                parallel=True)
    session = service.create_session()
    # Said out loud: without it the two tools run one after the other, the
    # gates never open, and this fails as a timeout rather than as a claim
    # about correlation.
    assert service.session(session["id"]).assembly.agent._can_parallelise(
        scripts[0].tool_calls), "these tools must actually run at once"
    run_turn(service, session["id"], "run both")

    output = seen.named("tool.output")
    order = [chunk["text"] for chunk in output]
    assert order == ["A1", "B1", "A2", "B2"], f"the gates did not interleave: {order}"

    by_call: dict[str, list[str]] = {}
    for chunk in output:
        by_call.setdefault(chunk["call_id"], []).append(chunk["text"])
    assert by_call == {"ca": ["A1", "A2"], "cb": ["B1", "B2"]}
    service.close()


def test_tool_output_carries_the_call_it_came_from(config):
    quiet = Streamer("quiet", ["one", "two"])
    scripts = [
        Script(text="Streaming.", tool_calls=[
            ToolCall(id="only", name="quiet", arguments={})]),
        Script(text="Done."),
    ]
    service, seen = service_for(config, scripts, extra_tools=[quiet])
    session = service.create_session()
    run_turn(service, session["id"], "stream")

    chunks = seen.named("tool.output")
    assert [chunk["text"] for chunk in chunks] == ["one", "two"]
    assert {chunk["call_id"] for chunk in chunks} == {"only"}
    service.close()


def test_a_failing_tool_reports_failed_not_completed(config):
    scripts = [
        Script(text="Trying.", tool_calls=[
            ToolCall(id="c1", name="boom", arguments={})]),
        Script(text="Oh well."),
    ]
    service, seen = service_for(config, scripts, extra_tools=[Boom()])
    session = service.create_session()
    run_turn(service, session["id"], "break it")

    failed = seen.named("tool.failed")
    assert len(failed) == 1
    assert failed[0]["call_id"] == "c1"
    assert "went wrong" in failed[0]["error"]
    assert not seen.named("tool.completed")
    service.close()


# --------------------------------------------------------------------------- #
# how a message ends
# --------------------------------------------------------------------------- #

def test_a_completed_message_says_so(config):
    service, seen = service_for(config, [Script(text="Hello.")])
    session = service.create_session()
    run_turn(service, session["id"], "hi")

    done = seen.named("message.completed")
    assert len(done) == 1
    assert done[0]["status"] == "completed"
    assert done[0]["text"] == "Hello."
    service.close()


def test_a_provider_failure_ends_the_message_rather_than_leaving_it_open(config):
    """Otherwise the client shows an answer that streams for ever.

    `_stream_once` raises before it can emit the end of the message, so
    nothing else in the turn will ever complete it. A notification alone tells
    the person something broke and leaves the spinner running.
    """
    service, seen = service_for(config, [Script(error="the provider fell over")])
    session = service.create_session()
    run_turn(service, session["id"], "hi")

    done = seen.named("message.completed")
    assert len(done) == 1, "the open message was never closed"
    assert done[0]["status"] == "failed"
    assert done[0]["error"]
    assert seen.named("notification.created"), "and the person is told why"
    service.close()


def test_an_error_with_no_open_message_completes_nothing(config):
    """A failure before the first message must not invent one to fail."""
    service, seen = service_for(config, [Script(text="fine")])
    session = service.create_session()
    handle = service.session(session["id"])
    from comodor.events import Kind

    handle.assembly.bus.emit(Kind.ERROR, text="something, but not a turn")
    assert not seen.named("message.completed")
    assert seen.named("notification.created")
    service.close()


# --------------------------------------------------------------------------- #
# unicode
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("whole", [
    "Hello سلام 👋🏽 café é",
    "سلام دنیا — این یک آزمایش است",
    "é and é are different strings",
    "🇮🇷🇬🇧 flags are surrogate pairs",
])
def test_streamed_text_reconstructs_exactly(config, whole):
    """Every chunking of the same string must rebuild the same string."""
    service, seen = service_for(config, [Script(text=whole)])
    session = service.create_session()
    run_turn(service, session["id"], "say it")

    rebuilt = "".join(delta["text"] for delta in seen.named("message.delta"))
    assert rebuilt == whole
    assert seen.named("message.completed")[0]["text"] == whole
    service.close()


# --------------------------------------------------------------------------- #
# sequence numbers
# --------------------------------------------------------------------------- #

def test_events_are_numbered_from_one_without_gaps(config):
    scripts = [
        Script(text="Looking.", tool_calls=[
            ToolCall(id="c1", name="list_dir", arguments={"path": "."})]),
        Script(text="Done."),
    ]
    service, seen = service_for(config, scripts)
    session = service.create_session()
    run_turn(service, session["id"], "look")

    numbers = seen.sequence()
    assert numbers == list(range(1, len(numbers) + 1)), \
        "a hole here makes a client resynchronise over nothing"
    service.close()


def test_a_declined_capability_leaves_no_hole_in_the_sequence(config):
    """A client that cannot draw forms still gets a contiguous stream.

    The question is answered on its behalf and the request is never sent. If
    the number had been spent before the suppression, the client would see a
    gap and resynchronise for an event that was never meant for it.
    """
    scripts = [
        Script(text="Asking.", tool_calls=[
            ToolCall(id="c1", name="ask",
                     arguments={"questions": [
                         {"header": "Colour", "question": "Which colour?",
                          "options": [{"label": "red"}, {"label": "blue"}]}]})]),
        Script(text="Right."),
    ]
    service, seen = service_for(config, scripts)
    service.client_capabilities = ()          # announces neither
    session = service.create_session()
    run_turn(service, session["id"], "ask me")

    assert "question.requested" not in seen.names()
    numbers = seen.sequence()
    assert numbers == list(range(1, len(numbers) + 1))
    service.close()


# --------------------------------------------------------------------------- #
# the snapshot
# --------------------------------------------------------------------------- #

def test_a_snapshot_holds_the_conversation_and_the_tools(config):
    quiet = Streamer("quiet", ["line one", "line two"])
    scripts = [
        Script(text="Looking.", tool_calls=[
            ToolCall(id="c1", name="quiet", arguments={})]),
        Script(text="Done."),
    ]
    service, seen = service_for(config, scripts, extra_tools=[quiet])
    session = service.create_session()
    run_turn(service, session["id"], "have a look")

    snapshot = service.snapshot(session["id"])
    roles = [message["role"] for message in snapshot["messages"]]
    assert roles == ["user", "assistant", "assistant"]
    assert snapshot["messages"][0]["text"] == "have a look"
    assert [message["text"] for message in snapshot["messages"][1:]] \
        == ["Looking.", "Done."]
    assert all(message["status"] == "completed"
               for message in snapshot["messages"])

    assert len(snapshot["tools"]) == 1
    tool = snapshot["tools"][0]
    assert tool["call_id"] == "c1"
    assert tool["state"] == "completed"
    assert tool["output"] == "line oneline two"
    assert snapshot["revision"] == max(seen.sequence())
    service.close()


def test_a_snapshot_of_an_untouched_session_is_empty_but_valid(config):
    service, _ = service_for(config, [Script(text="hi")])
    session = service.create_session()

    snapshot = service.snapshot(session["id"])
    assert snapshot["messages"] == []
    assert snapshot["tools"] == []
    assert snapshot["session"]["id"] == session["id"]
    assert snapshot["revision"] >= 1        # session.created was an event
    service.close()


def test_a_snapshot_never_lands_between_an_event_and_its_number(config):
    """The race the revision exists for.

    A snapshot taken while a turn streams must describe a state that actually
    existed: everything it contains is at or below its revision, and nothing
    above its revision is in it. Taken repeatedly during a real streaming turn
    rather than argued about.
    """
    lines = [f"chunk-{index}" for index in range(40)]
    noisy = Streamer("noisy", lines)
    scripts = [
        Script(text="Streaming.", tool_calls=[
            ToolCall(id="c1", name="noisy", arguments={})]),
        Script(text="Done."),
    ]
    service, seen = service_for(config, scripts, extra_tools=[noisy])
    session = service.create_session()

    taken: list[dict[str, Any]] = []
    stop = threading.Event()

    def sample() -> None:
        while not stop.is_set():
            taken.append(service.snapshot(session["id"]))

    watcher = threading.Thread(target=sample, daemon=True)
    watcher.start()
    run_turn(service, session["id"], "make noise")
    stop.set()
    watcher.join(timeout=PATIENCE)

    assert taken, "no snapshot was taken during the turn"
    for snapshot in taken:
        held = "".join(tool.get("output", "") for tool in snapshot["tools"])
        # Whatever output the snapshot holds must be a prefix of the whole:
        # a snapshot that had skipped a chunk and kept a later one would not.
        assert "".join(lines).startswith(held), "a snapshot skipped a chunk"
    service.close()

def test_a_snapshot_keeps_a_turn_interleaved(config):
    """Answer, tool, answer, tool, answer — in that order, after a rebuild.

    A snapshot arrives as two lists. Numbering them in one domain is what lets
    a client merge them back into the turn that happened; without it every
    rebuilt session draws both answers and then both tools, which puts the
    closing summary above the work it summarises.
    """
    quiet = Streamer("quiet", ["one line"])
    scripts = [
        Script(text="Looking.", tool_calls=[
            ToolCall(id="c1", name="quiet", arguments={})]),
        Script(text="Editing.", tool_calls=[
            ToolCall(id="c2", name="quiet", arguments={})]),
        Script(text="Done."),
    ]
    service, _ = service_for(config, scripts, extra_tools=[quiet])
    session = service.create_session()
    run_turn(service, session["id"], "have a look")

    snapshot = service.snapshot(session["id"])
    items = sorted(
        [(message["started_seq"], f"message:{message['text'] or message['role']}")
         for message in snapshot["messages"]]
        + [(tool["started_seq"], f"tool:{tool['call_id']}")
           for tool in snapshot["tools"]],
        key=lambda item: item[0])

    assert [name for _, name in items] == [
        "message:have a look", "message:Looking.", "tool:c1",
        "message:Editing.", "tool:c2", "message:Done.",
    ]
    service.close()

def test_a_snapshot_numbers_items_with_the_events_that_started_them(config):
    """The number in a snapshot is the number that event was given on the wire.

    Checked end to end rather than only inside the journal, because the relay
    is what emits both: an item that stored the previous revision would look
    correct in isolation and put every message one event behind its own start.
    """
    quiet = Streamer("quiet", ["a line"])
    scripts = [
        Script(text="Looking.", tool_calls=[
            ToolCall(id="c1", name="quiet", arguments={})]),
        Script(text="Done."),
    ]
    service, seen = service_for(config, scripts, extra_tools=[quiet])
    session = service.create_session()
    run_turn(service, session["id"], "have a look")

    starts = {(name, str(params.get("message_id") or params.get("call_id"))): seq
              for seq, name, params in seen.events
              if name in ("message.started", "tool.started")}
    assert starts, "the turn produced no start events to check against"

    snapshot = service.snapshot(session["id"])
    for message in snapshot["messages"]:
        if message["role"] == "user":
            continue        # the prompt is a method call, not an event
        assert message["started_seq"] \
            == starts[("message.started", message["message_id"])]
    for tool in snapshot["tools"]:
        assert tool["started_seq"] == starts[("tool.started", tool["call_id"])]
    assert all(message["status"] == "completed"
               for message in snapshot["messages"]), "the turn had finished"
    service.close()


# --------------------------------------------------------------------------- #
# cancellation
# --------------------------------------------------------------------------- #

def test_cancelling_while_a_message_streams_marks_it_cancelled(config):
    """A stopped answer must not be left looking like one still arriving.

    Driven at the relay, because the point is precisely *where* the
    cancellation lands: with a message open and unfinished. A scripted
    provider streams faster than a test can interrupt it, and a test that
    raced it would be a test about timing.
    """
    from comodor.events import Kind

    service, seen = service_for(config, [Script(text="never sent")])
    session = service.create_session()
    bus = service.session(session["id"]).assembly.bus

    bus.emit(Kind.ASSISTANT_START, id="m1")
    bus.emit(Kind.ASSISTANT_DELTA, id="m1", text="half an ans")
    bus.emit(Kind.CANCELLED, reason="stop", id="m1")

    done = seen.named("message.completed")
    assert len(done) == 1
    assert done[0]["message_id"] == "m1"
    assert done[0]["status"] == "cancelled"
    # What had arrived is kept: a cancelled answer is still worth reading.
    assert done[0]["text"] == "half an ans"
    service.close()


def test_cancelling_during_a_tool_still_says_it_was_cancelled(config):
    """Where people actually press stop, and where F1 said nothing at all.

    The first message of the turn has genuinely completed by the time a tool
    is running, so there is no message to mark — and marking it would be a
    lie. Without a notice the turn simply goes quiet, which reads as a hang.
    """
    reached = threading.Event()
    release = threading.Event()

    class Blocker(Tool):
        name = "blocker"
        risk = Risk.SAFE
        description = "waits until it is cancelled"
        parameters = {"type": "object", "properties": {}}

        def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
            reached.set()
            release.wait(PATIENCE)
            return ToolResult.failure("stopped")

    scripts = [
        Script(text="Working.", tool_calls=[
            ToolCall(id="c1", name="blocker", arguments={})]),
        Script(text="unreachable"),
    ]
    service, seen = service_for(config, scripts, extra_tools=[Blocker()])
    session = service.create_session()
    service.send(session["id"], "do the slow thing")
    service.release()

    assert reached.wait(PATIENCE), "the tool never started"
    assert service.cancel(session["id"])["cancelled"] is True
    release.set()
    settled(service, session["id"])

    # The message that really did finish is not retroactively cancelled.
    assert [done["status"] for done in seen.named("message.completed")] \
        == ["completed"]
    # But the person is told the work stopped.
    notices = [notice["text"] for notice in seen.named("notification.created")]
    assert any("Stopped" in text for text in notices), notices
    # And the session converges: idle, and reported idle.
    assert not service.session(session["id"]).busy
    assert seen.named("session.updated")[-1]["session"]["busy"] is False
    service.close()


def test_cancelling_twice_is_safe(config):
    reached = threading.Event()
    release = threading.Event()

    class Blocker(Tool):
        name = "blocker"
        risk = Risk.SAFE
        description = "waits"
        parameters = {"type": "object", "properties": {}}

        def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
            reached.set()
            release.wait(PATIENCE)
            return ToolResult.failure("stopped")

    scripts = [
        Script(text="Working.", tool_calls=[
            ToolCall(id="c1", name="blocker", arguments={})]),
        Script(text="unreachable"),
    ]
    service, _ = service_for(config, scripts, extra_tools=[Blocker()])
    session = service.create_session()
    service.send(session["id"], "go")
    service.release()

    assert reached.wait(PATIENCE)
    assert service.cancel(session["id"])["cancelled"] is True
    assert service.cancel(session["id"])["cancelled"] is True
    release.set()
    settled(service, session["id"])
    assert service.cancel(session["id"])["cancelled"] is False
    service.close()


def test_cancelling_an_idle_session_is_a_no_op(config):
    service, _ = service_for(config, [Script(text="hi")])
    session = service.create_session()
    assert service.cancel(session["id"]) == {"cancelled": False}
    assert service.cancel(session["id"]) == {"cancelled": False}
    service.close()


def test_a_second_send_while_busy_is_refused_not_queued(config):
    from comodor.application import Refused

    started = threading.Event()
    release = threading.Event()

    class Blocker(Tool):
        name = "blocker"
        risk = Risk.SAFE
        description = "waits"
        parameters = {"type": "object", "properties": {}}

        def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
            started.set()
            release.wait(PATIENCE)
            return ToolResult.success(content="done")

    scripts = [
        Script(text="Working.", tool_calls=[
            ToolCall(id="c1", name="blocker", arguments={})]),
        Script(text="Finished."),
    ]
    service, _ = service_for(config, scripts, extra_tools=[Blocker()])
    session = service.create_session()
    service.send(session["id"], "first")
    service.release()
    assert started.wait(PATIENCE)

    with pytest.raises(Refused):
        service.send(session["id"], "second")

    release.set()
    settled(service, session["id"])
    service.close()


# --------------------------------------------------------------------------- #
# large output
# --------------------------------------------------------------------------- #

def test_a_snapshot_says_when_it_shortened_tool_output(config):
    """Capping is allowed; pretending it did not happen is not."""
    from comodor.application.journal import OUTPUT_CAP

    chunk = "x" * 1000
    noisy = Streamer("noisy", [chunk] * ((OUTPUT_CAP // 1000) + 5))
    scripts = [
        Script(text="Lots.", tool_calls=[
            ToolCall(id="c1", name="noisy", arguments={})]),
        Script(text="Done."),
    ]
    service, seen = service_for(config, scripts, extra_tools=[noisy])
    session = service.create_session()
    run_turn(service, session["id"], "flood")

    # Every chunk still went out live; only what is *kept* is bounded.
    assert len(seen.named("tool.output")) == (OUTPUT_CAP // 1000) + 5

    tool = service.snapshot(session["id"])["tools"][0]
    assert tool["output_truncated"] is True
    assert len(tool["output"]) <= OUTPUT_CAP
    service.close()


# --------------------------------------------------------------------------- #
# a rebuilt client converges on a continuously-connected one
# --------------------------------------------------------------------------- #

def test_a_snapshot_plus_later_events_equals_having_watched_it_all(config):
    """§96, in Python: state A watched everything; state B joined late.

    B takes a snapshot part-way through and then applies only the events above
    its revision. If the two do not agree at the end, either the snapshot
    missed something or it double-counted it.
    """
    halfway = threading.Event()
    carry_on = threading.Event()

    class Pauser(Tool):
        name = "pauser"
        risk = Risk.SAFE
        description = "stops in the middle"
        parameters = {"type": "object", "properties": {}}

        def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
            ctx.progress("before")
            halfway.set()
            carry_on.wait(PATIENCE)
            ctx.progress("after")
            return ToolResult.success(content="paused and resumed")

    scripts = [
        Script(text="Starting.", tool_calls=[
            ToolCall(id="c1", name="pauser", arguments={})]),
        Script(text="Finished."),
    ]
    service, seen = service_for(config, scripts, extra_tools=[Pauser()])
    session = service.create_session()
    service.send(session["id"], "go")
    service.release()

    assert halfway.wait(PATIENCE), "the tool never reached the middle"
    snapshot = service.snapshot(session["id"])
    taken_at = snapshot["revision"]

    carry_on.set()
    settled(service, session["id"])

    # B: the snapshot, then every event numbered above it.
    rebuilt_output = "".join(
        tool.get("output", "") for tool in snapshot["tools"])
    for seq, name, params in seen.events:
        if seq <= taken_at or name != "tool.output":
            continue
        rebuilt_output += params["text"]

    # A: everything, from the beginning.
    watched_output = "".join(
        params["text"] for _, name, params in seen.events
        if name == "tool.output")

    assert rebuilt_output == watched_output == "beforeafter"
    service.close()


# --------------------------------------------------------------------------- #
# a mode a tool changed, announced while the turn is still running
# --------------------------------------------------------------------------- #

def test_a_mode_a_tool_changed_is_announced_mid_turn(config):
    """Accepting a proposal is not the end of the turn, and must not look like it.

    `propose_mode` is a tool: the person accepts its card and the tool writes
    the session's mode itself, which never goes through `set_mode` and so never
    emitted `mode.changed`. A client caches the mode from events, so it kept
    drawing the old one for the rest of the turn — PLAN on the bar while the
    session ran under ACT and was allowed to write. Not a cosmetic lag: the bar
    is how somebody tells what the agent may do next.
    """
    from comodor.events import Kind
    from comodor.tools.propose_mode import ProposeMode

    config.agent.mode = "plan"
    scripts = [
        Script(text="Let me switch.", tool_calls=[ToolCall(
            id="c1", name="propose_mode",
            arguments={"target_mode": "act", "reason": "the plan is done"})]),
        Script(text="Now in act."),
    ]
    service, seen = service_for(config, scripts, extra_tools=[ProposeMode()])
    session = service.create_session()

    def accept(event) -> None:
        if event.kind is not Kind.REQUEST:
            return
        request = event.get("request")
        if request is not None and not request.answered:
            request.answer("act")

    unsubscribe = service.session(session["id"]).assembly.bus.subscribe(accept)
    try:
        run_turn(service, session["id"], "finish the plan")
    finally:
        unsubscribe()

    names = seen.names()
    assert "mode.changed" in names, \
        "the mode moved and no event said so"
    changed = seen.named("mode.changed")
    assert changed[-1]["mode"] == "act"
    assert service.get_session(session["id"])["mode"] == "act"

    # Announced where it happened, not folded into the turn's final update:
    # after the tool that changed it, and before the answer that follows.
    at_changed = names.index("mode.changed")
    at_tool = names.index("tool.completed")
    at_last_message = len(names) - 1 - names[::-1].index("message.completed")
    assert at_tool < at_changed < at_last_message, names
    service.close()
