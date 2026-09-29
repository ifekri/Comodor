"""One decision point, one form (T216, T218; FR-014, SC-007, D18, D19).

Every material question one model reply raises — through several `ask`
calls, or through the mutation preflight beside them — reaches the person as
one form: one request, answered by one submission. The form has no upper
bound; a client pages it. The same decision asked twice is one question,
shown under the first header and answered to each call under its own. If any
`ask` in the reply is refused, none is asked and nothing that may depend on
the set runs. Each case counts the forms the bus actually carried.
"""

from __future__ import annotations

import json

import pytest

from comodor import questions as forms
from comodor.agent import AgentLoop, Conversation
from comodor.agent import loop as loop_module
from comodor.events import EventBus, Kind
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry
from comodor.tools import ask as ask_tool

REQUEST = ("Build the service. Which database: SQLite or PostgreSQL? Which cache: "
           "Redis or Memcached? Which queue: RabbitMQ or Kafka? Which language: "
           "Go or Rust? Which region: Europe or Asia? Which licence: MIT or GPL?")

TOPICS = {
    "Database": ("Which database should this use?", "SQLite", "PostgreSQL"),
    "Cache": ("Which cache should this use?", "Redis", "Memcached"),
    "Queue": ("Which queue should this use?", "RabbitMQ", "Kafka"),
    "Language": ("Which language should this use?", "Go", "Rust"),
    "Region": ("Which region should this deploy to?", "Europe", "Asia"),
    "Licence": ("Which licence should this ship under?", "MIT", "GPL"),
}


def question(header, prompt=None):
    text, first, second = TOPICS.get(header, TOPICS["Database"])
    return {"question": prompt or text, "header": header, "affects": ["architecture"],
            "options": [{"label": first, "source": "request", "evidence": first},
                        {"label": second, "source": "request", "evidence": second}]}


def ask(call_id, *questions):
    return ToolCall(id=call_id, name="ask", arguments={"questions": list(questions)})


def write(call_id="w1", path="service.py"):
    return ToolCall(id=call_id, name="write_file",
                    arguments={"path": path, "content": "SERVICE = True\n"})


def make_agent(config, bus, scripts):
    return AgentLoop(config, Gateway(config, scripts=scripts), ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation())


class Person:
    """Answers each form on the emitting thread, and counts them."""

    def __init__(self, bus, reply):
        self.reply = reply
        self.forms: list = []
        self.displays: dict[str, str] = {}
        bus.subscribe(self)

    def __call__(self, event):
        if event.kind is Kind.REQUEST and event.payload["request"].kind == "questions":
            request = event.payload["request"]
            self.forms.append(request)
            reply = self.reply(request) if callable(self.reply) else self.reply
            if reply is not None:
                request.answer(reply)
        elif event.kind is Kind.TOOL_END:
            self.displays[str(event.get("id"))] = str(event.get("display") or "")

    def headers(self, index=0):
        return [entry["header"] for entry in self.forms[index].meta["questions"]]


def first_option_for_every_question(request):
    """A real answer: the first offered option on every question shown."""
    answers = []
    for entry in request.meta["questions"]:
        offered = [option["label"] for option in entry["options"] if not option.get("free")]
        answers.append({"header": entry["header"], "prompt": "",
                        "chosen": offered[:1], "written": "" if offered else "yes"})
    return json.dumps(answers)


def only(*headers):
    """Answer just these headers, with their first option; leave the rest blank."""
    def reply(request):
        answers = []
        for entry in request.meta["questions"]:
            offered = [o["label"] for o in entry["options"] if not o.get("free")]
            chosen = offered[:1] if entry["header"] in headers else []
            answers.append({"header": entry["header"], "prompt": "",
                            "chosen": chosen, "written": ""})
        return json.dumps(answers)
    return reply


def tool_text(agent, call_id):
    return next(m.content for m in agent.conversation.messages if m.tool_call_id == call_id)


# --------------------------------------------------------------------------- #
# C1-C4: the batch forms one form
# --------------------------------------------------------------------------- #


def test_c1_one_call_with_three_questions_is_one_form(config, bus):
    person = Person(bus, first_option_for_every_question)
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[ask("q1", question("Database"),
                                               question("Cache"), question("Queue"))]),
        Script(text="Done.")])
    agent.run(REQUEST)
    assert len(person.forms) == 1
    assert person.headers() == ["Database", "Cache", "Queue"]


def test_c2_two_calls_for_two_decisions_are_one_form(config, bus):
    person = Person(bus, first_option_for_every_question)
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[ask("q1", question("Database")),
                                           ask("q2", question("Cache"))]),
        Script(text="Done.")])
    result = agent.run(REQUEST)
    assert len(person.forms) == 1, "one reply is one decision point"
    assert person.headers() == ["Database", "Cache"]
    assert result.ok
    assert "SQLite" in tool_text(agent, "q1") and "Redis" not in tool_text(agent, "q1")
    assert "Redis" in tool_text(agent, "q2") and "SQLite" not in tool_text(agent, "q2")


def test_c2_the_one_form_is_the_coalescing(config, bus, monkeypatch):
    """Mutation check: without the coalescing, the reply raises two forms."""
    monkeypatch.setattr(loop_module.AgentLoop, "_ask_as_one_form", lambda self: False)
    person = Person(bus, first_option_for_every_question)
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[ask("q1", question("Database")),
                                           ask("q2", question("Cache"))]),
        Script(text="Done.")])
    agent.run(REQUEST)
    assert len(person.forms) == 2, "the mutation raises one form per call"


def test_c3_the_same_decision_twice_is_one_question(config, bus):
    person = Person(bus, first_option_for_every_question)
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[ask("q1", question("Database")),
                                           ask("q2", question("Database"))]),
        Script(text="Done.")])
    agent.run(REQUEST)
    assert len(person.forms) == 1
    assert person.headers() == ["Database"]
    decisions = [d for d in agent.tool_context.evidence.decisions if d.material]
    assert len(decisions) == 1 and decisions[0].state == "answered"


def test_c3_one_question_is_the_decision_key(config, bus, monkeypatch):
    """Mutation check: keyed per call, the same decision is shown twice."""
    counter = iter(range(1000))
    monkeypatch.setattr(ask_tool, "_key", lambda prompt: f"{prompt}#{next(counter)}")
    # The same header then looks like a collision; let it through, so what is
    # measured is the de-duplication alone.
    monkeypatch.setattr(ask_tool, "collision", lambda calls: "")
    person = Person(bus, first_option_for_every_question)
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[ask("q1", question("Database")),
                                           ask("q2", question("Database"))]),
        Script(text="Done.")])
    agent.run(REQUEST)
    assert len(person.headers()) == 2, "the mutation shows one decision twice"


def test_c4_the_same_decision_twice_cancelled_is_one_form(config, bus):
    person = Person(bus, forms.CANCELLED)
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[ask("q1", question("Database")),
                                           ask("q2", question("Database")), write()]),
        Script(text="Done.")])
    result = agent.run(REQUEST)
    assert len(person.forms) == 1
    assert result.stopped == "clarification_required"
    assert result.clarification["outcome"] == "cancelled"
    assert not (config.paths.project / "service.py").exists()


# --------------------------------------------------------------------------- #
# C5: the preflight's missing decision rides on the same form
# --------------------------------------------------------------------------- #


MISSING_RATE = json.dumps({
    "status": "requires_clarification",
    "decisions": [{"what": "What rate limit should the service use?",
                   "affects": ["behaviour"], "resolution": "missing", "source_refs": []}],
    "reason": "the quota belongs to the account"})


@pytest.mark.parametrize("order", ["ask_then_write", "write_then_ask"])
def test_c5_an_ask_and_a_preflight_decision_share_one_form(config, bus, order):
    person = Person(bus, lambda request: json.dumps([
        {"header": entry["header"], "prompt": "",
         "chosen": [o["label"] for o in entry["options"] if not o.get("free")][:1],
         "written": "" if any(not o.get("free") for o in entry["options"]) else "100/s"}
        for entry in request.meta["questions"]]))
    calls = [ask("q1", question("Database")), write()]
    if order == "write_then_ask":
        calls.reverse()
    agent = make_agent(config, bus, [Script(text="Working.", tool_calls=calls),
                                     Script(text="Done.")])
    agent.gateway.provider("fake").preflight = MISSING_RATE
    result = agent.run(REQUEST)
    assert len(person.forms) == 1, "the reply's decisions share one form"
    prompts = [entry["prompt"] for entry in person.forms[0].meta["questions"]]
    assert "What rate limit should the service use?" in prompts
    assert "Which database should this use?" in prompts
    assert result.ok and (config.paths.project / "service.py").exists()


# --------------------------------------------------------------------------- #
# C6: a later model call is a new decision point
# --------------------------------------------------------------------------- #


def test_c6_a_question_in_the_next_model_call_is_a_new_form(config, bus):
    person = Person(bus, first_option_for_every_question)
    agent = make_agent(config, bus, [
        Script(text="First.", tool_calls=[ask("q1", question("Database"))]),
        Script(text="Then.", tool_calls=[ask("q2", question("Cache"))]),
        Script(text="Done.")])
    agent.run(REQUEST)
    assert len(person.forms) == 2


# --------------------------------------------------------------------------- #
# C7, C8, C12: partial answers and non-answers
# --------------------------------------------------------------------------- #


def test_c7_a_partial_answer_leaves_the_rest_open(config, bus):
    person = Person(bus, only("Database"))
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[ask("q1", question("Database")),
                                           ask("q2", question("Cache")), write()]),
        Script(text="Done.")])
    result = agent.run(REQUEST)
    assert len(person.forms) == 1
    assert result.stopped == "clarification_required"
    open_refs = [entry["decision"] for entry in result.clarification["decisions"]]
    assert open_refs == ["Which cache should this use?"], "reported once"
    assert "SQLite" in tool_text(agent, "q1")
    assert "Which database" not in tool_text(agent, "q2")
    assert not (config.paths.project / "service.py").exists()


@pytest.mark.parametrize("ending", ["cancelled", "expired", "unattended"])
def test_c8_a_non_answer_applies_to_every_decision(config, ending, monkeypatch):
    bus = EventBus()
    if ending == "expired":
        monkeypatch.setattr(ask_tool, "WAIT_FOR", 0.0)
        person = Person(bus, None)
    elif ending == "cancelled":
        person = Person(bus, forms.CANCELLED)
    else:
        person = None                          # nobody listening
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[ask("q1", question("Database")),
                                           ask("q2", question("Cache")), write()]),
        Script(text="Done.")])
    result = agent.run(REQUEST)
    if person is not None:
        assert len(person.forms) == 1
    assert result.stopped == "clarification_required"
    assert result.clarification["outcome"] == ending
    named = sorted(entry["decision"] for entry in result.clarification["decisions"])
    assert named == ["Which cache should this use?", "Which database should this use?"]
    assert not (config.paths.project / "service.py").exists()


def test_c12_six_questions_cancelled_leave_every_decision_open(config, bus):
    person = Person(bus, forms.CANCELLED)
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[
            ask("q1", question("Database"), question("Cache")),
            ask("q2", question("Queue"), question("Language")),
            ask("q3", question("Region"), question("Licence")), write()]),
        Script(text="Done.")])
    result = agent.run(REQUEST)
    assert len(person.forms) == 1 and len(person.headers()) == 6
    assert len(result.clarification["decisions"]) == 6
    assert all(d.state == "unresolved" for d in agent.tool_context.evidence.decisions
               if d.material)
    assert not (config.paths.project / "service.py").exists()


# --------------------------------------------------------------------------- #
# C9: more than four questions, one form, one submission
# --------------------------------------------------------------------------- #


def test_c9_six_questions_from_three_calls_are_one_form(config, bus):
    person = Person(bus, first_option_for_every_question)
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[
            ask("q1", question("Database"), question("Cache")),
            ask("q2", question("Queue"), question("Language")),
            ask("q3", question("Region"), question("Licence"))]),
        Script(text="Done.")])
    result = agent.run(REQUEST)
    assert len(person.forms) == 1, "one request"
    assert person.headers() == list(TOPICS)
    assert result.ok
    assert "RabbitMQ" in tool_text(agent, "q2") and "SQLite" not in tool_text(agent, "q2")
    assert "Europe" in tool_text(agent, "q3")
    answered = [d for d in agent.tool_context.evidence.decisions if d.state == "answered"]
    assert len(answered) == 6


def test_c9_more_than_four_in_one_call_is_refused(config, bus):
    person = Person(bus, first_option_for_every_question)
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[ask("q1", *[question(h) for h in TOPICS])]),
        Script(text="Done.")])
    agent.run(REQUEST)
    assert person.forms == []
    assert "at most" in tool_text(agent, "q1")


# --------------------------------------------------------------------------- #
# C10: atomic refusal
# --------------------------------------------------------------------------- #


REFUSALS = {
    "too_many": ask("q2", *[question(h) for h in TOPICS]),
    "malformed": ToolCall(id="q2", name="ask", arguments={"questions": "not a list"}),
    "permission": ToolCall(id="q2", name="ask", arguments={"questions": [{
        "question": "Should I proceed?", "header": "Go",
        "options": [{"label": "Yes"}, {"label": "No"}]}]}),
    "collision": ask("q2", question("Database", prompt="Which store should this use?")),
}


@pytest.mark.parametrize("reason", list(REFUSALS))
def test_c10_one_refused_ask_refuses_the_set_and_withholds_the_write(config, bus, reason):
    person = Person(bus, first_option_for_every_question)
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[ask("q1", question("Database")),
                                           REFUSALS[reason], write()]),
        Script(text="Again, together.", tool_calls=[ask("q3", question("Database")),
                                                    ask("q4", question("Cache"))]),
        Script(text="Done.")])
    agent.run(REQUEST)
    assert len(person.forms) == 1, "nothing from the refused reply; one form on retry"
    assert person.headers() == ["Database", "Cache"]
    assert "not asked" in tool_text(agent, "q1")
    assert "not asked" in tool_text(agent, "q2")
    assert "not run" in tool_text(agent, "w1")
    assert not (config.paths.project / "service.py").exists()


def test_c10_the_refusal_is_atomic(config, bus, monkeypatch):
    """Mutation check: without the set-wide refusal, a partial form appears."""
    monkeypatch.setattr(loop_module.AgentLoop, "_refuse_asks", lambda self, asks: "")
    person = Person(bus, first_option_for_every_question)
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[ask("q1", question("Database")),
                                           REFUSALS["malformed"]]),
        Script(text="Done.")])
    agent.run(REQUEST)
    assert len(person.forms) == 1, "the mutation puts the valid half to the person"


def test_c10_the_write_waits_because_of_the_withholding(config, bus, monkeypatch):
    """Mutation check: without the withholding, the sibling write runs."""
    monkeypatch.setattr(loop_module.AgentLoop, "_refused_sibling", lambda self, call: False)
    Person(bus, first_option_for_every_question)
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[ask("q1", question("Database")),
                                           REFUSALS["malformed"], write()]),
        Script(text="Done.")])
    agent.run(REQUEST)
    assert (config.paths.project / "service.py").exists(), "the mutation lets it run"


# --------------------------------------------------------------------------- #
# C11: a decision carried back from a delegate is not asked in the parent
# --------------------------------------------------------------------------- #


def test_c11_a_carried_decision_is_not_put_into_the_parents_form(config, bus):
    person = Person(bus, first_option_for_every_question)
    carried = {"kind": "clarification_required", "outcome": "cancelled",
               "decision": "Which database should this use?",
               "decisions": [{"decision": "Which database should this use?",
                              "reason": "architecture", "candidates": []}]}
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[ask("q1", question("Database")),
                                           ask("q2", question("Database"))]),
        Script(text="Done.")])
    result = agent.run(REQUEST, decisions=[carried])
    assert person.forms == [], "the carried decision is reported, never re-asked"
    assert result.stopped == "clarification_required"


# --------------------------------------------------------------------------- #
# C13: one decision under two headers
# --------------------------------------------------------------------------- #


def two_headers():
    return [Script(text="Asking.", tool_calls=[
        ask("q1", question("Database")),
        ask("q2", question("Store", prompt="Which database should this use?"))]),
        Script(text="Done.")]


def test_c13_one_decision_under_two_headers_is_answered_under_each(config, bus):
    person = Person(bus, first_option_for_every_question)
    agent = make_agent(config, bus, two_headers())
    agent.run(REQUEST)
    assert len(person.forms) == 1 and person.headers() == ["Database"]
    assert person.displays["q1"] == "Database: SQLite"
    assert person.displays["q2"] == "Store: SQLite"


def test_c13_a_cancellation_reaches_each_call(config, bus):
    Person(bus, forms.CANCELLED)
    agent = make_agent(config, bus, two_headers())
    result = agent.run(REQUEST)
    assert result.clarification["outcome"] == "cancelled"
    for call_id in ("q1", "q2"):
        assert "remain unresolved" in tool_text(agent, call_id)


def test_c13_each_call_reads_its_own_header(config, bus, monkeypatch):
    """Mutation check: returned only under the shown header, the second call
    reads an answer under a header it never used."""
    monkeypatch.setattr(ask_tool, "_rebind", lambda given, own, prompt: forms.Answer(
        header=given["header"], prompt=prompt, chosen=list(given.get("chosen") or [])))
    person = Person(bus, first_option_for_every_question)
    agent = make_agent(config, bus, two_headers())
    agent.run(REQUEST)
    assert person.displays["q2"] != "Store: SQLite", "the mutation loses the own header"


# --------------------------------------------------------------------------- #
# N4: what the model is told, and that it is stable
# --------------------------------------------------------------------------- #


def test_the_ask_description_says_one_reply_is_one_form():
    description = ask_tool.Ask.description
    assert "one form" in description
    assert f"at most {forms.MAX_QUESTIONS} questions" in description
    assert "several `ask` calls in the same reply" in description
    items = ask_tool.Ask.parameters["properties"]["questions"]
    assert items["maxItems"] == forms.MAX_QUESTIONS, "the per-call limit is unchanged"
    assert "one form" in items["description"]


def test_the_ask_specification_is_the_same_on_every_turn(config):
    registry = ToolRegistry()
    first = [spec for spec in registry.specs("act") if spec.name == "ask"]
    second = [spec for spec in registry.specs("act") if spec.name == "ask"]
    assert first and first == second, "a stable head keeps the cached prefix"
