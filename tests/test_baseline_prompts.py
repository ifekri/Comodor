"""Characterization: the cached prompt head does not move between turns.

These tests pin *current* behaviour before the grounded-agent work changes
anything around it (spec 002, T001; FR-050, FR-091, SC-015). The whole prefix
cache rests on one fact: what `build_system_prompt` returns for a session is
byte-identical from one turn to the next, however much the recalled playbook
differs, because recall rides on the user message's `briefing` and never on
the system prompt. If a later change moves recall into the head, these fail.
"""

from __future__ import annotations

from comodor.agent import AgentLoop, Conversation
from comodor.agent.prompts import build_system_prompt
from comodor.providers.base import Role
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry


class _Lesson:
    def __init__(self, text: str) -> None:
        self.text = text

    def as_dict(self) -> dict:
        return {"text": self.text}


class _RecallThatChanges:
    """A stand-in brain whose playbook is different on every turn."""

    def __init__(self) -> None:
        self.turn = 0
        self.store = None
        self.facts_briefing = ""

    def before_turn(self, text: str) -> None:
        self.turn += 1

    def take_prefetched(self, text: str):
        return None

    def recall(self, text: str) -> list:
        return [_Lesson(f"lesson-{self.turn}")]

    def active_rules(self) -> list:
        return []

    def external_briefing(self, text: str) -> str:
        return ""

    def render_playbook(self, lessons, rules=None) -> str:
        return f"Playbook for turn {self.turn}: {', '.join(lesson.text for lesson in lessons)}"

    def record_outcome(self, **kwargs) -> None:
        pass


def _agent(config, bus, scripts, memory):
    gateway = Gateway(config, scripts=scripts)
    return AgentLoop(config, gateway, ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation(),
                     memory=memory), gateway


def test_the_system_prompt_is_byte_identical_across_turns_with_differing_recall(config, bus):
    config.learning.enabled = True
    memory = _RecallThatChanges()
    agent, gateway = _agent(config, bus, [Script(text="ok")] * 3, memory)

    for turn in ("first", "second", "third"):
        agent.run(turn)

    provider = gateway.provider("fake")
    heads = [call[0] for call in provider.calls]
    assert all(head.role is Role.SYSTEM for head in heads)
    assert len({head.content for head in heads}) == 1, \
        "the system prompt changed between turns — the prefix cache is lost"

    # And the recall did differ, so the head being stable is not vacuous.
    briefings = [message.briefing for call in provider.calls
                 for message in call if message.role is Role.USER and message.briefing]
    assert len(set(briefings)) == 3
    assert all("Playbook for turn" in briefing for briefing in briefings)
    # Recall never leaks into the head.
    assert "Playbook" not in heads[0].content


def test_recall_rides_on_the_user_message_not_the_system_prompt(config):
    """`build_system_prompt` with no playbook is the head every turn sends."""
    plain = build_system_prompt(config)
    again = build_system_prompt(config)
    assert plain == again
    assert "Playbook" not in plain


def test_the_head_is_ordered_identity_environment_mode_then_tools(config):
    """The order is the caching order: stable parts first."""
    head = build_system_prompt(config)
    identity = head.index("You are Comodor")
    environment = head.index("Environment:")
    mode = head.index("Mode: ACT")
    tools = head.index("Using tools:")
    assert identity < environment < mode < tools


def test_project_instructions_sit_after_the_tool_guidance_and_before_extras(config):
    (config.paths.project / "COMODOR.md").write_text("Always use tabs.\n",
                                                     encoding="utf-8")
    config.agent.system_prompt_extra = "Extra words."
    head = build_system_prompt(config)
    assert head.index("Using tools:") < head.index("Project instructions") \
        < head.index("Extra words.")
    # The instructions are carried exactly once.
    assert head.count("Always use tabs.") == 1
