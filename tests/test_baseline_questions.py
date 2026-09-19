"""Characterization: the shared question flow as it stands (T006).

The custom-answer invariant, header binding and both answer shapes are
enforced in `questions.py` — one layer that every surface renders. Spec 002
keeps all of it (FR-016, FR-017, FR-020, FR-021) and changes only what
happens when *no* answer comes back, so what comes back today is pinned here
too: the tool tells the model to choose sensible defaults. That sentence is
the behaviour FR-082 removes, and it is recorded before it goes.

The Web UI half of T006 lives in `tests/test_web.py` (the authoritative Web
suite) under "the question form, characterized".
"""

from __future__ import annotations

import pytest

from comodor import questions as forms
from comodor.events import Cancellation, EventBus, Kind
from comodor.safety import CheckpointStore, PermissionEngine, Redactor
from comodor.tools.ask import Ask
from comodor.tools.base import ToolContext


def a_question(**overrides):
    question = {
        "question": "Which database should this use?",
        "header": "Database",
        "options": [{"label": "SQLite", "description": "one file"},
                    {"label": "PostgreSQL", "description": "a server"}],
    }
    question.update(overrides)
    return question


@pytest.fixture
def context_on(config):
    def build(bus):
        return ToolContext(config=config, permissions=PermissionEngine(config, bus),
                           checkpoints=CheckpointStore(config.paths.checkpoints),
                           bus=bus, redact=Redactor([]), cancel=Cancellation(),
                           cwd=config.paths.project,
            # The request names every candidate used below, so the options
            # are grounded (FR-016) and reach the form.
            request_text=("Which database, SQLite or PostgreSQL? Which "
                          "language, Python or Go?"))
    return build


def _run(context_on, reply, args):
    """Run the real tool against a bus whose one subscriber answers `reply`."""
    bus = EventBus()
    seen = []

    def answer(event):
        if event.kind is Kind.REQUEST:
            request = event.payload["request"]
            seen.append(request)
            request.answer(reply(request) if callable(reply) else reply)

    bus.subscribe(answer)
    return Ask().run(context_on(bus), **args), seen


# --------------------------------------------------------------------------- #
# the custom-answer invariant, enforced centrally
# --------------------------------------------------------------------------- #


def test_options_appends_exactly_one_free_row_last():
    parsed = forms.parse([a_question()])
    options = parsed[0].options
    assert [option.free for option in options] == [False, False, True]
    assert options[-1].label == forms.WRITE_YOUR_OWN


@pytest.mark.parametrize("hatch", ["Other", "Something else", "None of the above",
                                   "custom", "Let me write", "other…"])
def test_a_model_authored_escape_hatch_is_stripped_before_the_row_is_appended(hatch):
    parsed = forms.parse([a_question(options=[
        {"label": "SQLite"}, {"label": "PostgreSQL"}, {"label": hatch}])])
    labels = [option.label for option in parsed[0].options]
    assert labels == ["SQLite", "PostgreSQL", forms.WRITE_YOUR_OWN]
    assert sum(option.free for option in parsed[0].options) == 1


def test_the_free_row_survives_encoding_for_every_surface():
    parsed = forms.parse([a_question()])
    wire = forms.encode(parsed)
    last = wire[0]["options"][-1]
    assert last["label"] == forms.WRITE_YOUR_OWN and last["free"] is True
    assert last["description"] == ""
    back = forms.decode(wire)
    assert back[0].options[-1].free is True


def test_the_request_the_tool_raises_carries_the_free_row(context_on):
    _, seen = _run(context_on, forms.CANCELLED, {"questions": [a_question()]})
    assert seen[0].kind == "questions"
    assert seen[0].options == []
    carried = seen[0].meta["questions"][0]["options"]
    assert carried[-1]["free"] is True
    assert [entry["label"] for entry in carried] == ["SQLite", "PostgreSQL",
                                                     forms.WRITE_YOUR_OWN]


# --------------------------------------------------------------------------- #
# answers bind by header, and both shapes round-trip
# --------------------------------------------------------------------------- #


def test_a_single_choice_answer_round_trips_to_the_model(context_on):
    def reply(request):
        question = forms.decode(request.meta["questions"])[0]
        return forms.encode_answers([forms.Answer(header=question.header,
                                                  prompt=question.prompt,
                                                  chosen=["PostgreSQL"])])

    result, _ = _run(context_on, reply, {"questions": [a_question()]})
    assert result.ok and result.meta["answered"] is True
    assert "PostgreSQL" in result.content and result.meta["given"] == 1


def test_a_multi_choice_answer_round_trips_with_every_choice(context_on):
    def reply(request):
        question = forms.decode(request.meta["questions"])[0]
        return forms.encode_answers([forms.Answer(header=question.header,
                                                  prompt=question.prompt,
                                                  chosen=["SQLite", "PostgreSQL"])])

    result, _ = _run(context_on, reply, {"questions": [a_question(multi=True)]})
    assert "SQLite, PostgreSQL" in result.content


def test_a_written_answer_round_trips(context_on):
    def reply(request):
        question = forms.decode(request.meta["questions"])[0]
        return forms.encode_answers([forms.Answer(header=question.header,
                                                  prompt=question.prompt,
                                                  written="DuckDB, actually")])

    result, _ = _run(context_on, reply, {"questions": [a_question()]})
    assert "DuckDB, actually" in result.content


def test_answers_match_by_header_not_by_position(context_on):
    two = [a_question(), a_question(question="Which language?", header="Language",
                                    options=[{"label": "Python"}, {"label": "Go"}])]

    def reply(request):
        questions = forms.decode(request.meta["questions"])
        # Sent back in the opposite order to the one asked.
        return forms.encode_answers([
            forms.Answer(header=questions[1].header, prompt="", chosen=["Go"]),
            forms.Answer(header=questions[0].header, prompt="", chosen=["SQLite"]),
        ])

    result, _ = _run(context_on, reply, {"questions": two})
    assert "Which database should this use?\n  -> SQLite" in result.content
    assert "Which language?\n  -> Go" in result.content


def test_an_answer_for_an_unknown_header_leaves_the_question_unanswered(context_on):
    def reply(request):
        return forms.encode_answers([forms.Answer(header="Nope", prompt="",
                                                  chosen=["SQLite"])])

    result, _ = _run(context_on, reply, {"questions": [a_question()]})
    assert "Left unanswered" in result.content
    assert "SQLite" not in result.content.split("Left unanswered")[0]
    # `given` counts answers as sent, not answers that matched a question —
    # pinned as-is; the summary is what the model reads.
    assert result.meta["given"] == 1


# --------------------------------------------------------------------------- #
# the starting point for FR-082: what a no-answer produces *today*
# --------------------------------------------------------------------------- #


def test_a_dismissed_form_no_longer_tells_the_model_to_choose_defaults(context_on):
    """Before spec 002 this returned "Choose sensible defaults, carry on" —
    the behaviour FR-082 removes. Now the decision stays open."""
    result, _ = _run(context_on, forms.CANCELLED, {"questions": [a_question()]})
    assert result.ok
    assert result.meta["answered"] is False
    assert result.meta["outcome"] == "cancelled"
    assert "sensible defaults" not in result.content.lower()
    assert "remain unresolved" in result.content


def test_an_expired_form_is_told_apart_from_a_dismissed_one(context_on, monkeypatch):
    """`bus.resolve` says it expired; the tool used to discard that flag."""
    from comodor.tools import ask as ask_tool

    monkeypatch.setattr(ask_tool, "WAIT_FOR", 0.0)
    bus = EventBus()
    bus.subscribe(lambda event: None)          # somebody listening, nobody answering
    result = Ask().run(context_on(bus), questions=[a_question()])
    assert result.meta["answered"] is False
    assert result.meta["outcome"] == "expired"
    assert "expired" in result.content
    assert "sensible defaults" not in result.content.lower()


def test_the_decoder_reads_every_dismissal_spelling_as_none():
    for raw in ("", forms.CANCELLED, "no", "deny", "not json", "{}"):
        assert forms.decode_answers(raw) is None
    assert forms.decode_answers("[]") == []
