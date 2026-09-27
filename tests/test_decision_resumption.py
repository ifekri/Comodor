"""Resuming a decision in a later invocation, by its `decision_ref` (FR-129).

A decision the agent stopped for is answered later by one structured input,
keyed by the decision's minted ref, and resolved by exact lookup only — never
by recency, position, wording or first-open order. Everything that crosses an
invocation belongs to `application.run_turn`; the loop stays the loop.

T175 lookup and derivation · T180 the turn contract · T200 binding · T176
lifecycle · T181 validation order and atomicity · T193 privacy and security ·
T205 every primary entry reaches `run_turn` · T206 the SC-042 replay.
"""

from __future__ import annotations

import copy as _copy
import json as _json
import re as _re

import pytest

from comodor.agent import AgentLoop, Conversation
from comodor.application import Binding, DecisionRejected, run_turn
from comodor.events import EventBus
from comodor.providers.base import Message, ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.session.store import SessionMeta, SessionStore, UnresolvableRef, decision_states
from comodor.tools import ToolRegistry


def _form(ref: str, outcome: str, *, answer: str = "", header: str = "Database",
          prompt: str = "Which database?") -> Message:
    message = Message.tool(call_id=f"c-{ref}-{outcome}", name="ask", content="…")
    message.meta["question"] = {
        "questions": [{"prompt": prompt, "header": header, "multi": False,
                       "options": [{"label": "SQLite"}, {"label": "PostgreSQL"},
                                   {"label": "Write your own", "free": True}],
                       "reason": "persisted_state", "decision_ref": ref}],
        "answers": ([{"header": header, "chosen": [answer], "written": ""}]
                    if answer else []),
        "outcome": outcome, "origin": "model_ask",
        "state": "answered" if outcome == "answered" else "unresolved",
    }
    return message


def _store(config) -> SessionStore:
    return SessionStore(config.paths.user / "sessions")


def _continuation(store: SessionStore, session_id: str, refs: list[str],
                  records: list[Message], *, mode: str = "act", cwd: str = "/w") -> None:
    store.save_meta(SessionMeta(id=session_id, cwd=cwd,
                                continuation={"decision_refs": refs, "mode": mode}))
    for message in records:
        store.append(session_id, message)


# --------------------------------------------------------------------------- #
# T175 — exact lookup, and open / stale / unknown from the form records
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("ending", ["cancelled", "expired", "unattended"])
def test_a_ref_whose_latest_record_ended_without_an_answer_is_open(ending):
    states = decision_states([_form("ref-1", ending)])
    assert states["ref-1"].status == "open"
    assert states["ref-1"].question["prompt"] == "Which database?"


def test_a_ref_with_an_answer_on_record_is_stale_and_stays_stale():
    states = decision_states([_form("ref-1", "unattended"),
                              _form("ref-1", "answered", answer="SQLite"),
                              _form("ref-1", "cancelled")])
    assert states["ref-1"].status == "stale"


def test_a_ref_no_record_names_is_unknown_to_the_session():
    assert "ref-other" not in decision_states([_form("ref-1", "unattended")])


def test_a_blank_answer_is_not_an_answer():
    message = _form("ref-1", "cancelled")
    message.meta["question"]["answers"] = [{"header": "Database", "chosen": [],
                                            "written": "  "}]
    assert decision_states([message])["ref-1"].status == "open"


def test_find_continuation_is_exact_membership(config):
    store = _store(config)
    _continuation(store, "c-1", ["ref-1", "ref-2"], [_form("ref-1", "unattended")])
    assert store.find_continuation("ref-1").id == "c-1"
    assert store.find_continuation("ref-2").id == "c-1"
    # Neither a prefix, a suffix nor a near-miss of a ref resolves.
    for near in ("ref", "ref-", "ref-12", "REF-1", "ref-1 ", "ef-1"):
        assert store.find_continuation(near) is None


def test_a_deleted_continuations_ref_becomes_unknown(config):
    store = _store(config)
    _continuation(store, "c-1", ["ref-1"], [_form("ref-1", "unattended")])
    assert store.delete("c-1")
    assert store.find_continuation("ref-1") is None


def test_a_ref_two_continuations_claim_is_unresolvable_never_picked(config):
    store = _store(config)
    _continuation(store, "c-1", ["ref-1"], [_form("ref-1", "unattended")])
    _continuation(store, "c-2", ["ref-1"], [_form("ref-1", "unattended")])
    with pytest.raises(UnresolvableRef):
        store.find_continuation("ref-1")


def test_the_most_recent_continuation_has_no_say_in_the_result(config):
    store = _store(config)
    _continuation(store, "c-old", ["ref-old"], [_form("ref-old", "unattended")])
    _continuation(store, "c-new", ["ref-new"], [_form("ref-new", "unattended")])
    # The newer one is irrelevant to a ref it never issued.
    assert store.find_continuation("ref-old").id == "c-old"
    assert store.find_continuation("ref-new").id == "c-new"
    assert store.find_continuation("ref-unknown") is None


def test_an_ordinary_session_is_never_a_continuation_for_a_ref(config):
    store = _store(config)
    store.save_meta(SessionMeta(id="s-1"))
    store.append("s-1", _form("ref-1", "unattended"))
    assert store.find_continuation("ref-1") is None


def test_open_and_stale_are_read_from_the_transcript_not_the_meta(config):
    store = _store(config)
    _continuation(store, "c-1", ["ref-1", "ref-2"],
                  [_form("ref-1", "unattended"),
                   _form("ref-2", "unattended", header="Queue", prompt="Which queue?"),
                   _form("ref-1", "answered", answer="SQLite")])
    states = store.decisions("c-1")
    assert states["ref-1"].status == "stale"
    assert states["ref-2"].status == "open"


# --------------------------------------------------------------------------- #
# shared: a real loop with a scripted provider, stopping for one decision
# --------------------------------------------------------------------------- #



REQUEST = "Set up the database layer in db.py — SQLite or PostgreSQL?"


def _option(label: str) -> dict:
    return {"label": label, "source": "request", "evidence": label}


def _ask(*questions: tuple[str, str, list[str]], call_id: str = "q1") -> ToolCall:
    return ToolCall(id=call_id, name="ask", arguments={"questions": [
        {"question": prompt, "header": header, "affects": ["persistence"],
         "options": [_option(label) for label in labels]}
        for prompt, header, labels in questions]})


DATABASE = ("Which database?", "Database", ["SQLite", "PostgreSQL"])
QUEUE = ("Which queue?", "Queue", ["Redis", "RabbitMQ"])


def _write(path: str, content: str, call_id: str = "w1") -> ToolCall:
    return ToolCall(id=call_id, name="write_file",
                    arguments={"path": path, "content": content})


def _agent(config, scripts, bus=None):
    bus = bus or EventBus()
    gateway = Gateway(config, scripts=scripts)
    agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation())
    return agent, gateway


def _calls(gateway) -> int:
    return len(gateway.provider("fake").calls)


def _sessions(config) -> SessionStore:
    return SessionStore(config.paths.user / "sessions")


def _stop(config, *questions, request: str = REQUEST):
    """A fresh stateless run that stops, unattended, for `questions`."""
    agent, _ = _agent(config, [Script(text="A question first.",
                                      tool_calls=[_ask(*(questions or (DATABASE,)))]),
                               Script(text="unreachable")])
    store = _sessions(config)
    result = run_turn(agent, request, store=store, binding=Binding.of(config))
    assert result.stopped == "clarification_required"
    return result, store


def _refs(result) -> list[str]:
    return [entry["decision_ref"] for entry in result.clarification["decisions"]]


def _snapshot(store: SessionStore) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(store.root.iterdir())}


class _RecordingLoop:
    """The loop's input contract, recorded: what `run_turn` hands it."""

    def __init__(self, config, conversation=None):
        self.config = config
        self.conversation = conversation or Conversation()
        self.calls: list[tuple[str, dict]] = []

    def run(self, user_text, **kwargs):
        from comodor.agent.loop import TurnResult

        self.calls.append((user_text, kwargs))
        return TurnResult(text="ok")


class _SpyStore(SessionStore):
    def __init__(self, root):
        super().__init__(root)
        self.lookups: list[str] = []

    def find_continuation(self, decision_ref):
        self.lookups.append(decision_ref)
        return super().find_continuation(decision_ref)


# --------------------------------------------------------------------------- #
# T180 — run_turn: the loop's inputs unchanged, one new input
# --------------------------------------------------------------------------- #


def test_user_text_images_and_decisions_reach_the_loop_unchanged(config):
    loop = _RecordingLoop(config)
    images = ["data:image/png;base64,AAAA"]
    decisions = [{"kind": "clarification_required", "decision": "Which host?",
                  "decision_ref": "dr-delegate-1", "outcome": "unattended"}]
    before = _copy.deepcopy(decisions)
    run_turn(loop, "the user's words", images=images, decisions=decisions)
    ((text, kwargs),) = loop.calls
    assert text == "the user's words"
    assert kwargs["images"] is images and kwargs["decisions"] is decisions
    assert decisions == before
    assert "answered" not in kwargs


def test_a_caller_that_gives_neither_gets_the_plain_call(config):
    loop = _RecordingLoop(config)
    run_turn(loop, "hello")
    assert loop.calls == [("hello", {})]


def test_the_inputs_pass_through_unchanged_beside_decision_answers(config):
    result, store = _stop(config)
    loop = _RecordingLoop(config)
    images = ["data:image/png;base64,BBBB"]
    carried = [{"kind": "clarification_required", "decision": "Which host?",
                "decision_ref": "dr-delegate-2", "outcome": "cancelled"}]
    before = _copy.deepcopy(carried)
    run_turn(loop, "and also this", images=images, decisions=carried,
             decision_answers=[{"decision_ref": _refs(result)[0], "chosen": ["SQLite"]}],
             store=store, binding=Binding.of(config))
    ((text, kwargs),) = loop.calls
    assert text == "and also this"
    assert kwargs["images"] is images and kwargs["decisions"] is carried
    assert carried == before
    # The answers arrive as their own input, never folded into the others.
    assert kwargs["answered"]["outcome"] == "answered"


def test_case_a_carried_decisions_alone_trigger_no_lookup_and_stay_open(config):
    store = _SpyStore(config.paths.user / "sessions")
    carried = {"kind": "clarification_required", "decision": "Which host?",
               "decision_ref": "dr-delegate-3", "reason": "external_side_effect",
               "outcome": "unattended",
               "decisions": [{"id": "dr-delegate-3", "decision_ref": "dr-delegate-3",
                              "decision": "Which host?", "candidates": [],
                              "evidence_consulted": [],
                              "reason": "external_side_effect"}]}
    agent, gateway = _agent(config, [Script(text="Waiting on the host decision.")])
    result = run_turn(agent, "Deliver the delegate's report.",
                      decisions=[carried], store=store, binding=Binding.of(config))
    assert store.lookups == []
    decision = next(d for d in agent.tool_context.evidence.decisions
                    if d.ref == "dr-delegate-3")
    assert decision.state in ("unresolved", "blocked") and decision.answer == ""
    assert result.stopped == "clarification_required"
    assert _refs(result) == ["dr-delegate-3"]


def test_case_b_a_valid_batch_runs_the_exact_lookup_and_resumes(config):
    result, _ = _stop(config)
    ref = _refs(result)[0]
    store = _SpyStore(config.paths.user / "sessions")
    agent, gateway = _agent(config, [
        Script(text="Writing it.", tool_calls=[_write("db.py", "ENGINE = 'sqlite'\n")]),
        Script(text="Done — SQLite.")])
    resumed = run_turn(agent, "", decision_answers=[{"decision_ref": ref,
                                                     "chosen": ["SQLite"]}],
                       store=store, binding=Binding.of(config))
    assert store.lookups == [ref]
    assert resumed.stopped == "done"
    assert (config.paths.project / "db.py").read_text(encoding="utf-8") \
        == "ENGINE = 'sqlite'\n"
    decision = next(d for d in agent.tool_context.evidence.decisions if d.ref == ref)
    assert decision.state == "answered" and decision.answer == "SQLite"


def test_case_c_an_invalid_batch_is_refused_and_carried_decisions_untouched(config):
    _stop(config)
    store = _sessions(config)
    loop = _RecordingLoop(config)
    carried = [{"kind": "clarification_required", "decision": "Which host?",
                "decision_ref": "dr-delegate-4", "outcome": "cancelled"}]
    before = _copy.deepcopy(carried)
    with pytest.raises(DecisionRejected) as refused:
        run_turn(loop, "go", decisions=carried,
                 decision_answers=[{"decision_ref": "dr-never-minted", "chosen": ["x"]}],
                 store=store, binding=Binding.of(config))
    assert refused.value.kind == "unknown"
    assert loop.calls == []
    assert carried == before


def test_accepted_is_called_only_for_a_batch_that_passed(config):
    result, store = _stop(config)
    seen = []
    loop = _RecordingLoop(config)
    run_turn(loop, "", decision_answers=[{"decision_ref": _refs(result)[0],
                                          "chosen": ["SQLite"]}],
             store=store, binding=Binding.of(config), accepted=lambda: seen.append("ok"))
    assert seen == ["ok"]
    with pytest.raises(DecisionRejected):
        run_turn(_RecordingLoop(config), "", decision_answers="not json",
                 store=store, binding=Binding.of(config),
                 accepted=lambda: seen.append("wrong"))
    assert seen == ["ok"]


def test_a_live_session_resolves_against_its_own_conversation(config):
    """A session-backed caller passes no store: its conversation is its
    session. A ref from anywhere else is unknown to it."""
    agent, gateway = _agent(config, [
        Script(text="A question first.", tool_calls=[_ask(DATABASE)]),
        Script(text="unreachable")])
    stopped = run_turn(agent, REQUEST)
    ref = _refs(stopped)[0]

    other, _ = _stop(config)                     # a ref from another run
    with pytest.raises(DecisionRejected) as refused:
        run_turn(agent, "", decision_answers=[{"decision_ref": _refs(other)[0],
                                               "chosen": ["SQLite"]}])
    assert refused.value.kind == "unknown"

    gateway.provider("fake").scripts += [
        Script(text="Writing.", tool_calls=[_write("db.py", "ENGINE = 'sqlite'\n")]),
        Script(text="Done.")]
    resumed = run_turn(agent, "", decision_answers=[{"decision_ref": ref,
                                                     "chosen": ["SQLite"]}])
    assert resumed.stopped == "done"
    with pytest.raises(DecisionRejected) as again:
        run_turn(agent, "", decision_answers=[{"decision_ref": ref,
                                               "chosen": ["SQLite"]}])
    assert again.value.kind == "stale"


# --------------------------------------------------------------------------- #
# T200 — workspace and mode bind; provider and model do not
# --------------------------------------------------------------------------- #


def _resume_agent(config):
    return _agent(config, [
        Script(text="Writing it.", tool_calls=[_write("db.py", "ENGINE = 'sqlite'\n")]),
        Script(text="Done.")])


def test_same_workspace_and_mode_resumes(config):
    result, store = _stop(config)
    agent, _ = _resume_agent(config)
    resumed = run_turn(agent, "", decision_answers=[{"decision_ref": _refs(result)[0],
                                                     "chosen": ["SQLite"]}],
                       store=store, binding=Binding.of(config))
    assert resumed.stopped == "done"


def test_a_different_workspace_is_refused_before_the_model(config, tmp_path):
    result, store = _stop(config)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    before = _snapshot(store)
    agent, gateway = _resume_agent(config)
    with pytest.raises(DecisionRejected) as refused:
        run_turn(agent, "", decision_answers=[{"decision_ref": _refs(result)[0],
                                               "chosen": ["SQLite"]}],
                 store=store, binding=Binding(workspace=str(elsewhere.resolve()),
                                              mode="act"))
    assert refused.value.kind == "workspace"
    assert _calls(gateway) == 0 and agent.conversation.messages == []
    assert _snapshot(store) == before
    assert not (config.paths.project / "db.py").exists()


@pytest.mark.parametrize("mode", ["plan", "ask", "chat"])
def test_a_different_mode_is_refused_before_the_model(config, mode):
    result, store = _stop(config)
    before = _snapshot(store)
    agent, gateway = _resume_agent(config)
    with pytest.raises(DecisionRejected) as refused:
        run_turn(agent, "", decision_answers=[{"decision_ref": _refs(result)[0],
                                               "chosen": ["SQLite"]}],
                 store=store, binding=Binding(workspace=Binding.of(config).workspace,
                                              mode=mode))
    assert refused.value.kind == "mode"
    assert _calls(gateway) == 0 and _snapshot(store) == before


def test_an_unknown_mode_fails_closed(config):
    result, store = _stop(config)
    agent, gateway = _resume_agent(config)
    with pytest.raises(DecisionRejected) as refused:
        run_turn(agent, "", decision_answers=[{"decision_ref": _refs(result)[0],
                                               "chosen": ["SQLite"]}],
                 store=store, binding=Binding(workspace=Binding.of(config).workspace,
                                              mode="superuser"))
    assert refused.value.kind == "mode"
    assert _calls(gateway) == 0


def test_a_changed_model_and_provider_keep_the_ref_valid(config):
    from comodor.config import ProviderConfig

    result, store = _stop(config)
    config.providers["other"] = ProviderConfig(
        name="other", kind="fake", base_url="offline", api_key="test",
        model="fake-2", label="Other")
    config.provider, config.model = "other", "fake-2"
    agent, _ = _resume_agent(config)
    resumed = run_turn(agent, "", decision_answers=[{"decision_ref": _refs(result)[0],
                                                     "chosen": ["SQLite"]}],
                       store=store, binding=Binding.of(config))
    assert resumed.stopped == "done"
    # The continuation still records where it came from; that never bound it.
    meta = store.find_continuation(_refs(result)[0])
    assert meta.model == "fake-1"


# --------------------------------------------------------------------------- #
# T176 — the stateless-run lifecycle
# --------------------------------------------------------------------------- #


def test_a_fresh_run_that_finishes_keeps_nothing(config):
    store = _sessions(config)
    agent, _ = _agent(config, [Script(text="All done.")])
    result = run_turn(agent, "Say hello.", store=store, binding=Binding.of(config))
    assert result.stopped == "done"
    assert list(store.root.iterdir()) == []


def test_a_fresh_run_that_errors_keeps_nothing(config):
    store = _sessions(config)
    agent, _ = _agent(config, [Script(error="provider fell over")])
    result = run_turn(agent, "Say hello.", store=store, binding=Binding.of(config))
    assert result.stopped == "error"
    assert list(store.root.iterdir()) == []


def test_a_fresh_run_that_stops_keeps_exactly_one_hidden_continuation(config):
    result, store = _stop(config)
    metas = store.list_sessions(include_continuations=True)
    assert len(metas) == 1
    meta = metas[0]
    assert meta.continuation == {"decision_refs": _refs(result), "mode": "act"}
    assert meta.cwd == Binding.of(config).workspace
    assert store.list_sessions() == []
    states = store.decisions(meta.id)
    assert states[_refs(result)[0]].status == "open"


def test_the_continuation_exports_by_the_id_its_ref_resolves_to(config, tmp_path):
    result, store = _stop(config)
    meta = store.find_continuation(_refs(result)[0])
    markdown = store.export_markdown(meta.id, tmp_path / "out.md")
    exported = store.export_json(meta.id, tmp_path / "out.json")
    assert "Which database?" in markdown.read_text(encoding="utf-8")
    assert _json.loads(exported.read_text(encoding="utf-8"))["meta"]["continuation"] \
        == meta.continuation


@pytest.mark.parametrize("ending", ["done", "error"])
def test_a_resumed_run_appends_to_the_same_continuation_however_it_ends(config, ending):
    result, store = _stop(config)
    ref = _refs(result)[0]
    meta = store.find_continuation(ref)
    lines_before = len(store.load(meta.id))
    scripts = ([Script(text="Writing.", tool_calls=[_write("db.py", "x\n")]),
                Script(text="Done.")] if ending == "done"
               else [Script(error="provider fell over")])
    agent, _ = _agent(config, scripts)
    resumed = run_turn(agent, "", decision_answers=[{"decision_ref": ref,
                                                     "chosen": ["SQLite"]}],
                       store=store, binding=Binding.of(config))
    assert resumed.stopped == ending
    assert [m.id for m in store.list_sessions(include_continuations=True)] == [meta.id]
    assert len(store.load(meta.id)) > lines_before
    assert store.decisions(meta.id)[ref].status == "stale"


def test_a_resumed_run_that_stops_again_keeps_the_continuation_and_adds_refs(config):
    result, store = _stop(config)
    first = _refs(result)[0]
    meta = store.find_continuation(first)
    agent, _ = _agent(config, [
        Script(text="Now the queue.", tool_calls=[_ask(QUEUE, call_id="q2")]),
        Script(text="unreachable")])
    again = run_turn(agent, "", decision_answers=[{"decision_ref": first,
                                                   "chosen": ["SQLite"]}],
                     store=store, binding=Binding.of(config))
    assert again.stopped == "clarification_required"
    second = _refs(again)[0]
    assert second != first
    kept = store.list_sessions(include_continuations=True)
    assert [m.id for m in kept] == [meta.id]
    assert kept[0].continuation["decision_refs"] == [first, second]
    states = store.decisions(meta.id)
    assert states[first].status == "stale" and states[second].status == "open"
    with pytest.raises(DecisionRejected) as refused:
        run_turn(_RecordingLoop(config), "", decision_answers=[
            {"decision_ref": first, "chosen": ["SQLite"]}],
            store=store, binding=Binding.of(config))
    assert refused.value.kind == "stale"


# --------------------------------------------------------------------------- #
# T181 — every rejection class, in order, with nothing changed
# --------------------------------------------------------------------------- #


def _two_decision_stop(config):
    result, store = _stop(config, DATABASE, QUEUE)
    return result, store, _refs(result)


@pytest.mark.parametrize("raw, kind", [
    ("not json at all", "malformed"),
    ("{}", "malformed"),
    ("[]", "malformed"),
    ([{"chosen": ["SQLite"]}], "missing"),
    ([{"decision_ref": "", "chosen": ["SQLite"]}], "missing"),
    ([{"decision_ref": "has spaces", "chosen": ["SQLite"]}], "malformed"),
    ([{"decision_ref": "dr-x", "chosen": ["SQLite"], "extra": 1}], "malformed"),
    ([{"decision_ref": "dr-never-minted", "chosen": ["SQLite"]}], "unknown"),
])
def test_each_rejection_class_is_refused_with_nothing_changed(config, raw, kind):
    result, store, _ = _two_decision_stop(config)
    before = _snapshot(store)
    agent, gateway = _resume_agent(config)
    with pytest.raises(DecisionRejected) as refused:
        run_turn(agent, "", decision_answers=raw, store=store,
                 binding=Binding.of(config))
    assert refused.value.kind == kind
    assert _calls(gateway) == 0 and agent.conversation.messages == []
    assert _snapshot(store) == before


def test_an_empty_answer_is_refused(config):
    result, store, refs = _two_decision_stop(config)
    before = _snapshot(store)
    agent, gateway = _resume_agent(config)
    with pytest.raises(DecisionRejected) as refused:
        run_turn(agent, "", decision_answers=[{"decision_ref": refs[0], "chosen": [],
                                               "written": "   "}],
                 store=store, binding=Binding.of(config))
    assert refused.value.kind == "empty" and refused.value.refs == [refs[0]]
    assert _calls(gateway) == 0 and _snapshot(store) == before


def test_an_option_the_question_never_offered_is_refused(config):
    result, store, refs = _two_decision_stop(config)
    agent, gateway = _resume_agent(config)
    with pytest.raises(DecisionRejected) as refused:
        run_turn(agent, "", decision_answers=[{"decision_ref": refs[0],
                                               "chosen": ["MongoDB"]}],
                 store=store, binding=Binding.of(config))
    assert refused.value.kind == "invalid_answer"
    assert _calls(gateway) == 0


def test_a_batch_spanning_two_continuations_is_refused(config):
    first, store = _stop(config)
    second, _ = _stop(config, QUEUE, request="Set up the queue — Redis or RabbitMQ?")
    before = _snapshot(store)
    agent, gateway = _resume_agent(config)
    with pytest.raises(DecisionRejected) as refused:
        run_turn(agent, "", decision_answers=[
            {"decision_ref": _refs(first)[0], "chosen": ["SQLite"]},
            {"decision_ref": _refs(second)[0], "chosen": ["Redis"]}],
            store=store, binding=Binding.of(config))
    assert refused.value.kind == "cross_continuation"
    assert _calls(gateway) == 0 and _snapshot(store) == before


def test_one_bad_answer_among_three_applies_none(config):
    result, store, refs = _two_decision_stop(config)
    before = _snapshot(store)
    agent, gateway = _resume_agent(config)
    with pytest.raises(DecisionRejected):
        run_turn(agent, "", decision_answers=[
            {"decision_ref": refs[0], "chosen": ["SQLite"]},
            {"decision_ref": refs[1], "chosen": ["Redis"]},
            {"decision_ref": "dr-never-minted", "chosen": ["x"]}],
            store=store, binding=Binding.of(config))
    assert _snapshot(store) == before
    states = store.decisions(store.find_continuation(refs[0]).id)
    assert states[refs[0]].status == states[refs[1]].status == "open"
    assert _calls(gateway) == 0


def test_stale_is_reported_stale_and_a_deleted_continuations_ref_unknown(config):
    result, store = _stop(config)
    ref = _refs(result)[0]
    agent, _ = _resume_agent(config)
    run_turn(agent, "", decision_answers=[{"decision_ref": ref, "chosen": ["SQLite"]}],
             store=store, binding=Binding.of(config))
    with pytest.raises(DecisionRejected) as stale:
        run_turn(_RecordingLoop(config), "", decision_answers=[
            {"decision_ref": ref, "chosen": ["SQLite"]}],
            store=store, binding=Binding.of(config))
    assert stale.value.kind == "stale" and stale.value.refs == [ref]

    store.delete(store.find_continuation(ref).id)
    with pytest.raises(DecisionRejected) as unknown:
        run_turn(_RecordingLoop(config), "", decision_answers=[
            {"decision_ref": ref, "chosen": ["SQLite"]}],
            store=store, binding=Binding.of(config))
    assert unknown.value.kind == "unknown"


def test_the_checks_run_in_order_and_stop_at_the_first_failure(config, tmp_path):
    """A batch wrong in several ways is reported for the earliest check —
    so no later step ever ran. Here: stale (5) outranks workspace (6), mode
    (7) and an empty answer (8); workspace outranks mode and content."""
    result, store = _stop(config)
    ref = _refs(result)[0]
    agent, _ = _resume_agent(config)
    run_turn(agent, "", decision_answers=[{"decision_ref": ref, "chosen": ["SQLite"]}],
             store=store, binding=Binding.of(config))
    elsewhere = tmp_path / "x"
    elsewhere.mkdir()
    wrong = Binding(workspace=str(elsewhere.resolve()), mode="plan")
    with pytest.raises(DecisionRejected) as refused:
        run_turn(_RecordingLoop(config), "", decision_answers=[
            {"decision_ref": ref, "chosen": [], "written": ""}], store=store, binding=wrong)
    assert refused.value.kind == "stale"

    second, _ = _stop(config)
    with pytest.raises(DecisionRejected) as refused:
        run_turn(_RecordingLoop(config), "", decision_answers=[
            {"decision_ref": _refs(second)[0], "chosen": []}], store=store, binding=wrong)
    assert refused.value.kind == "workspace"


def test_a_partial_batch_answers_only_its_own_decision(config):
    result, store, refs = _two_decision_stop(config)
    agent, _ = _agent(config, [Script(text="The queue is still open; stopping.")])
    run_turn(agent, "", decision_answers=[{"decision_ref": refs[0], "chosen": ["SQLite"]}],
             store=store, binding=Binding.of(config))
    states = store.decisions(store.find_continuation(refs[0]).id)
    assert states[refs[0]].status == "stale"
    assert states[refs[1]].status == "open"


# --------------------------------------------------------------------------- #
# T201 — a resumed answer is learned by the same path as a live one
# --------------------------------------------------------------------------- #


def _learning_agent(config, scripts, bus=None):
    from comodor.learning import LearningEngine

    bus = bus or EventBus()
    gateway = Gateway(config, scripts=scripts)
    memory = LearningEngine(config, bus, gateway)
    agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation(), memory)
    return agent, memory


def test_a_resumed_answer_becomes_a_settled_decision_with_provenance(config):
    result, store = _stop(config)
    agent, memory = _learning_agent(config, [Script(text="Noted.")])
    run_turn(agent, "", decision_answers=[{"decision_ref": _refs(result)[0],
                                           "chosen": ["SQLite"]}],
             store=store, binding=Binding.of(config))
    (settled,) = memory.settled_decisions()
    assert settled.trigger == "Which database?" and settled.guidance == "SQLite"
    assert settled.provenance == "settled_decision" and settled.source == "user"


@pytest.mark.parametrize("raw", [
    [{"decision_ref": "dr-never-minted", "chosen": ["SQLite"]}],
    "garbage",
    [{"decision_ref": "__REF__", "chosen": ["MongoDB"]}],
])
def test_a_rejected_batch_learns_nothing(config, raw):
    result, store = _stop(config)
    if isinstance(raw, list):
        raw = [{**entry, "decision_ref": entry["decision_ref"].replace(
            "__REF__", _refs(result)[0])} for entry in raw]
    agent, memory = _learning_agent(config, [Script(text="Noted.")])
    with pytest.raises(DecisionRejected):
        run_turn(agent, "", decision_answers=raw, store=store,
                 binding=Binding.of(config))
    assert memory.settled_decisions() == []


def test_a_stale_batch_learns_nothing_more(config):
    result, store = _stop(config)
    ref = _refs(result)[0]
    agent, memory = _learning_agent(config, [Script(text="Noted.")])
    run_turn(agent, "", decision_answers=[{"decision_ref": ref, "chosen": ["SQLite"]}],
             store=store, binding=Binding.of(config))
    later, later_memory = _learning_agent(config, [Script(text="Noted.")])
    with pytest.raises(DecisionRejected):
        run_turn(later, "", decision_answers=[{"decision_ref": ref,
                                               "chosen": ["PostgreSQL"]}],
                 store=store, binding=Binding.of(config))
    assert [d.guidance for d in later_memory.settled_decisions()] == ["SQLite"]


def test_the_learned_decision_is_not_asked_again_in_the_project(config):
    result, store = _stop(config)
    agent, memory = _learning_agent(config, [Script(text="Noted.")])
    run_turn(agent, "", decision_answers=[{"decision_ref": _refs(result)[0],
                                           "chosen": ["SQLite"]}],
             store=store, binding=Binding.of(config))
    later, _ = _learning_agent(config, [
        Script(text="Checking.", tool_calls=[_ask(DATABASE, call_id="q9")]),
        Script(text="Done.")])
    again = later.run("Add a users table to the database.")
    assert again.stopped == "done"
    assert all(d.state == "answered" for d in later.tool_context.evidence.decisions)


def test_learning_switched_off_learns_nothing(config):
    config.learning.enabled = False
    result, store = _stop(config)
    agent, memory = _learning_agent(config, [Script(text="Noted.")])
    run_turn(agent, "", decision_answers=[{"decision_ref": _refs(result)[0],
                                           "chosen": ["SQLite"]}],
             store=store, binding=Binding.of(config))
    config.learning.enabled = True
    assert memory.settled_decisions() == []


def test_the_index_alone_decides_membership_not_the_transcript(config):
    """A ref a transcript mentions but its continuation never indexed is
    unknown — even when that continuation is the most recent one."""
    store = _sessions(config)
    _continuation(store, "c-1", ["ref-indexed"],
                  [_form("ref-indexed", "unattended"),
                   _form("ref-unindexed", "unattended", header="Queue",
                         prompt="Which queue?")],
                  cwd=Binding.of(config).workspace)
    loop = _RecordingLoop(config)
    with pytest.raises(DecisionRejected) as refused:
        run_turn(loop, "", decision_answers=[{"decision_ref": "ref-unindexed",
                                               "chosen": ["SQLite"]}],
                 store=store, binding=Binding.of(config))
    assert refused.value.kind == "unknown" and loop.calls == []


# --------------------------------------------------------------------------- #
# T205 — every application / surface primary-turn entry reaches run_turn
#
# Proved by behaviour, not by reading source: each of the six real entry
# functions is driven with `run_turn` replaced by a recording double, and the
# double must be reached with the inputs that entry carries. `run_turn`
# itself calls the loop, and the delegate child loops run their own; neither
# is part of this invariant.
# --------------------------------------------------------------------------- #


class _RunTurnDouble:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, agent, user_text="", **kwargs):
        from comodor.agent.loop import TurnResult

        self.calls.append({"agent": agent, "user_text": user_text, **kwargs})
        accepted = kwargs.get("accepted")
        if accepted is not None:
            accepted()
        return TurnResult(text="recorded")


def test_entry_a_the_web_session_reaches_run_turn_with_what_it_was_given(
        config, monkeypatch):
    import comodor.web.session as web

    double = _RunTurnDouble()
    monkeypatch.setattr(web, "run_turn", double)
    session = web.Session(config)
    images = ["data:image/png;base64,AAAA"]
    carried = [{"decision": "Which host?", "decision_ref": "dr-a-1"}]
    try:
        assert session.send("look", images=images, decisions=carried)
        assert session._turn.acquire(timeout=10)
        session._turn.release()
    finally:
        session.close()
    (call,) = double.calls
    assert call["agent"] is session.agent and call["user_text"] == "look"
    assert call["images"] is images and call["decisions"] is carried
    assert call["decision_answers"] is None


def test_entry_b_core_service_send_reaches_run_turn_with_the_user_text(
        config, monkeypatch):
    import comodor.application as application

    double = _RunTurnDouble()
    monkeypatch.setattr(application, "run_turn", double)
    service = application.CoreService(config)
    try:
        handle = service.session(service.create_session()["id"])
        service.send(handle.id, "the user's words")
        handle._worker.join(10.0)
        assert not handle._worker.is_alive()
    finally:
        service.close()
    (call,) = double.calls
    assert call["agent"] is handle.assembly.agent
    assert call["user_text"] == "the user's words"
    assert "decisions" not in call and "decision_answers" not in call


def test_entry_c_the_completion_turn_passes_the_carried_decisions_as_decisions(
        config, monkeypatch):
    import comodor.application as application

    double = _RunTurnDouble()
    monkeypatch.setattr(application, "run_turn", double)
    payload = {"kind": "clarification_required", "decision": "Which host?",
               "decision_ref": "dr-c-1", "outcome": "unattended",
               "decisions": [{"id": "dr-c-1", "decision_ref": "dr-c-1",
                              "decision": "Which host?"}]}

    class Manager:
        records = [{"id": "d1", "state": "done", "answer": "stopped",
                    "clarification": payload}]

        def take_pending(self):
            records, self.records = self.records, []
            return records

        def restore(self, _):
            pass

    service = application.CoreService(config)
    try:
        handle = service.session(service.create_session()["id"])
        handle.assembly.delegates = Manager()
        service._deliver_completions(handle)
    finally:
        service.close()
    (call,) = double.calls
    assert call["decisions"] == [payload]
    assert "decision_answers" not in call


def test_entry_d_the_headless_run_reaches_run_turn_as_a_stateless_caller(
        config, monkeypatch, tmp_path):
    import argparse

    import comodor.application as application
    from comodor import cli

    double = _RunTurnDouble()
    monkeypatch.setattr(application, "run_turn", double)
    answers = tmp_path / "answers.json"
    answers.write_text('[{"decision_ref": "dr-d-1", "written": "x"}]', encoding="utf-8")
    config.learning.enabled = False
    code = cli.run_headless(config, argparse.Namespace(
        task="the task", yes=False, json=False, max_steps=1,
        decision_answers=str(answers)))
    assert code == 0
    (call,) = double.calls
    assert call["user_text"] == "the task"
    assert call["decision_answers"] == answers.read_text(encoding="utf-8")
    assert call["binding"] == Binding.of(config)
    assert call["store"].root == config.paths.user / "sessions"


def test_entry_e_an_acp_prompt_reaches_run_turn(config, monkeypatch):
    import io

    from comodor.acp import agent as acp_agent
    from comodor.acp.jsonrpc import Connection

    double = _RunTurnDouble()
    monkeypatch.setattr(acp_agent, "run_turn", double)
    agent = acp_agent.ComodorAgent(config, Connection(
        reader=io.StringIO(""), writer=io.StringIO(), log=io.StringIO()))
    try:
        made = agent.session_new({"cwd": str(config.paths.project)})
        session = agent.sessions[made["sessionId"]]
        agent.session_prompt({"sessionId": made["sessionId"],
                              "prompt": [{"type": "text", "text": "from the editor"}]})
        assert session._turn.acquire(timeout=10)
        session._turn.release()
    finally:
        agent.close()
    (call,) = double.calls
    assert call["agent"] is session.loop and call["user_text"] == "from the editor"
    assert call["decision_answers"] is None


def test_entry_f_a_scheduled_job_reaches_run_turn_as_a_stateless_caller(
        config, monkeypatch):
    from types import SimpleNamespace

    import comodor.cron.runner as runner

    double = _RunTurnDouble()
    monkeypatch.setattr(runner, "run_turn", double)
    runner.run_job(config, SimpleNamespace(prompt="the job's prompt", model=""))
    (call,) = double.calls
    assert call["user_text"] == "the job's prompt"
    assert call["binding"] == Binding.of(config)
    assert call["store"].root == config.paths.user / "sessions"
    assert "decision_answers" not in call


# --------------------------------------------------------------------------- #
# T206 — SC-042: a later answer produces the same requested result as an
# answer given during the original wait
# --------------------------------------------------------------------------- #


REPLAY_REQUEST = "Configure the service: SQLite or PostgreSQL, Redis or RabbitMQ?"


def _replay_model(messages):
    """A deterministic stand-in for the model: it asks until both decisions
    are answered, then writes exactly what the answers say, then stops. It
    reads the answers from the conversation — wherever they arrived from."""
    said = "\n".join(str(message.content or "") for message in messages)
    database = _re.search(r"Which database\?\n  -> (\w+)", said)
    queue = _re.search(r"Which queue\?\n  -> (\w+)", said)
    wrote = any(getattr(message, "name", "") == "write_file" for message in messages)
    if not (database and queue):
        return Script(text="Two decisions first.", tool_calls=[_ask(
            DATABASE, QUEUE, call_id=f"ask-{len(messages)}")])
    if not wrote:
        return Script(text="Writing the configuration.", tool_calls=[_write(
            "service.cfg", f"database={database.group(1)}\nqueue={queue.group(1)}\n",
            call_id=f"write-{len(messages)}")])
    return Script(text="Configured.")


def _replay_agent(config, bus=None):
    agent, gateway = _agent(config, [], bus)
    gateway.provider("fake")._next_script = _replay_model
    return agent


def _observed(config, result):
    target = config.paths.project / "service.cfg"
    content = target.read_text(encoding="utf-8") if target.exists() else None
    if target.exists():
        target.unlink()
    return {"stopped": result.stopped, "service.cfg": content}


def _answer_live(bus, chosen: dict[str, str]):
    def reply(event):
        if event.kind.value == "request" and event.payload["request"].kind == "questions":
            event.payload["request"].answer(_json.dumps([
                {"header": header, "prompt": "", "chosen": [value], "written": ""}
                for header, value in chosen.items()]))

    bus.subscribe(reply)


def test_sc_042_a_later_answer_gives_the_same_result_as_answering_at_once(config):
    chosen = {"Database": "SQLite", "Queue": "Redis"}

    # A: the decisions are answered during the original wait.
    bus = EventBus()
    _answer_live(bus, chosen)
    live = run_turn(_replay_agent(config, bus), REPLAY_REQUEST)
    answered_at_once = _observed(config, live)

    # B: nobody is there; the run stops, keeps a hidden continuation, and a
    #    later invocation answers the same decisions by their refs.
    store = _sessions(config)
    stopped = run_turn(_replay_agent(config), REPLAY_REQUEST, store=store,
                       binding=Binding.of(config))
    assert stopped.stopped == "clarification_required"
    by_prompt = {entry["decision"]: entry["decision_ref"]
                 for entry in stopped.clarification["decisions"]}
    assert set(by_prompt) == {"Which database?", "Which queue?"}
    resumed = run_turn(_replay_agent(config), "", decision_answers=[
        {"decision_ref": by_prompt["Which database?"], "chosen": ["SQLite"]},
        {"decision_ref": by_prompt["Which queue?"], "chosen": ["Redis"]}],
        store=store, binding=Binding.of(config))
    answered_later = _observed(config, resumed)

    assert answered_at_once == answered_later == {
        "stopped": "done", "service.cfg": "database=SQLite\nqueue=Redis\n"}
    # The same semantic decisions were resolved: both refs are now spent.
    meta = store.find_continuation(by_prompt["Which database?"])
    states = store.decisions(meta.id)
    assert {states[ref].status for ref in by_prompt.values()} == {"stale"}


# --------------------------------------------------------------------------- #
# T193 — a continuation keeps an ordinary session's privacy, and an answer
# never grants a permission
# --------------------------------------------------------------------------- #

SECRET = "sk-live-0123456789abcdefSECRET"


def test_a_continuation_holds_no_secret_an_ordinary_session_would_not(config):
    """The same redaction as any stored session: a configured secret read by
    a tool is redacted at the tool layer before it enters the conversation,
    so it reaches neither the continuation's transcript nor its meta."""
    config.providers["fake"].api_key = SECRET
    (config.paths.project / "settings.env").write_text(f"TOKEN={SECRET}\n",
                                                      encoding="utf-8")
    agent, _ = _agent(config, [Script(text="Reading, then a question.", tool_calls=[
        ToolCall(id="r1", name="read_file", arguments={"path": "settings.env"}),
        _ask(DATABASE)]), Script(text="unreachable")])
    store = _sessions(config)
    result = run_turn(agent, REQUEST, store=store, binding=Binding.of(config))
    assert result.stopped == "clarification_required"

    (meta,) = store.list_sessions(include_continuations=True)
    for path in (store.path_for(meta.id), store.meta_path(meta.id)):
        assert SECRET not in path.read_text(encoding="utf-8"), path.name
    # The ordinary-session path writes the very same messages the same way.
    store.save_meta(SessionMeta(id="ordinary"))
    for message in agent.conversation.messages:
        store.append("ordinary", message)
    assert SECRET not in store.path_for("ordinary").read_text(encoding="utf-8")
    # The index holds refs and a mode name, nothing else.
    assert set(meta.continuation) == {"decision_refs", "mode"}
    assert all(ev_ref.startswith("dr-") for ev_ref in meta.continuation["decision_refs"])


def test_a_rejection_never_echoes_what_the_answer_said(config):
    """FR-074: the refusal names refs and the failed check, never the text of
    the answer — which may hold anything the caller typed."""
    result, store = _stop(config)
    ref = _refs(result)[0]
    agent, _ = _resume_agent(config)
    run_turn(agent, "", decision_answers=[{"decision_ref": ref, "chosen": ["SQLite"]}],
             store=store, binding=Binding.of(config))
    with pytest.raises(DecisionRejected) as refused:
        run_turn(_RecordingLoop(config), "", decision_answers=[
            {"decision_ref": ref, "written": f"use {SECRET}"}],
            store=store, binding=Binding.of(config))
    assert SECRET not in str(refused.value)
    assert SECRET not in _json.dumps(refused.value.as_dict())


def test_an_answer_in_plan_mode_grants_no_write(config):
    """A decision answer supplies information, never permission: a run that
    stopped in plan mode resumes in plan mode, where writing stays refused."""
    config.agent.mode = "plan"
    result, store = _stop(config)
    agent, _ = _agent(config, [
        Script(text="Writing now.", tool_calls=[_write("db.py", "x\n")]),
        Script(text="Done.")])
    run_turn(agent, "", decision_answers=[{"decision_ref": _refs(result)[0],
                                           "chosen": ["SQLite"]}],
             store=store, binding=Binding.of(config))
    assert not (config.paths.project / "db.py").exists()


def test_in_act_mode_the_resumed_write_is_still_permission_controlled(config):
    """Act mode stays permission-controlled after an answer: with writes not
    pre-approved and nobody there to approve, the write does not happen."""
    result, store = _stop(config)
    config.safety.auto_approve_writes = False
    asked = []
    bus = EventBus()

    def decline(event):
        # The permission prompt is put to the person, who declines it.
        if event.kind.value == "request" and event.payload["request"].kind != "questions":
            asked.append(event.payload["request"])
            event.payload["request"].answer(event.payload["request"].fallback)

    bus.subscribe(decline)
    agent, _ = _agent(config, [
        Script(text="Writing now.", tool_calls=[_write("db.py", "x\n")]),
        Script(text="Done.")], bus)
    run_turn(agent, "", decision_answers=[{"decision_ref": _refs(result)[0],
                                           "chosen": ["SQLite"]}],
             store=store, binding=Binding.of(config))
    assert asked, "the write was put to the permission engine, not waved through"
    assert not (config.paths.project / "db.py").exists()


def test_a_changed_provider_does_not_bypass_the_mode_binding(config):
    from comodor.config import ProviderConfig

    config.agent.mode = "plan"
    result, store = _stop(config)
    config.providers["other"] = ProviderConfig(
        name="other", kind="fake", base_url="offline", api_key="test",
        model="fake-2", label="Other")
    config.provider, config.model, config.agent.mode = "other", "fake-2", "act"
    agent, gateway = _resume_agent(config)
    with pytest.raises(DecisionRejected) as refused:
        run_turn(agent, "", decision_answers=[{"decision_ref": _refs(result)[0],
                                               "chosen": ["SQLite"]}],
                 store=store, binding=Binding.of(config))
    assert refused.value.kind == "mode"
    assert _calls(gateway) == 0 and not (config.paths.project / "db.py").exists()


def test_an_invalid_batch_authorises_no_dependent_work(config):
    result, store = _stop(config)
    agent, gateway = _resume_agent(config)
    with pytest.raises(DecisionRejected):
        run_turn(agent, "", decision_answers=[{"decision_ref": _refs(result)[0],
                                               "chosen": ["NotAnOption"]}],
                 store=store, binding=Binding.of(config))
    assert _calls(gateway) == 0
    assert not (config.paths.project / "db.py").exists()
