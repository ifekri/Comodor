"""The one property the saving rests on: the request grows only at its end.

Providers re-serve a prompt cheaply when the request *begins* with bytes they
have already stored. Not similar bytes — the same ones, from the first
character. So the saving is not really a feature that can be switched on; it is
a property of how requests are assembled, and it holds or it does not.

These tests run the real agent loop, take the messages it actually sent, encode
them the way the wire adapter does, and check that property literally: request
*n+1* must start with request *n*, byte for byte. Anything that breaks it —
recall in the system prompt, a timestamp in the header, a tool list that
reorders itself — fails here rather than quietly costing ten times the money.
"""

from __future__ import annotations

import json

from comodor.agent import AgentLoop, Conversation
from comodor.agent.prompts import IDENTITY
from comodor.learning import LearningEngine
from comodor.providers.anthropic import AnthropicProvider
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry

REFLECTION = json.dumps({
    "lessons": [{
        "kind": "pitfall",
        "trigger": "running the test suite in this project",
        "guidance": "Run pytest from the repository root.",
        "confidence": 0.8,
    }],
    "skill": None,
})


def wire(messages) -> str:
    """One request, serialised the way it would go on the wire."""
    system, encoded = AnthropicProvider(api_key="x")._encode(messages)
    return json.dumps({"system": system, "messages": encoded}, ensure_ascii=False)


def head(messages) -> str:
    return AnthropicProvider(api_key="x")._encode(messages)[0]


def requests_of(provider) -> list[list]:
    """Only the agent's own requests.

    Reflection and titling are separate one-shot calls with their own system
    prompts and their own short conversations. They are not part of the session
    prefix and must not be mistaken for it breaking.
    """
    return [call for call in provider.calls if IDENTITY[:40] in head(call)]


def test_each_request_begins_with_the_one_before_it(config, bus):
    """The whole feature, stated as one assertion.

    Every request in a session must be a byte-exact extension of its
    predecessor up to the point where new material starts. Where that holds,
    everything before the new material is a cache read; where it does not,
    the entire prompt is billed again at full price.
    """
    scripts = [Script(text="First answer."), Script(text="Second answer."),
               Script(text="Third answer.")]
    gateway = Gateway(config, scripts=scripts)
    agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation())

    agent.run("read the parser")
    agent.run("now change it")
    agent.run("and run the tests")

    sent = [wire(call) for call in requests_of(gateway.provider("fake"))]
    assert len(sent) >= 3

    for index in range(1, len(sent)):
        shared = 0
        while (shared < min(len(sent[index - 1]), len(sent[index]))
               and sent[index - 1][shared] == sent[index][shared]):
            shared += 1
        # The trailing "]}" of the previous request is the only part that must
        # differ; everything before the new message is required to be identical.
        assert shared > len(sent[index - 1]) - 32, (
            f"request {index} diverges from request {index - 1} after "
            f"{shared} of {len(sent[index - 1])} characters — the cache would miss")


def test_the_head_never_changes_once_a_session_has_started(config, bus):
    """Recall used to be written into the system prompt, which meant the first
    paragraph of every request differed and nothing behind it could match. This
    is that bug, asserted."""
    scripts = [Script(text="ok"), Script(text=f"```json\n{REFLECTION}\n```"),
               Script(text="ok again"), Script(text="ok once more")]
    gateway = Gateway(config, scripts=scripts)
    memory = LearningEngine(config, bus, gateway)
    agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation(), memory)

    agent.run("run the test suite")
    memory.wait_for_reflection(timeout=10.0)
    agent.run("run the test suite again")

    heads = {head(call) for call in requests_of(gateway.provider("fake"))}
    memory.close()

    assert len(heads) == 1, (
        "the system prompt differed between requests, so every request after "
        "the first would miss the cache entirely")


def test_a_recalled_lesson_still_reaches_the_model(config, bus):
    """Cheaper is worthless if the brain stopped arriving. Same guarantee as
    before, checked at its new address."""
    scripts = [Script(text="ok"), Script(text=f"```json\n{REFLECTION}\n```"),
               Script(text="ok again")]
    gateway = Gateway(config, scripts=scripts)
    memory = LearningEngine(config, bus, gateway)
    agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation(), memory)

    agent.run("run the test suite")
    memory.wait_for_reflection(timeout=10.0)
    agent.conversation = Conversation()
    agent.run("run the test suite again")

    everything = "".join(wire(call) for call in requests_of(gateway.provider("fake")))
    memory.close()

    assert "repository root" in everything


def test_the_lesson_travels_after_the_cached_part_not_before_it(config, bus):
    """Where it sits is the difference between 72% and 87% of the resends."""
    scripts = [Script(text="ok"), Script(text=f"```json\n{REFLECTION}\n```"),
               Script(text="ok again")]
    gateway = Gateway(config, scripts=scripts)
    memory = LearningEngine(config, bus, gateway)
    agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation(), memory)

    agent.run("run the test suite")
    memory.wait_for_reflection(timeout=10.0)
    agent.conversation = Conversation()
    agent.run("run the test suite again")

    calls = requests_of(gateway.provider("fake"))
    memory.close()

    assert not any("repository root" in head(call) for call in calls), \
        "recalled material must not sit in the system prompt"
