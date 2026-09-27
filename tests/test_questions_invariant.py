"""The custom-answer invariant, adversarially (T029; FR-017, SC-005).

Whatever the model authors — "Other", "None of the above", "Custom", several
of them, in any case, with punctuation — exactly one write-your-own row
survives, appended centrally, last, and flagged `free`. The guard is
`questions._options`; the mutation check removes it and watches the
invariant fail.
"""

from __future__ import annotations

import itertools
import random

import pytest

from comodor import questions as forms

HATCHES = ["Other", "other", "OTHER", "Others", "Something else", "Custom",
           "None of these", "None of the above", "Let me write", "I'll write",
           "I will write my own", "Type my own", "My own answer", "Write your own",
           "Other…", "Other.", " custom "]
REAL = ["SQLite", "PostgreSQL", "MySQL", "DuckDB"]


def _forms(seed: int, count: int = 200):
    rng = random.Random(seed)
    for _ in range(count):
        real = rng.sample(REAL, rng.randint(2, 4))
        hatches = rng.sample(HATCHES, rng.randint(0, 3))
        options = real + hatches
        rng.shuffle(options)
        # A model-authored hatch may even carry `free: true` itself.
        rows = [{"label": label, "free": rng.random() < 0.3} if label in hatches
                else {"label": label} for label in options]
        yield rows


@pytest.mark.parametrize("seed", range(5))
def test_exactly_one_free_row_survives_and_it_is_the_appended_one(seed):
    for rows in _forms(seed):
        parsed = forms.parse([{"question": "Which?", "header": "Which",
                               "options": rows}])
        options = parsed[0].options
        free = [option for option in options if option.free]
        assert len(free) == 1
        assert options[-1] is free[0]
        assert options[-1].label == forms.WRITE_YOUR_OWN
        # Every real option survived, in order, and no hatch did.
        labels = [option.label for option in options[:-1]]
        assert labels == [row["label"] for row in rows
                          if not forms._is_an_escape_hatch(row["label"])]
        assert not any(forms._is_an_escape_hatch(label) for label in labels)


def test_every_spelling_the_guard_knows_is_stripped():
    for hatch in HATCHES:
        parsed = forms.parse([{"question": "Which?", "header": "W",
                               "options": ["SQLite", "PostgreSQL", hatch]}])
        assert [o.label for o in parsed[0].options] == ["SQLite", "PostgreSQL",
                                                        forms.WRITE_YOUR_OWN]


def test_a_form_of_only_hatches_is_refused_not_shown():
    with pytest.raises(forms.MalformedQuestions):
        forms.parse([{"question": "Which?", "header": "W",
                      "options": ["Other", "Custom", "None of the above"]}])


def test_the_row_survives_encode_decode_and_a_free_flag_from_the_wire_is_not_a_second_row():
    parsed = forms.parse([{"question": "Which?", "header": "W",
                           "options": ["SQLite", "PostgreSQL"]}])
    wire = forms.encode(parsed)
    back = forms.decode(wire)
    assert sum(option.free for option in back[0].options) == 1
    assert back[0].options[-1].label == forms.WRITE_YOUR_OWN


def test_the_guard_is_the_stripping_in_options(monkeypatch):
    """Mutation check: with the hatch filter removed, two free-looking rows
    reach the person — the invariant fails and this catches it."""
    real = forms._is_an_escape_hatch
    monkeypatch.setattr(forms, "_is_an_escape_hatch", lambda label: False)
    parsed = forms.parse([{"question": "Which?", "header": "W",
                           "options": ["SQLite", "Other"]}])
    labels = [option.label for option in parsed[0].options]
    assert "Other" in labels and forms.WRITE_YOUR_OWN in labels, \
        "the mutation lets a model-authored hatch through"

    monkeypatch.setattr(forms, "_is_an_escape_hatch", real)
    parsed = forms.parse([{"question": "Which?", "header": "W",
                           "options": ["SQLite", "PostgreSQL", "Other"]}])
    assert [option.label for option in parsed[0].options] == \
        ["SQLite", "PostgreSQL", forms.WRITE_YOUR_OWN]


def test_the_append_itself_is_a_guard(monkeypatch):
    """Mutation check: without the append there is no way out at all."""
    original = forms._options

    def without_the_row(raw, where):
        options = original(raw, where)
        return [option for option in options if not option.free]

    monkeypatch.setattr(forms, "_options", without_the_row)
    parsed = forms.parse([{"question": "Which?", "header": "W",
                           "options": ["SQLite", "PostgreSQL"]}])
    assert not any(option.free for option in parsed[0].options)
    monkeypatch.setattr(forms, "_options", original)
    parsed = forms.parse([{"question": "Which?", "header": "W",
                           "options": ["SQLite", "PostgreSQL"]}])
    assert parsed[0].options[-1].free is True


def test_headers_and_positions_do_not_disturb_the_row():
    questions = [{"question": f"Q{i}?", "header": f"H{i}",
                  "options": list(itertools.islice(itertools.cycle(REAL), 2 + i % 3))}
                 for i in range(4)]
    for question in forms.parse(questions):
        assert question.options[-1].free is True
        assert sum(option.free for option in question.options) == 1
