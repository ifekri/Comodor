"""Non-interactive blocking (T044; FR-033, FR-121, SC-002).

With no bus subscriber a material clarification ends the turn in
`clarification_required`, and no invented value appears anywhere in the
output. The guard — reading presence from the bus — is mutation-checked.
"""

from __future__ import annotations

from comodor.agent import AgentLoop, Conversation
from comodor.events import EventBus
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry

REQUEST = "Which database, SQLite or PostgreSQL? Then write db.py."


def a_question():
    return ToolCall(id="q1", name="ask", arguments={"questions": [{
        "question": "Which database?", "header": "Database", "affects": ["architecture"],
        "options": [{"label": "SQLite", "source": "request", "evidence": "SQLite"},
                    {"label": "PostgreSQL", "source": "request", "evidence": "PostgreSQL"}],
    }]})


def scripts():
    return [Script(text="One question first.", tool_calls=[a_question()]),
            Script(text="Writing SQLite.", tool_calls=[ToolCall(
                id="w1", name="write_file",
                arguments={"path": "db.py", "content": "ENGINE = 'sqlite'\n"})]),
            Script(text="Done — SQLite it is, I chose it for you.")]


def make_agent(config, bus):
    gateway = Gateway(config, scripts=scripts())
    return AgentLoop(config, gateway, ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation()), gateway


def _everything_the_model_read(gateway):
    return "\n".join(message.content for call in gateway.provider("fake").calls
                     for message in call)


def test_with_nobody_listening_the_turn_ends_needing_a_decision(config):
    agent, gateway = make_agent(config, EventBus())
    result = agent.run(REQUEST)

    assert result.stopped == "clarification_required"
    assert result.ok is False
    assert result.clarification["outcome"] == "unattended"
    assert result.clarification["decision"] == "Which database?"
    assert [c["label"] for c in result.clarification["candidates"]] == ["SQLite", "PostgreSQL"]
    assert "evidence_consulted" in result.clarification


def test_no_invented_value_appears_anywhere_in_the_output(config):
    agent, gateway = make_agent(config, EventBus())
    result = agent.run(REQUEST)

    assert "I chose it for you" not in result.text
    assert "sensible defaults" not in _everything_the_model_read(gateway).lower()
    assert not (config.paths.project / "db.py").exists()
    assert "no default was chosen" in result.text
    assert result.steps == 1


def test_the_payload_is_enough_to_answer_in_a_later_invocation(config):
    """FR-034: decision, candidates, evidence consulted."""
    (config.paths.project / "settings.py").write_text("x = 1\n", encoding="utf-8")
    agent, _ = make_agent(config, EventBus())
    agent.tool_context = None
    result = agent.run(REQUEST)
    payload = result.clarification
    assert payload["kind"] == "clarification_required"
    assert payload["decision"] and payload["candidates"]
    assert isinstance(payload["evidence_consulted"], list)
    assert payload["reason"] == "architecture"
    assert payload["decisions"][0]["id"].startswith("d")


def test_a_later_answer_in_the_next_turn_resumes_the_work(config):
    """T038's replay: an answer supplied after the block produces the same
    result as a first-time answer."""
    agent, _ = make_agent(config, EventBus())
    first = agent.run(REQUEST)
    assert first.stopped == "clarification_required"

    # The person comes back and answers in words; the model proceeds.
    agent.gateway = Gateway(config, scripts=[
        Script(text="Writing SQLite.", tool_calls=[ToolCall(
            id="w2", name="write_file",
            arguments={"path": "db.py", "content": "ENGINE = 'sqlite'\n"})]),
        Script(text="Done: db.py uses SQLite."),
    ])
    second = agent.run("Use SQLite.")
    assert second.ok and second.stopped == "done"
    assert (config.paths.project / "db.py").read_text(encoding="utf-8") == "ENGINE = 'sqlite'\n"
    assert second.text == "Done: db.py uses SQLite."


def test_the_guard_is_the_presence_check(config, monkeypatch):
    """Mutation check: pretend somebody is listening and the form waits on a
    bus that will never answer — so the wait is shortened to prove the
    difference is the presence check, not the wait."""
    from comodor.tools import ask as ask_tool

    monkeypatch.setattr(ask_tool, "WAIT_FOR", 0.0)
    monkeypatch.setattr(EventBus, "listening", property(lambda self: True))
    agent, _ = make_agent(config, EventBus())
    result = agent.run(REQUEST)
    assert result.clarification["outcome"] == "expired", \
        "with presence faked, the form is raised and expires instead"

    monkeypatch.undo()
    monkeypatch.setattr(ask_tool, "WAIT_FOR", 0.0)
    agent, _ = make_agent(config, EventBus())
    result = agent.run(REQUEST)
    assert result.clarification["outcome"] == "unattended"
