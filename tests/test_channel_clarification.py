"""A needed decision reaches every channel that runs turns (T135; FR-121).

All four messaging channels — Telegram, Slack, WhatsApp and Discord — drive
the same `web.session.Session`, so the turn outcome is produced once and each
channel's `_follow` loop is what consumes it. Two things are asserted:

* the shared turn path closes a clarification-required turn with a visible
  message naming the decision and how the clarification ended, and
* each channel's `_follow` renders that message (and never substitutes an
  invented value or a default).

No network, no credentials: the platform transport is replaced by a scripted
event stream.
"""

from __future__ import annotations

import importlib
import threading

import pytest

from comodor import questions as forms
from comodor.agent import AgentLoop
from comodor.agent import Conversation as AgentConversation
from comodor.events import Kind
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry

DECISION = ("Stopped: a decision is needed before this can continue — "
            "Which database should we use? (nobody was there to answer)")

CHANNELS = [
    ("comodor.telegram.bot", "telegram", 555),
    ("comodor.slack.bot", "slack", "U1"),
    ("comodor.whatsapp.bot", "whatsapp", "15551234"),
    ("comodor.discord.bot", "discord", "U1"),
]


class FakeSession:
    """A session that hands its scripted events over exactly once."""

    def __init__(self, events: list[dict]) -> None:
        self._events = list(events)
        self.cursor = 0

    def wait_for(self, cursor: int, timeout: float = 8.0) -> list[dict]:
        events, self._events = self._events, []
        if events:
            self.cursor += 1
        return events

    def close(self) -> None:
        pass


def _clarification_events() -> list[dict]:
    return [
        {"kind": "assistant_delta", "text": "Asking."},
        {"kind": "assistant_end", "text": DECISION},
        {"kind": "turn_end", "stopped": "clarification_required",
         "clarification": {"kind": "clarification_required",
                           "decision": "Which database should we use?",
                           "outcome": "unattended", "decisions": []}},
    ]


def _talk(bot, events):
    """A channel conversation with a scripted session and no real transport."""
    talk = object.__new__(bot.Conversation)
    talk.session = FakeSession(events)
    talk.cursor = 0
    return talk


# --------------------------------------------------------------------------- #
# the shared turn path produces the message
# --------------------------------------------------------------------------- #


def test_the_turn_closes_with_the_needed_decision_visible(config, bus):
    """A clarification-required turn emits the decision as its closing
    assistant message, so every surface can show it (FR-121)."""

    def dismiss(event):
        if event.kind is Kind.REQUEST:
            event.payload["request"].answer(forms.CANCELLED)

    bus.subscribe(dismiss)
    question = ToolCall(id="q1", name="ask", arguments={"questions": [{
        "question": "Which database should we use?", "header": "Database",
        "affects": ["persistence"],
        "options": [{"label": "SQLite", "source": "request", "evidence": "SQLite"},
                    {"label": "PostgreSQL", "source": "request", "evidence": "PostgreSQL"}]}]})
    scripts = [Script(text="Asking.", tool_calls=[question]), Script(text="never")]
    agent = AgentLoop(config, Gateway(config, scripts=scripts), ToolRegistry(),
                      bus, PermissionEngine(config, bus), AgentConversation())

    ends: list[dict] = []
    turns: list[dict] = []
    bus.subscribe(lambda event: ends.append(dict(event.payload))
                  if event.kind is Kind.ASSISTANT_END else None)
    bus.subscribe(lambda event: turns.append(dict(event.payload))
                  if event.kind is Kind.TURN_END else None)

    result = agent.run("SQLite or PostgreSQL?")

    assert result.stopped == "clarification_required"
    final = [end for end in ends if end.get("text") == result.text]
    assert final, "the decision text must be emitted as a visible message"
    assert "Which database should we use?" in final[-1]["text"]
    assert "cancelled" in final[-1]["text"]
    assert turns and turns[-1]["stopped"] == "clarification_required"
    assert turns[-1]["clarification"]["outcome"] == "cancelled"


# --------------------------------------------------------------------------- #
# each channel consumes it
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("module,key", [(spec[0], spec[2]) for spec in CHANNELS])
def test_a_channel_renders_the_needed_decision(module, key):
    bot = importlib.import_module(module)
    service = bot.Service.__new__(bot.Service)
    service.stopping = threading.Event()
    captured: dict = {}
    if hasattr(bot.Service, "_finish"):
        # WhatsApp speaks once at the end rather than editing a growing reply.
        service._finish = lambda talk, answer, tools: captured.update(text=answer)
    else:
        service._draw = (lambda talk, text, tools, final=False:
                         captured.update(text=text))

    service._follow(_talk(bot, _clarification_events()))

    text = captured.get("text", "")
    assert DECISION in text, f"{module} did not surface the decision"
    assert "nobody was there to answer" in text, (
        f"{module} did not name which clarification outcome occurred")


@pytest.mark.parametrize("module,key", [(spec[0], spec[2]) for spec in CHANNELS])
def test_a_channel_never_treats_the_decision_as_a_completed_answer(module, key):
    """The channel renders the turn's own closing text and invents nothing;
    there is no option label or default anywhere in what it sends."""
    bot = importlib.import_module(module)
    service = bot.Service.__new__(bot.Service)
    service.stopping = threading.Event()
    captured: dict = {}
    if hasattr(bot.Service, "_finish"):
        service._finish = lambda talk, answer, tools: captured.update(text=answer)
    else:
        service._draw = (lambda talk, text, tools, final=False:
                         captured.update(text=text))

    service._follow(_talk(bot, _clarification_events()))

    text = captured.get("text", "")
    assert "SQLite" not in text and "PostgreSQL" not in text, (
        f"{module} invented a chosen value")


def test_a_cancelled_turn_is_not_rewritten_as_a_clarification():
    """The turn lifecycle keeps its own meaning: a `cancelled` event renders
    the stopped note, never the clarification message (contracts §C5)."""
    bot = importlib.import_module("comodor.telegram.bot")
    service = bot.Service.__new__(bot.Service)
    service.stopping = threading.Event()
    captured: dict = {}
    service._draw = lambda talk, text, tools, final=False: captured.update(text=text)

    service._follow(_talk(bot, [
        {"kind": "assistant_delta", "text": "Working."},
        {"kind": "cancelled", "reason": "stop"},
    ]))

    assert "stopped" in captured["text"].lower()
    assert DECISION not in captured["text"]


# --------------------------------------------------------------------------- #
# T185 — the needed-decision text names each decision's ref, once, in the core
# --------------------------------------------------------------------------- #


def test_the_closing_text_names_every_open_decisions_ref(config, bus, monkeypatch):
    from comodor.agent import evidence

    refs = iter(["dr-first-ref", "dr-second-ref"])
    monkeypatch.setattr(evidence, "mint_ref", lambda: next(refs))
    option = lambda label: {"label": label, "source": "request", "evidence": label}  # noqa: E731
    question = ToolCall(id="q1", name="ask", arguments={"questions": [
        {"question": "Which database should we use?", "header": "Database",
         "affects": ["persistence"], "options": [option("SQLite"), option("PostgreSQL")]},
        {"question": "Which queue should we use?", "header": "Queue",
         "affects": ["persistence"], "options": [option("Redis"), option("RabbitMQ")]}]})
    agent = AgentLoop(config, Gateway(config, scripts=[
        Script(text="Asking.", tool_calls=[question]), Script(text="never")]),
        ToolRegistry(), bus, PermissionEngine(config, bus), AgentConversation())
    ends: list[str] = []

    def watch(event):
        # A listening bus: the form is dismissed at once rather than waited on.
        if event.kind is Kind.REQUEST:
            event.payload["request"].answer(forms.CANCELLED)
        elif event.kind is Kind.ASSISTANT_END:
            ends.append(str(event.payload.get("text") or ""))

    bus.subscribe(watch)

    result = agent.run("SQLite or PostgreSQL, Redis or RabbitMQ?")

    assert result.stopped == "clarification_required"
    assert "- Which database should we use? (decision_ref: dr-first-ref)" in result.text
    assert "- Which queue should we use? (decision_ref: dr-second-ref)" in result.text
    assert ends[-1] == result.text, "the text every channel relays carries the refs"


@pytest.mark.parametrize("module,key", [(spec[0], spec[2]) for spec in CHANNELS])
def test_every_channel_relays_the_ref_as_the_core_wrote_it(module, key):
    """No channel formats the ref itself: Discord and the webhook's reply
    delivery included, each relays the core's text, which already names it."""
    named = DECISION + " (decision_ref: dr-relay-1)"
    bot = importlib.import_module(module)
    service = bot.Service.__new__(bot.Service)
    service.stopping = threading.Event()
    captured: dict = {}
    if hasattr(bot.Service, "_finish"):
        service._finish = lambda talk, answer, tools: captured.update(text=answer)
    else:
        service._draw = (lambda talk, text, tools, final=False:
                         captured.update(text=text))
    events = _clarification_events()
    events[1] = {"kind": "assistant_end", "text": named}
    service._follow(_talk(bot, events))
    assert "decision_ref: dr-relay-1" in captured.get("text", "")


def test_the_core_notification_names_the_ref_too(config):
    from comodor.application import CoreService, _relay_clarification
    from comodor.events import Event

    service = CoreService(config)
    try:
        handle = service.session(service.create_session()["id"])
        sent = []
        service.on_event = lambda _s, name, params, _q: sent.append((name, params))
        _relay_clarification(service, handle, Event(kind=Kind.TURN_END, payload={
            "stopped": "clarification_required",
            "clarification": {"decision": "Which database?", "candidates": [],
                              "evidence_consulted": [], "reason": "persisted_state",
                              "outcome": "unattended", "decision_ref": "dr-core-1"}}))
    finally:
        service.close()
    (note,) = [params["text"] for name, params in sent if name == "notification.created"]
    assert "(decision_ref: dr-core-1)" in note


# --------------------------------------------------------------------------- #
# T188 — Discord has no structured reply: it reports, and never resumes
# --------------------------------------------------------------------------- #


def test_discord_free_text_is_a_new_request_never_a_decision_answer(monkeypatch):
    """Discord relays the needed-decision text with its ref (T185) and offers
    no resumption route: whatever is typed afterwards starts a new turn
    carrying no decision answer."""
    import inspect

    bot = importlib.import_module("comodor.discord.bot")
    assert "resume_decision" not in inspect.getsource(bot), \
        "Discord gained a resumption route no structured reply can carry"

    sent: list[tuple] = []

    class Recording:
        busy = False
        cursor = 0

        def send(self, text, images=None, decisions=None, decision_answers=None):
            sent.append((text, decision_answers))
            return False

        def interrupt(self, *_):
            pass

    from comodor.channels.busy import start_or_steer

    start_or_steer(Recording(), "PostgreSQL", None, "queue", lambda note: None)
    assert sent == [("PostgreSQL", None)]
