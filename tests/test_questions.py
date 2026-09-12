"""The question form: what the model may send, and what comes back."""

from __future__ import annotations

import json
import threading

import pytest

from comodor import questions as forms
from comodor.events import EventBus, Kind
from comodor.questions import (
    CANCELLED,
    Answer,
    MalformedQuestions,
    decode,
    decode_answers,
    encode,
    encode_answers,
    parse,
    summarise,
)
from comodor.tools.ask import Ask

# --------------------------------------------------------------------------- #
# what the model sends
# --------------------------------------------------------------------------- #


def a_question(**over):
    base = {
        "question": "Which database should this use?",
        "header": "Database",
        "options": [
            {"label": "PostgreSQL", "description": "Relational"},
            {"label": "SQLite", "description": "No server"},
        ],
    }
    base.update(over)
    return base


def test_a_free_row_is_always_added():
    [question] = parse([a_question()])
    assert question.options[-1].free
    assert question.options[-1].label == forms.WRITE_YOUR_OWN
    # And it is the only one.
    assert sum(1 for option in question.options if option.free) == 1


def test_the_free_row_does_not_spend_one_of_the_four_slots():
    labels = [{"label": f"Option {n}"} for n in range(forms.MAX_OPTIONS)]
    [question] = parse([a_question(options=labels)])
    assert len(question.options) == forms.MAX_OPTIONS + 1


def test_a_model_written_escape_hatch_is_dropped():
    """Otherwise the user gets two of them and only one works."""
    [question] = parse([a_question(options=[
        {"label": "PostgreSQL"},
        {"label": "SQLite"},
        {"label": "Other"},
        {"label": "None of the above"},
    ])])
    labels = [option.label for option in question.options]
    assert labels == ["PostgreSQL", "SQLite", forms.WRITE_YOUR_OWN]


def test_plain_strings_are_accepted_as_options():
    """Models get this shape wrong routinely; refusing costs a turn."""
    [question] = parse([a_question(options=["PostgreSQL", "SQLite"])])
    assert [option.label for option in question.options[:2]] == ["PostgreSQL", "SQLite"]


def test_one_option_is_refused():
    with pytest.raises(MalformedQuestions, match="at least"):
        parse([a_question(options=[{"label": "Only this"}])])


def test_too_many_options_is_refused():
    many = [{"label": f"Option {n}"} for n in range(forms.MAX_OPTIONS + 1)]
    with pytest.raises(MalformedQuestions, match="limit"):
        parse([a_question(options=many)])


def test_too_many_questions_is_refused():
    with pytest.raises(MalformedQuestions, match="too many"):
        parse([a_question() for _ in range(forms.MAX_QUESTIONS + 1)])


def test_an_empty_list_is_refused():
    with pytest.raises(MalformedQuestions, match="empty"):
        parse([])


def test_a_missing_question_is_refused_by_number():
    with pytest.raises(MalformedQuestions, match="question 2"):
        parse([a_question(), a_question(question="")])


def test_a_long_header_is_trimmed_not_refused():
    [question] = parse([a_question(header="An extremely long tab label here")])
    assert len(question.header) <= forms.MAX_HEADER


def test_a_missing_header_falls_back_to_the_prompt():
    [question] = parse([a_question(header="")])
    assert question.header
    assert len(question.header) <= forms.MAX_HEADER


def test_duplicate_headers_are_made_distinct():
    """Two tabs with one name are two tabs the user cannot tell apart."""
    first, second = parse([a_question(), a_question(question="And for tests?")])
    assert first.header != second.header


# --------------------------------------------------------------------------- #
# crossing the wire
# --------------------------------------------------------------------------- #


def test_a_form_survives_a_round_trip():
    questions = parse([a_question(), a_question(question="Keep the old API?",
                                                header="Old API")])
    back = decode(json.loads(json.dumps(encode(questions))))
    assert [q.prompt for q in back] == [q.prompt for q in questions]
    assert [len(q.options) for q in back] == [len(q.options) for q in questions]
    assert back[0].options[-1].free


def test_answers_survive_a_round_trip():
    given = [Answer(header="Database", prompt="Which?", chosen=["SQLite"]),
             Answer(header="Old API", prompt="Keep?", written="for one release")]
    back = decode_answers(encode_answers(given))
    assert back is not None
    assert back[0].chosen == ["SQLite"]
    assert back[1].written == "for one release"


@pytest.mark.parametrize("raw", ["", CANCELLED, "no", "deny", "not json at all",
                                 '{"not": "a list"}'])
def test_a_dismissed_form_is_none_not_an_empty_list(raw):
    """The two mean different things and the tool acts on the difference."""
    assert decode_answers(raw) is None


def test_a_form_answered_with_nothing_is_an_empty_list():
    assert decode_answers(encode_answers([])) == []


# --------------------------------------------------------------------------- #
# what the model reads back
# --------------------------------------------------------------------------- #


def test_the_summary_keeps_the_question_with_its_answer():
    questions = parse([a_question()])
    text = summarise(questions, [Answer(header=questions[0].header,
                                        prompt=questions[0].prompt,
                                        chosen=["SQLite"])])
    assert "Which database should this use?" in text
    assert "SQLite" in text


def test_a_skipped_question_is_named_as_skipped():
    """Left out, it reads as an oversight and gets filled with an assumption."""
    questions = parse([a_question(), a_question(question="Keep the old API?",
                                                header="Old API")])
    text = summarise(questions, [Answer(header=questions[0].header,
                                        prompt=questions[0].prompt,
                                        chosen=["SQLite"])])
    assert "Keep the old API?" in text
    assert "unanswered" in text.lower()


def test_a_written_answer_appears_in_the_summary():
    questions = parse([a_question()])
    text = summarise(questions, [Answer(header=questions[0].header,
                                        prompt=questions[0].prompt,
                                        written="DuckDB, actually")])
    assert "DuckDB, actually" in text


# --------------------------------------------------------------------------- #
# the tool
# --------------------------------------------------------------------------- #


@pytest.fixture
def context_on(config):
    """A tool context bound to a bus the test controls.

    The shared `tool_context` fixture holds a bus of its own, and these tests
    need to subscribe to the one the tool will publish on before it does.
    """
    from comodor.events import Cancellation
    from comodor.safety import CheckpointStore, PermissionEngine, Redactor
    from comodor.tools.base import ToolContext

    def build(bus):
        return ToolContext(
            config=config,
            permissions=PermissionEngine(config, bus),
            checkpoints=CheckpointStore(config.paths.checkpoints),
            bus=bus,
            redact=Redactor([]),
            cancel=Cancellation(),
            cwd=config.paths.project,
        )

    return build


class _Answerer:
    """Stands in for an interface: answers the first request it sees."""

    def __init__(self, reply):
        self.reply = reply
        self.seen = []

    def __call__(self, event):
        if event.kind is not Kind.REQUEST:
            return
        request = event.payload["request"]
        self.seen.append(request)
        request.answer(self.reply(request) if callable(self.reply) else self.reply)


def _run(context_on, reply, args):
    bus = EventBus()
    answerer = _Answerer(reply)
    bus.subscribe(answerer)
    ctx = context_on(bus)
    result = Ask().run(ctx, **args)
    return result, answerer


def test_the_tool_asks_and_reads_the_answer(context_on):
    def reply(request):
        questions = decode(request.meta["questions"])
        return encode_answers([Answer(header=questions[0].header,
                                      prompt=questions[0].prompt,
                                      chosen=["SQLite"])])

    result, answerer = _run(context_on, reply, {"questions": [a_question()]})
    assert result.ok
    assert "SQLite" in result.content
    assert answerer.seen[0].kind == "questions"


def test_the_request_carries_no_options(context_on):
    """A JSON answer would fail an interface's membership check against them."""
    _, answerer = _run(context_on, CANCELLED, {"questions": [a_question()]})
    assert answerer.seen[0].options == []


def test_a_dismissed_form_tells_the_model_to_carry_on(context_on):
    result, _ = _run(context_on, CANCELLED, {"questions": [a_question()]})
    assert result.ok, "dismissing a form is not a tool failure"
    assert result.meta["answered"] is False
    assert "do not ask again" in result.content.lower()


def test_malformed_questions_come_back_as_a_usable_error(context_on):
    result, _ = _run(context_on, CANCELLED,
                     {"questions": [a_question(options=[{"label": "one"}])]})
    assert not result.ok
    assert "question 1" in result.content


def test_the_tool_is_safe_so_it_works_while_planning():
    from comodor.safety import Risk

    assert Ask.risk is Risk.SAFE


def test_the_tool_is_offered_by_default():
    from comodor.tools.registry import DEFAULT_TOOLS

    assert Ask in DEFAULT_TOOLS


# --------------------------------------------------------------------------- #
# the glyphs a terminal form draws with, in both glyph sets
# --------------------------------------------------------------------------- #


def test_every_glyph_the_form_uses_exists_in_both_sets():
    from comodor.terminal.theme import ASCII_GLYPHS, Glyphs

    for name in ("ticked", "unticked", "arrow", "rise", "fall", "left",
                 "right", "dot"):
        assert getattr(Glyphs(), name)
        assert getattr(ASCII_GLYPHS, name)


# --------------------------------------------------------------------------- #
# the two threads
# --------------------------------------------------------------------------- #


def test_the_worker_is_released_when_the_form_is_answered(context_on):
    """The agent thread blocks on this; a form nobody answers must not wedge it."""
    bus = EventBus()
    held = []
    bus.subscribe(lambda event: held.append(event.payload["request"])
                  if event.kind is Kind.REQUEST else None)

    ctx = context_on(bus)
    out = {}
    worker = threading.Thread(
        target=lambda: out.update(result=Ask().run(ctx, questions=[a_question()])))
    worker.start()

    deadline = threading.Event()
    while not held and not deadline.wait(0.02):
        pass
    held[0].answer(encode_answers([Answer(header=held[0].meta["questions"][0]["header"],
                                          prompt="Which database should this use?",
                                          chosen=["SQLite"])]))
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert out["result"].ok
