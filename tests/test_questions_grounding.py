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
