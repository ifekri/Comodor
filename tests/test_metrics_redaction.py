"""The paired record holds counts, never content (T061–T064; FR-055, FR-072,
FR-073, FR-074, FR-051).

Per turn: input, output and cached tokens apart, from the provider's own
figures, with the estimator filling in only their absence. Per task: the
counts FR-072 names. And nothing else — no prompt, no file content, no
credential — which is mutation-checked by making `as_dict` leak and
watching the guard catch it.
"""

from __future__ import annotations

import json

import pytest

from comodor.agent import AgentLoop, Conversation
from comodor.agent import tokens as tokens_module
from comodor.agent.tokens import TaskMeasurement
from comodor.events import Kind
from comodor.providers.base import ToolCall, Usage
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry

SECRET = "XIAOMI_API_KEY=sk-live-0123456789abcdef"
FORBIDDEN_KEYS = {"text", "prompt", "content", "message", "body", "key", "token",
                  "answer", "goal", "request"}


def make_agent(config, bus, scripts):
    gateway = Gateway(config, scripts=scripts)
    return AgentLoop(config, gateway, ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation())


# --------------------------------------------------------------------------- #
# T061 — three figures apart, provider first
# --------------------------------------------------------------------------- #


def test_provider_usage_is_the_truth_and_the_three_figures_stay_apart():
    measurement = TaskMeasurement()
    turn = measurement.record_turn(Usage(input_tokens=100, output_tokens=20,
                                         cached_tokens=900), context_estimate=5)
    assert (turn.input_tokens, turn.output_tokens, turn.cached_tokens) == (100, 20, 900)
    assert turn.context_size == 1000 and turn.estimated is False
    assert measurement.as_dict()["estimated_turns"] == 0


def test_the_estimator_fills_in_only_where_the_provider_reported_nothing():
    measurement = TaskMeasurement()
    turn = measurement.record_turn(Usage(), context_estimate=4321)
    assert turn.context_size == 4321 and turn.estimated is True
    assert measurement.as_dict()["estimated_turns"] == 1


def test_a_multi_turn_task_sums_per_turn_and_keeps_the_last_context_size(config, bus):
    agent = make_agent(config, bus, [
        Script(text="Looking.", tool_calls=[ToolCall(id="r", name="list_dir",
                                                     arguments={"path": "."})],
               usage=Usage(input_tokens=100, output_tokens=10, cached_tokens=0)),
        Script(text="Done.", usage=Usage(input_tokens=30, output_tokens=5, cached_tokens=120)),
    ])
    result = agent.run("look")
    record = result.measurement.as_dict()
    assert record["model_turns"] == 2 and record["tool_calls"] == 1
    figures = (record["input_tokens"], record["output_tokens"], record["cached_tokens"])
    assert figures == (130, 15, 120)
    assert record["context_size"] == 150
    assert record["outcome"] == "done"


# --------------------------------------------------------------------------- #
# T062 — the counts FR-072 names, from records the product already writes
# --------------------------------------------------------------------------- #


def test_every_field_fr_072_names_is_in_the_record():
    record = TaskMeasurement().as_dict()
    for name in ("input_tokens", "output_tokens", "cached_tokens", "context_size",
                 "model_turns", "tool_calls", "retries", "clarifications_raised",
                 "clarifications_answered", "corrections", "outcome",
                 "validation_outcome", "knowledge_hits", "knowledge_stale"):
        assert name in record, name


def test_clarifications_and_retries_are_counted_from_what_happened(config, bus):
    bus.subscribe(lambda e: e.payload["request"].answer(json.dumps(
        [{"header": "Database", "prompt": "", "chosen": ["SQLite"], "written": ""}]))
        if e.kind is Kind.REQUEST else None)
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[
            ToolCall(id="q", name="ask", arguments={"questions": [{
                "question": "Which database?", "header": "Database",
                "options": [{"label": "SQLite", "source": "request", "evidence": "SQLite"},
                            {"label": "PostgreSQL", "source": "request",
                             "evidence": "PostgreSQL"}]}]}),
            ToolCall(id="r", name="read_file", arguments={"path": "missing.py"})]),
        Script(text="Done."),
    ])
    result = agent.run("SQLite or PostgreSQL?")
    record = result.measurement.as_dict()
    assert record["clarifications_raised"] == 1
    assert record["clarifications_answered"] == 1
    assert record["retries"] == 1                    # the failed read
    assert record["tool_calls"] == 2


def test_the_episode_and_the_insights_carry_the_record(config, bus):
    from comodor.insights import collect
    from comodor.learning import LearningEngine

    config.learning.enabled = True
    config.learning.reflect = False
    config.learning.review = False
    engine = LearningEngine(config, bus)
    try:
        agent = AgentLoop(config, Gateway(config, scripts=[
            Script(text="ok", usage=Usage(input_tokens=50, output_tokens=5, cached_tokens=200))]),
            ToolRegistry(), bus, PermissionEngine(config, bus), Conversation(),
            memory=engine)
        agent.run("hello")
        episode = engine.store.episodes(limit=1)[0]
        assert episode.measurement["cached_tokens"] == 200
        summary = collect(config, days=1)
        assert summary.measured_episodes == 1
        assert summary.task_cached_tokens == 200 and summary.model_turns == 1
    finally:
        engine.close()


# --------------------------------------------------------------------------- #
# T063 — context size at the funnel, no second pass
# --------------------------------------------------------------------------- #


def test_the_gauge_and_the_request_agree(config, bus):
    seen = []
    bus.subscribe(lambda e: seen.append(e.get("context_used")) if e.kind is Kind.USAGE else None)
    agent = make_agent(config, bus, [Script(text="ok", usage=Usage())])
    agent.run("hello")
    assert seen and seen[-1] == agent.conversation.last_request_tokens
    assert agent.conversation.last_request_tokens > 0


def test_render_counts_once_where_it_assembles():
    calls = []
    conversation = Conversation()
    real = conversation.counter.count

    def counting(messages, tools=None):
        calls.append(len(messages))
        return real(messages, tools)

    conversation.counter.count = counting                     # type: ignore[assignment]
    from comodor.providers.base import Message

    conversation.add(Message.user("hi"))
    conversation.render("HEAD")
    assert calls == [2]
    assert conversation.last_request_tokens == real([Message.system("HEAD"),
                                                     conversation.messages[0]], None)


# --------------------------------------------------------------------------- #
# T064 — nothing sensitive, mutation-checked
# --------------------------------------------------------------------------- #


def _assert_counts_only(record):
    assert set(record) & FORBIDDEN_KEYS == set()
    for key, value in record.items():
        assert isinstance(value, (int, float, bool, str)), key
        if isinstance(value, str):
            assert " " not in value and len(value) <= 32, (key, value)
    serialised = json.dumps(record)
    assert "sk-live" not in serialised and "XIAOMI" not in serialised


def test_the_record_of_a_turn_that_read_a_secret_holds_counts_only(config, bus):
    (config.paths.project / ".env").write_text(SECRET + "\n", encoding="utf-8")
    agent = make_agent(config, bus, [
        Script(text="Reading.", tool_calls=[ToolCall(id="r", name="read_file",
                                                     arguments={"path": ".env"})]),
        Script(text=f"The key is {SECRET}"),
    ])
    result = agent.run(f"read .env and tell me the key {SECRET}")
    _assert_counts_only(result.measurement.as_dict())


def test_the_guard_catches_a_record_that_leaks(monkeypatch):
    """Mutation check: make `as_dict` carry the prompt and the guard fails."""
    real = TaskMeasurement.as_dict

    def leaking(self):
        record = real(self)
        record["prompt"] = "read .env and tell me the key " + SECRET
        return record

    monkeypatch.setattr(TaskMeasurement, "as_dict", leaking)
    with pytest.raises(AssertionError):
        _assert_counts_only(TaskMeasurement().as_dict())
    monkeypatch.setattr(TaskMeasurement, "as_dict", real)
    _assert_counts_only(TaskMeasurement().as_dict())


def test_the_module_defines_no_field_that_could_hold_content():
    import dataclasses

    for cls in (tokens_module.TurnRecord, tokens_module.TaskMeasurement):
        for field in dataclasses.fields(cls):
            assert field.name not in FORBIDDEN_KEYS, field.name


def test_cache_creation_tokens_are_measured():
    """A cache-creation token is part of the prompt and of the task total."""
    from comodor.agent.tokens import TaskMeasurement
    from comodor.providers.base import Usage

    measurement = TaskMeasurement()
    measurement.record_turn(Usage(input_tokens=10, output_tokens=5,
                                  cached_tokens=20, written_tokens=7, cost_usd=0.0))

    assert measurement.written_tokens == 7
    assert measurement.as_dict()["written_tokens"] == 7
    assert measurement.as_dict()["input_tokens"] == 10
    assert measurement.as_dict()["cached_tokens"] == 20
