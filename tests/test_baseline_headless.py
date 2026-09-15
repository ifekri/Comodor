"""Characterization: what a headless run does with a form today (T009).

`comodor run` has nobody to fill in a form. Today it answers every question
itself with `cancelled` the moment it is raised, the tool tells the model to
choose sensible defaults, and the run reports `stopped: "done"` and `ok: true`
— a task completed by guessing looks identical to one completed by knowing.

That is the documented starting point for the one intended behaviour change
in spec 002 (FR-033, FR-082, FR-121): after it, such a run ends in
`clarification_required`. This file records the behaviour being removed,
before it is removed.
"""

from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout

import pytest

from comodor import cli
from comodor.config import ProviderConfig, load
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway


@pytest.fixture
def scripted(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "work"
    project.mkdir(parents=True)
    monkeypatch.setenv("COMODOR_HOME", str(home))

    def build(scripts):
        config = load(cwd=project, use_environment=False)
        config.providers["fake"] = ProviderConfig(
            name="fake", kind="fake", base_url="offline", api_key="demo",
            model="scripted", configured=True)
        config.provider = "fake"
        config.learning.enabled = False

        def make(configuration, scripts=None):
            gateway = Gateway(configuration, scripts=list(build.plan))
            build.providers.append(gateway.provider("fake"))
            return gateway

        monkeypatch.setattr("comodor.providers.gateway.Gateway", make)
        build.plan = scripts
        return config

    build.plan = []
    build.providers = []
    return build


def a_question():
    return ToolCall(id="call-1", name="ask", arguments={"questions": [{
        "question": "Which framework?", "header": "Framework",
        "options": [{"label": "Flask"}, {"label": "Django"}],
    }]})


def run_json(config):
    args = argparse.Namespace(task="build me something", yes=True, json=True,
                              max_steps=3)
    out = io.StringIO()
    with redirect_stdout(out):
        code = cli.run_headless(config, args)
    return code, json.loads(out.getvalue())


def test_a_headless_form_ends_the_run_unattended_instead_of_carrying_on(scripted):
    """Before spec 002 the form was answered `cancelled` at once, the tool
    told the model to choose sensible defaults, and the run reported `done`
    with `ok: true`. That is the behaviour FR-082 removes; this is what
    replaces it (FR-033, FR-121)."""
    config = scripted([
        Script(text="One thing first.", tool_calls=[a_question()]),
        Script(text="Flask it is — I picked it for you."),
    ])

    code, report = run_json(config)

    assert code != 0
    assert report["ok"] is False
    assert report["stopped"] == "clarification_required"
    assert report["tools"] == ["ask"]
    assert "Flask it is" not in report["text"]

    replies = [message.content for call in scripted.providers[0].calls
               for message in call]
    assert not any("sensible defaults" in reply.lower() for reply in replies)


def test_today_the_json_report_has_exactly_these_fields(scripted):
    """The shape a caller reads now; additions later must be additive."""
    config = scripted([Script(text="Hello.")])
    _, report = run_json(config)
    assert {"text", "ok", "stopped", "steps", "tool_calls",
            "tools", "error", "usage", "elapsed"} <= set(report)
    # Two additions since: `usage.cached_tokens` (T015) and the paired
    # `measurement` record (T061); nothing a pre-change caller read moved.
    assert set(report) == {"text", "ok", "stopped", "steps", "tool_calls",
                           "tools", "error", "usage", "elapsed", "measurement"}
    # `cached_tokens` is the one addition Phase 1 makes (T015 needs it for the
    # paired baseline); everything a pre-change caller read is still there.
    assert {"input_tokens", "output_tokens", "cost_usd"} <= set(report["usage"])
    assert set(report["usage"]) == {"input_tokens", "output_tokens",
                                    "cached_tokens", "cost_usd"}


def test_today_stopped_takes_only_the_loops_own_values(scripted):
    from comodor.agent.loop import TurnResult

    assert TurnResult().stopped == "done"
    assert TurnResult(stopped="max_steps").ok is True
    for value in ("budget", "cancelled", "error"):
        assert TurnResult(stopped=value).ok is False


def test_today_a_failed_turn_exits_one_and_a_completed_one_zero(scripted):
    config = scripted([Script(text="", error="provider down")])
    code, report = run_json(config)
    assert code == 1
    assert report["stopped"] == "error" and report["ok"] is False
