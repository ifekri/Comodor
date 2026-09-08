"""What the protocol costs, measured rather than asserted.

Marked `performance` so it runs alone, like the rest of the timing suite. The
thresholds are deliberately loose — an order of magnitude above what the
machine here does — because a benchmark that fails on a loaded CI runner is a
benchmark people learn to ignore. What they catch is a regression that changes
the shape of the cost, not a slow afternoon.

The actual numbers from a run are printed, so a person reading CI output sees
what it did rather than only that it passed.
"""

from __future__ import annotations

import io
import json
import statistics
import time

import pytest

from comodor import protocol as P
from comodor.application import CoreService
from comodor.transport.jsonl import Channel
from comodor.transport.server import Server

pytestmark = pytest.mark.performance


def _serve(service: CoreService, lines: list[dict]) -> tuple[list[dict], float]:
    text = "\n".join(json.dumps(line) for line in lines)
    out = io.StringIO()
    channel = Channel(reader=io.StringIO(text + "\n"), writer=out,
                      log=io.StringIO())
    server = Server(service, channel)
    started = time.perf_counter()
    server.serve()
    elapsed = time.perf_counter() - started
    return [json.loads(row) for row in out.getvalue().splitlines()], elapsed


def _hello() -> dict:
    return P.request("h", "client.hello", {
        "protocol_version": P.PROTOCOL_VERSION,
        "client": {"name": "bench", "version": "0"}})


def test_encoding_and_decoding_one_message_is_cheap():
    message = P.event("message.delta", {
        "session_id": "s" * 12, "message_id": "m" * 12,
        "text": "a moderately sized chunk of an answer, as one delta"})

    rounds = 20_000
    started = time.perf_counter()
    for _ in range(rounds):
        P.decode(json.dumps(message))
    each = (time.perf_counter() - started) / rounds

    print(f"\nencode+decode: {each * 1e6:.1f} µs per message")
    # A streamed answer is thousands of these. At a microsecond each the
    # protocol is not the thing anybody waits for; at a millisecond it is.
    assert each < 200e-6


def test_a_trivial_request_is_answered_in_well_under_a_millisecond(config):
    service = CoreService(config)
    try:
        calls = [_hello()] + [
            P.request(str(n), "workspace.get", {}) for n in range(200)]
        answers, elapsed = _serve(service, calls)

        assert len(answers) == 201
        each = elapsed / 200
        print(f"\ntrivial round trip: {each * 1e3:.3f} ms mean "
              f"({elapsed * 1e3:.1f} ms for 200)")
        assert each < 5e-3
    finally:
        service.close()


def test_the_spread_of_a_trivial_request_is_reported(config):
    service = CoreService(config)
    try:
        samples: list[float] = []
        for _ in range(30):
            _, elapsed = _serve(service, [_hello(), P.request("1", "model.get", {})])
            samples.append(elapsed)
        samples.sort()
        p50 = statistics.median(samples)
        p95 = samples[int(len(samples) * 0.95) - 1]
        print(f"\nhandshake + one call: p50 {p50 * 1e3:.2f} ms, "
              f"p95 {p95 * 1e3:.2f} ms")
        assert p95 < 50e-3
    finally:
        service.close()


def test_changing_mode_is_a_state_change_not_a_rebuild(config):
    service = CoreService(config)
    try:
        session = service.create_session()["id"]
        samples: list[float] = []
        for index in range(50):
            mode = ("act", "plan", "ask")[index % 3]
            started = time.perf_counter()
            service.set_mode(session, mode)
            samples.append(time.perf_counter() - started)
        each = statistics.median(samples)
        print(f"\nmode switch: {each * 1e6:.1f} µs median")
        # It writes one field and emits two events. Anything near a
        # millisecond would mean something is being rebuilt per switch.
        assert each < 5e-3
    finally:
        service.close()


def test_a_long_stream_of_events_keeps_its_order_and_its_pace(config):
    """Ten thousand deltas, in order, with nothing dropped."""
    service = CoreService(config)
    seen: list[str] = []
    service.on_event = lambda _s, name, params: (
        seen.append(str(params.get("text", ""))) if name == "message.delta"
        else None)
    try:
        handle_id = service.create_session()["id"]
        handle = service.session(handle_id)
        from comodor.events import Kind

        started = time.perf_counter()
        for index in range(10_000):
            handle.assembly.bus.emit(Kind.ASSISTANT_DELTA, text=str(index))
        elapsed = time.perf_counter() - started

        assert len(seen) == 10_000, "an event was dropped"
        assert seen == [str(index) for index in range(10_000)], "out of order"
        print(f"\n10,000 deltas relayed: {elapsed * 1e3:.1f} ms "
              f"({elapsed / 10_000 * 1e6:.1f} µs each)")
        assert elapsed < 5.0
    finally:
        service.close()


def test_validation_does_not_dominate_a_call():
    payload = {"session_id": "s" * 12, "text": "hello" * 20}
    rounds = 50_000
    started = time.perf_counter()
    for _ in range(rounds):
        P.validate("SessionSendParams", payload)
    each = (time.perf_counter() - started) / rounds

    print(f"\nvalidate: {each * 1e6:.2f} µs per call")
    assert each < 50e-6
