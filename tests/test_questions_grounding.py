"""Grounded candidates, and the empty-candidate case (T031, T032; FR-015–FR-017).

Every option the person sees traces to the request, a file this turn read, a
setting, a recalled item or a derivation from one of those. An option the
tool cannot confirm is dropped — never shown as if it were grounded — and a
question may end with no candidate at all, in which case the write-your-own
row still makes it answerable.
"""

from __future__ import annotations

import pytest

from comodor import questions as forms
from comodor.events import Cancellation, EventBus, Kind
from comodor.safety import CheckpointStore, PermissionEngine, Redactor
from comodor.tools.ask import Ask, ground
from comodor.tools.base import ToolContext


@pytest.fixture
def context(config):
    bus = EventBus()
    made = ToolContext(config=config, permissions=PermissionEngine(config, bus),
                       checkpoints=CheckpointStore(config.paths.checkpoints),
                       bus=bus, redact=Redactor([]), cancel=Cancellation(),
                       cwd=config.paths.project,
                       request_text="Add caching to the pricing client, in Redis or in memory.")
    return made


def _seen_form(context):
    seen = []
    context.bus.subscribe(lambda event: (seen.append(event.payload["request"]),
                                         event.payload["request"].answer(forms.CANCELLED))
                          if event.kind is Kind.REQUEST else None)
    return seen


def _labels(request):
    return [option["label"] for option in request.meta["questions"][0]["options"]]


def test_an_option_named_in_the_request_is_grounded(context):
    seen = _seen_form(context)
    Ask().run(context, questions=[{
        "question": "Where should the cache live?", "header": "Cache",
        "options": [{"label": "Redis", "source": "request", "evidence": "in Redis"},
                    {"label": "In memory", "source": "request", "evidence": "in memory"}]}])
    assert _labels(seen[0]) == ["Redis", "In memory", forms.WRITE_YOUR_OWN]
    assert all(option["grounded"] for option in seen[0].meta["questions"][0]["options"][:-1])


def test_an_option_the_request_never_mentions_is_dropped(context):
    seen = _seen_form(context)
    Ask().run(context, questions=[{
        "question": "Where should the cache live?", "header": "Cache",
        "options": [{"label": "Redis", "source": "request", "evidence": "in Redis"},
                    {"label": "Memcached", "source": "request", "evidence": "Memcached"}]}])
    assert _labels(seen[0]) == ["Redis", forms.WRITE_YOUR_OWN]


def test_an_option_from_a_file_this_turn_read_is_grounded(context):
    target = context.config.paths.project / "settings.py"
    target.write_text("CACHE_BACKEND = 'redis'\n", encoding="utf-8")
    context.note_read(target, material=target.read_text(encoding="utf-8"))
    seen = _seen_form(context)
    Ask().run(context, questions=[{
        "question": "Which backend?", "header": "Backend",
        "options": [{"label": "redis (as settings.py has)", "source": "configuration",
                     "evidence": "settings.py"},
                    {"label": "memcached", "source": "configuration",
                     "evidence": "config/cache.yml"}]}])
    assert _labels(seen[0]) == ["redis (as settings.py has)", forms.WRITE_YOUR_OWN]


def test_an_option_from_a_file_nobody_read_is_not_grounded(context):
    seen = _seen_form(context)
    Ask().run(context, questions=[{
        "question": "Which backend?", "header": "Backend",
        "options": [{"label": "redis", "source": "repository", "evidence": "settings.py"},
                    {"label": "memcached", "source": "repository", "evidence": "cache.yml"}]}])
    assert _labels(seen[0]) == [forms.WRITE_YOUR_OWN]


def test_a_source_that_does_not_establish_the_candidate_does_not_ground_it(context):
    """A file being read is not evidence that it names the candidate.

    The path was read this turn, but nothing in it supports the option; a
    candidate that merely shares a turn with an unrelated file is not
    grounded, and must not be shown as if it were.
    """
    target = context.config.paths.project / "README.md"
    target.write_text("# Project\n\nA small caching service.\n", encoding="utf-8")
    context.note_read(target, material=target.read_text(encoding="utf-8"))

    kept = ground([forms.Option(label="PostgreSQL", source="repository",
                                evidence="README.md")], context)
    assert kept == [], "README.md never mentions PostgreSQL"


def test_a_source_that_establishes_the_candidate_grounds_it(context):
    target = context.config.paths.project / "README.md"
    target.write_text("Everything is stored in PostgreSQL.\n", encoding="utf-8")
    context.note_read(target, material=target.read_text(encoding="utf-8"))

    kept = ground([forms.Option(label="PostgreSQL", source="repository",
                                evidence="README.md")], context)
    assert [option.label for option in kept] == ["PostgreSQL"]


def test_a_read_from_an_earlier_turn_does_not_ground_this_one(context):
    """`seen` outlives the turn on purpose; grounding does not use it."""
    target = context.config.paths.project / "README.md"
    target.write_text("Everything is stored in PostgreSQL.\n", encoding="utf-8")
    context.note_read(target, material=target.read_text(encoding="utf-8"))
    assert context.was_read(target) is True

    context.reset_evidence()             # the next turn starts here

    kept = ground([forms.Option(label="PostgreSQL", source="repository",
                                evidence="README.md")], context)
    assert kept == [], "a previous turn's read is not this turn's evidence"


def test_a_verified_claim_that_establishes_the_candidate_grounds_it(context):
    """A claim this turn established backs a candidate the same way a read does."""
    context.evidence.verified("deployments run PostgreSQL 16",
                              source="grep:deploy")

    kept = ground([forms.Option(label="PostgreSQL", source="repository",
                                evidence="deployments run PostgreSQL 16")], context)
    assert [option.label for option in kept] == ["PostgreSQL"]


def test_an_option_from_recalled_knowledge_is_grounded(context):
    context.recalled = ["deployments: this project always caches in Redis"]
    seen = _seen_form(context)
    Ask().run(context, questions=[{
        "question": "Which backend?", "header": "Backend",
        "options": [{"label": "Redis", "source": "knowledge",
                     "evidence": "caches in Redis"},
                    {"label": "Varnish", "source": "knowledge", "evidence": "Varnish"}]}])
    assert _labels(seen[0]) == ["Redis", forms.WRITE_YOUR_OWN]


def test_a_source_the_table_does_not_know_is_not_grounded(context):
    assert ground([forms.Option(label="Redis", source="imagination",
                                evidence="in Redis")], context) == []


def test_an_undeclared_source_is_checked_against_the_request_only(context):
    kept = ground([forms.Option(label="Redis"), forms.Option(label="Varnish")], context)
    assert [option.label for option in kept] == ["Redis"]


def test_the_empty_candidate_case_keeps_the_custom_row_and_asks(context):
    """No alternative could be grounded: the form still goes out, with the
    write-your-own row alone (T032)."""
    seen = _seen_form(context)
    result = Ask().run(context, questions=[{
        "question": "Which backend?", "header": "Backend",
        "options": [{"label": "Varnish"}, {"label": "Squid"}]}])
    assert len(seen) == 1
    options = seen[0].meta["questions"][0]["options"]
    assert [option["label"] for option in options] == [forms.WRITE_YOUR_OWN]
    assert options[0]["free"] is True
    assert result.meta["answered"] is False


def test_grounded_is_set_by_the_tool_never_by_the_model(context):
    kept = ground([forms.Option(label="Varnish", grounded=True)], context)
    assert kept == []
    kept = ground([forms.Option(label="Redis", grounded=False)], context)
    assert kept[0].grounded is True


def test_the_free_row_is_always_kept_and_is_never_grounded_by_provenance(context):
    row = forms.Option(label=forms.WRITE_YOUR_OWN, free=True)
    assert ground([row], context) == [row]
    assert row.grounded is False


def test_the_form_carries_why_and_what_was_checked(context):
    """FR-034: `reason` names the materiality class; `evidence_consulted`
    names what this turn already observed."""
    target = context.config.paths.project / "settings.py"
    target.write_text("x = 1\n", encoding="utf-8")
    context.note_read(target, material="x = 1\n")
    seen = _seen_form(context)
    Ask().run(context, questions=[{
        "question": "Where should the cache live?", "header": "Cache",
        "affects": ["architecture"],
        "options": [{"label": "Redis", "source": "request", "evidence": "in Redis"},
                    {"label": "In memory", "source": "request", "evidence": "in memory"}]}])
    question = seen[0].meta["questions"][0]
    assert question["reason"] == "architecture"
    assert "settings.py" in question["evidence_consulted"]
    assert question["decision_ref"].startswith("d")


def test_grounding_matches_words_not_substrings():
    """A candidate is grounded by the words that were said, not by a substring.

    "Go" is inside "Django"; a substring test would present an unmentioned
    option as grounded by the request.
    """
    from comodor.tools.ask import _mentioned

    assert not _mentioned("Go", "Use Django for the server")
    assert not _mentioned("Go", "the cargo toolchain")
    assert _mentioned("Django", "Use Django for the server")
    assert _mentioned("SQLite", "we could use sqlite here")
    assert _mentioned("PostgreSQL", "Postgres, but not PostgreSQL yet")


def test_a_bounded_window_this_turn_read_grounds_a_candidate(context):
    """A partial read is an observation of its window: a candidate inside it is
    grounded; one outside it is not (FR-015, FR-016)."""
    target = context.config.paths.project / "big.py"
    target.write_text("first line\nUSE_POSTGRES = True\nlast line\n", encoding="utf-8")
    context.note_window(target, material="first line\nUSE_POSTGRES = True\n")

    inside = ground([forms.Option(label="USE_POSTGRES", source="repository",
                                  evidence="big.py")], context)
    outside = ground([forms.Option(label="Redis", source="repository",
                                   evidence="big.py")], context)

    assert [option.label for option in inside] == ["USE_POSTGRES"]
    assert outside == []


def test_a_partial_read_from_an_earlier_turn_does_not_ground(context):
    target = context.config.paths.project / "big.py"
    target.write_text("USE_POSTGRES = True\n", encoding="utf-8")
    context.note_window(target, material="USE_POSTGRES = True\n")

    context.reset_evidence()

    kept = ground([forms.Option(label="USE_POSTGRES", source="repository",
                                evidence="big.py")], context)
    assert kept == []


def test_a_partial_read_records_the_window_it_saw(tools, tool_context):
    """The read tool's bounded window is what grounds a candidate found in it;
    removing that recording drops the option (FR-015, FR-016)."""
    target = tool_context.config.paths.project / "big.py"
    target.write_text("USE_POSTGRES = True\n"
                      + "\n".join(f"line {n}" for n in range(80)), encoding="utf-8")

    tools.invoke("read_file", tool_context, {"path": "big.py", "offset": 1, "limit": 2})

    kept = ground([forms.Option(label="USE_POSTGRES", source="repository",
                                evidence="big.py")], tool_context)
    assert [option.label for option in kept] == ["USE_POSTGRES"]


def test_a_non_material_question_is_not_put_to_the_person(context):
    """`affects: []` is the ledger's own statement that nothing material is
    at stake, so it is the agent's to decide and never interrupts the user
    (FR-003, FR-011)."""
    seen = _seen_form(context)

    result = Ask().run(context, questions=[{
        "question": "Which helper name?", "header": "Name", "affects": [],
        "options": [{"label": "Redis", "source": "request", "evidence": "Redis"},
                    {"label": "In memory", "source": "request", "evidence": "in memory"}]}])


    assert seen == [], "no form is raised for an immaterial decision"
    assert result.meta.get("answered") is False
    assert "yours to decide" in result.content


def test_a_mixed_batch_names_the_discretion_question_after_the_form(context):
    """One material and one immaterial question: the form shows only the
    material one, and the result still names the other as the model's to
    decide and report (review 4045639923)."""
    seen = _seen_form(context)

    result = Ask().run(context, questions=[
        {"question": "Which cache?", "header": "Cache", "affects": ["architecture"],
         "options": [{"label": "Redis", "source": "request", "evidence": "Redis"},
                     {"label": "In memory", "source": "request", "evidence": "in memory"}]},
        {"question": "Which helper name?", "header": "Name", "affects": [],
         "options": [{"label": "Redis", "source": "request", "evidence": "Redis"},
                     {"label": "In memory", "source": "request", "evidence": "in memory"}]},
    ])

    assert len(seen) == 1
    assert [q["header"] for q in seen[0].meta["questions"]] == ["Cache"]
    assert "yours to decide" in result.content
    assert "Which helper name?" in result.content
    assert result.meta["discretion"] == ["Which helper name?"]


def test_a_mixed_batch_answered_still_names_the_discretion_question(context):
    from comodor import questions as forms_module

    def answer(event):
        if event.kind is Kind.REQUEST:
            event.payload["request"].answer(forms_module.encode_answers([
                forms_module.Answer(header="Cache", prompt="", chosen=["Redis"])]))

    context.bus.subscribe(answer)
    result = Ask().run(context, questions=[
        {"question": "Which cache?", "header": "Cache", "affects": ["architecture"],
         "options": [{"label": "Redis", "source": "request", "evidence": "Redis"},
                     {"label": "In memory", "source": "request", "evidence": "in memory"}]},
        {"question": "Which helper name?", "header": "Name", "affects": [],
         "options": [{"label": "Redis", "source": "request", "evidence": "Redis"},
                     {"label": "In memory", "source": "request", "evidence": "in memory"}]},
    ])

    assert result.meta["given"] == 1
    assert "Which helper name?" in result.content and "yours to decide" in result.content
