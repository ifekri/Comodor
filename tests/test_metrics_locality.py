"""Measurements stay on this machine (T065; FR-075).

This feature introduces no outbound transmission: the record is written to
the local brain and printed on the local headless JSON, and nothing in the
modules it touched opens a socket. Checked two ways — the modules the
feature added or extended import nothing that speaks to a network, and a
turn that produces a full record makes no network call at all.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from comodor.agent import AgentLoop, Conversation
from comodor.events import EventBus
from comodor.providers.base import ToolCall, Usage
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry

SOURCE = Path(__file__).resolve().parents[1] / "src" / "comodor"

#: Modules this feature added or extended for measurement. None may reach out.
MEASUREMENT_MODULES = [
    "agent/tokens.py", "agent/evidence.py", "agent/context.py", "insights.py",
]
NETWORK_NAMES = ("socket", "urllib", "http.client", "httpx", "requests",
                 "aiohttp", "websocket", "smtplib", "ftplib")


@pytest.mark.parametrize("module", MEASUREMENT_MODULES)
def test_a_measurement_module_imports_nothing_that_speaks_to_a_network(module):
    text = (SOURCE / module).read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert not any(name in stripped for name in NETWORK_NAMES), (module, stripped)


def test_a_measured_turn_opens_no_socket(config, bus, monkeypatch):
    opened = []

    class Refusing(socket.socket):
        def __init__(self, *args, **kwargs):
            opened.append(args)
            raise AssertionError("a socket was opened during a measured turn")

    monkeypatch.setattr(socket, "socket", Refusing)
    agent = AgentLoop(config, Gateway(config, scripts=[
        Script(text="Looking.", tool_calls=[ToolCall(id="r", name="list_dir",
                                                     arguments={"path": "."})],
               usage=Usage(input_tokens=10, output_tokens=2)),
        Script(text="Done.", usage=Usage(input_tokens=12, output_tokens=2, cached_tokens=8)),
    ]), ToolRegistry(), bus, PermissionEngine(config, bus), Conversation())
    result = agent.run("look around")
    assert result.ok
    assert result.measurement.model_turns == 2
    assert opened == []


def test_the_record_is_written_locally_and_nowhere_else(config, tmp_path):
    from comodor.learning import LearningEngine

    config.learning.enabled = True
    config.learning.reflect = False
    config.learning.review = False
    bus = EventBus()
    engine = LearningEngine(config, bus)
    try:
        agent = AgentLoop(config, Gateway(config, scripts=[Script(text="ok")]),
                          ToolRegistry(), bus, PermissionEngine(config, bus),
                          Conversation(), memory=engine)
        agent.run("hello")
        assert engine.store.episodes(limit=1)[0].measurement["model_turns"] == 1
        assert config.paths.brain_db.exists()
        assert str(config.paths.brain_db).startswith(str(tmp_path))
    finally:
        engine.close()
