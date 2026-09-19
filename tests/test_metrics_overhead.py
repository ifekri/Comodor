"""Instrumentation costs next to nothing (T066; SC-022).

Recording the paired record adds no model call and stays off the critical
path. Measured alone, under the `performance` marker, with a budget loose
enough that a busy machine cannot fail an honest build and tight enough that
a record that re-rendered the payload or called a model would.
"""

from __future__ import annotations

import time

import pytest

from comodor.agent import AgentLoop, Conversation
from comodor.agent.tokens import TaskMeasurement
from comodor.providers.base import Message, Usage
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry

pytestmark = pytest.mark.performance

#: Recording ten thousand turns. A record is a handful of integer adds; a
#: millisecond per record would already be a hundred times too slow.
RECORD_BUDGET_SECONDS = 0.5

#: A full scripted turn, end to end, with and without the record wired.
#: The difference is what instrumentation costs; the scripted turn itself
#: is dominated by the loop's own work.
TURN_OVERHEAD_SHARE = 0.25


def test_recording_ten_thousand_turns_is_cheap():
    measurement = TaskMeasurement()
    usage = Usage(input_tokens=1000, output_tokens=100, cached_tokens=5000)
    started = time.perf_counter()
    for _ in range(10_000):
        measurement.record_turn(usage, context_estimate=6000)
    measurement.as_dict()
    elapsed = time.perf_counter() - started
    assert elapsed < RECORD_BUDGET_SECONDS, f"{elapsed:.3f}s"
    assert measurement.model_turns == 10_000


def test_no_model_call_is_added_by_measurement(config, bus):
    gateway = Gateway(config, scripts=[Script(text="ok")])
    agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation())
    for _ in range(5):
        agent.run("hello")
    calls = gateway.provider("fake").calls
    assert len(calls) == 5, "one model call per turn, and none for the record"


def test_the_record_stays_off_the_critical_path(config, bus):
    """Ten scripted turns with the record versus ten with a no-op record."""
    def run(turns):
        gateway = Gateway(config, scripts=[Script(text="ok")])
        agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                          PermissionEngine(config, bus), Conversation())
        started = time.perf_counter()
        for _ in range(turns):
            agent.run("hello")
        return time.perf_counter() - started

    class Silent(TaskMeasurement):
        def record_turn(self, usage, context_estimate=0):
            return None

    baseline = run(10)
    import comodor.agent.loop as loop_module

    real = loop_module.TaskMeasurement
    loop_module.TaskMeasurement = Silent
    try:
        silent = run(10)
    finally:
        loop_module.TaskMeasurement = real
    # The measured run may not be slower than the silent one by more than
    # the share above, with a floor so a sub-millisecond difference on a
    # fast machine is not a failure.
    assert baseline <= silent * (1 + TURN_OVERHEAD_SHARE) + 0.05, (baseline, silent)


def test_render_is_still_one_pass_over_the_history():
    conversation = Conversation()
    for index in range(2000):
        conversation.add(Message.user(f"message {index} " * 20))
    started = time.perf_counter()
    conversation.render("HEAD")
    elapsed = time.perf_counter() - started
    assert elapsed < 0.5, f"{elapsed:.3f}s for one render of 2000 messages"
