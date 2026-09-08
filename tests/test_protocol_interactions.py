"""Every interaction that can block a turn, and what a client is told about it.

A permission prompt and a question form are the two moments where the agent
stops and waits for a person. Both are safe while somebody answers. What these
tests pin down is the rest of it:

* a prompt nobody answers resolves itself, and says so, rather than leaving a
  card on screen for a decision the core has already taken;
* a reply that arrives after that is refused as unknown instead of being
  answered with a resolution nothing acted on;
* cancelling a turn unblocks a worker parked in a prompt;
* two interactions live at once are both carried, because a batch of read-only
  tools can each ask a question and a delegate shares its parent's bus;
* the prompt carries enough context to decide on, and no credential.

The waits here are claims, not sleeps: a zero timeout means "nobody can
answer", which is deterministic, and the concurrency test uses a barrier rather
than a duration.
"""

from __future__ import annotations

import json
import threading

import pytest

from comodor.application import CoreService, UnknownRequest
from comodor.events import Kind, Request
from comodor.safety import Risk


@pytest.fixture
def service(config):
    made = CoreService(config)
    seen: list[tuple[str, dict]] = []
    made.on_event = lambda _s, name, params, _q: seen.append((name, params))
    made.seen = seen          # type: ignore[attr-defined]
    yield made
    made.close()


@pytest.fixture
def prompting(config):
    """A config whose engine actually asks.

    The shared test fixture auto-approves writes and shell so the suites that
    are not about permissions never block. These tests are about the prompt, so
    the shortcut has to be off — otherwise `check` answers itself and nothing
    here is exercised. Set before the session is created, which is when the
    config is copied.
    """
    config.safety.auto_approve_safe = False
    config.safety.auto_approve_writes = False
    config.safety.auto_approve_shell = False
    return config


def names_of(service) -> list[str]:
    return [name for name, _ in service.seen]


def last(service, name: str) -> dict:
    found = [params for event, params in service.seen if event == name]
    assert found, f"no {name} was emitted; saw {names_of(service)}"
    return found[-1]


def raise_permission(service, session_id: str, *, request_id: str = "perm-1",
                     tool: str = "run_shell", risk: Risk = Risk.DANGEROUS,
                     summary: str = "run: npm run build",
                     detail: str = "$ npm run build") -> Request:
    """Put a real permission prompt on the session's bus, as the engine does."""
    request = Request(id=request_id, prompt=summary,
                      options=["allow", "allow_always", "deny"], detail=detail,
                      kind="permission", meta={"tool": tool, "risk": int(risk)})
    service.session(session_id).assembly.bus.emit(Kind.REQUEST, request=request)
    return request


# --------------------------------------------------------------------------- #
# what the prompt carries
# --------------------------------------------------------------------------- #

def test_a_permission_prompt_names_the_tool_and_the_tier(service):
    """The context an informed decision needs, from the engine's own record.

    Without it a client can only show a sentence, so the person has to infer
    from prose whether they are approving a read, a write or a shell command.
    """
    session = service.create_session()["id"]
    raise_permission(service, session)

    body = last(service, "permission.requested")
    assert body["tool"] == "run_shell"
    assert body["risk"] == "dangerous"
    assert body["title"] == "run: npm run build"
    assert body["detail"] == "$ npm run build"
    assert body["options"] == ["allow", "allow_always", "deny"]


@pytest.mark.parametrize("risk,name", [(Risk.SAFE, "safe"), (Risk.WRITE, "write"),
                                       (Risk.DANGEROUS, "dangerous")])
def test_every_tier_is_named_not_numbered(service, risk, name):
    """A client shows a word. The integer ordering stays a Python detail."""
    session = service.create_session()["id"]
    raise_permission(service, session, request_id=f"perm-{name}", risk=risk)

    assert last(service, "permission.requested")["risk"] == name


def test_a_prompt_with_nothing_to_say_omits_the_field(service):
    """Omitted rather than invented.

    A made-up `dangerous` on a prompt that was really a write trains somebody
    to stop reading the tier at all.
    """
    session = service.create_session()["id"]
    bare = Request(id="perm-bare", prompt="may I", options=["allow", "deny"],
                   kind="permission", meta={})
    service.session(session).assembly.bus.emit(Kind.REQUEST, request=bare)

    body = last(service, "permission.requested")
    assert "tool" not in body
    assert "risk" not in body


def test_no_credential_rides_along_in_a_prompt(service, config):
    """The prompt is display text for a client, so it is a boundary."""
    session = service.create_session()["id"]
    raise_permission(service, session)

    body = json.dumps(last(service, "permission.requested"))
    for forbidden in ("api_key", "apiKey", "providers", "token", "secret",
                      "ANTHROPIC", "Authorization"):
        assert forbidden not in body, f"{forbidden} reached a client"
    for entry in config.providers.values():
        if entry.api_key:
            assert entry.api_key not in body


# --------------------------------------------------------------------------- #
# a prompt nobody answers
# --------------------------------------------------------------------------- #

def test_an_unanswered_permission_resolves_itself_and_says_deny(prompting):
    """The card stops being actionable at the moment the core stops waiting.

    A timeout used to be silent: the worker carried on having refused, while
    every client kept showing a prompt for a decision already taken — and
    answering it produced a resolution event for a choice nothing acted on.
    """
    service = CoreService(prompting)
    seen: list[tuple[str, dict]] = []
    service.on_event = lambda _s, name, params, _q: seen.append((name, params))
    try:
        session = service.create_session()["id"]
        handle = service.session(session)
        handle.assembly.permissions.prompt_timeout = 0.0   # nobody can answer

        decision = handle.assembly.permissions.check(
            "run_shell", Risk.DANGEROUS, "run: npm run build",
            detail="$ npm run build")

        assert not decision.allowed
        assert "no answer" in decision.reason
        resolved = [params for name, params in seen
                    if name == "permission.resolved"]
        assert len(resolved) == 1, "the timeout is a resolution, and only one"
        assert resolved[0]["choice"] == "deny"
        # Nothing is left waiting, so a snapshot cannot restore a dead card.
        assert handle._pending == {}
        assert "permission" not in service.snapshot(session)
    finally:
        service.close()


def test_an_unanswered_timeout_is_not_learned_as_a_preference(config):
    """A refusal is a signal. Nobody having been there is not one."""
    service = CoreService(config)
    try:
        session = service.create_session()["id"]
        handle = service.session(session)
        handle.assembly.permissions.prompt_timeout = 0.0
        learned: list[tuple[str, str]] = []
        handle.assembly.permissions.on_denied = \
            lambda tool, summary: learned.append((tool, summary))

        handle.assembly.permissions.check(
            "run_shell", Risk.DANGEROUS, "run: npm run build",
            detail="$ npm run build")

        assert learned == [], "a timeout taught the engine a preference nobody held"
    finally:
        service.close()


def test_a_real_refusal_is_still_learned(prompting):
    """The other half of the distinction: an actual deny is a preference."""
    service = CoreService(prompting)
    try:
        session = service.create_session()["id"]
        handle = service.session(session)
        learned: list[tuple[str, str]] = []
        handle.assembly.permissions.on_denied = \
            lambda tool, summary: learned.append((tool, summary))

        def answer() -> None:
            # Polling for the request rather than sleeping on a guess: the
            # prompt is raised on another thread and this replies to it the
            # moment it exists.
            for _ in range(2000):
                if handle._pending:
                    try:
                        service.reply_permission(next(iter(handle._pending)),
                                                 "deny")
                    except Exception:
                        pass
                    return
                threading.Event().wait(0.005)

        worker = threading.Thread(target=answer, daemon=True)
        worker.start()
        decision = handle.assembly.permissions.check(
            "run_shell", Risk.DANGEROUS, "run: npm run build",
            detail="$ npm run build")
        worker.join(timeout=15.0)

        assert not decision.allowed
        assert decision.reason == "declined by the user"
        assert learned, "a real refusal is the clearest preference there is"
    finally:
        service.close()


def test_a_reply_after_the_timeout_is_refused_not_accepted(config):
    """The late answer must not be reported as though it had landed."""
    service = CoreService(config)
    try:
        session = service.create_session()["id"]
        handle = service.session(session)
        handle.assembly.permissions.prompt_timeout = 0.0
        handle.assembly.permissions.check(
            "run_shell", Risk.DANGEROUS, "run: npm run build",
            detail="$ npm run build")

        with pytest.raises(UnknownRequest):
            service.reply_permission("perm-late", "allow")

        # And the real request, now expired, is not answerable either.
        request = Request(id="perm-real", prompt="run: npm test",
                          options=["allow", "deny"], kind="permission")
        handle.assembly.bus.emit(Kind.REQUEST, request=request)
        request.expire()
        with pytest.raises(UnknownRequest):
            service.reply_permission("perm-real", "allow")
    finally:
        service.close()


def test_an_unanswered_question_resolves_as_cancelled(config):
    """Same rule for a form: the tool carries on, and the client is told."""
    from comodor.tools.ask import Ask

    service = CoreService(config)
    seen: list[tuple[str, dict]] = []
    service.on_event = lambda _s, name, params, _q: seen.append((name, params))
    try:
        session = service.create_session()["id"]
        handle = service.session(session)
        result: dict = {}

        def work() -> None:
            from comodor.events import Cancellation
            from comodor.safety import CheckpointStore, Redactor
            from comodor.tools.base import ToolContext

            handle.assembly.permissions.prompt_timeout = 0.0
            context = ToolContext(
                config=handle.assembly.config,
                permissions=handle.assembly.permissions,
                checkpoints=CheckpointStore(handle.assembly.config.paths.checkpoints),
                bus=handle.assembly.bus, redact=Redactor([]),
                cancel=Cancellation(),
                cwd=handle.assembly.config.paths.project)
            # The ask tool's own patience, shortened the same way: a form
            # nobody fills in is a cancelled form.
            import comodor.tools.ask as ask_module
            ask_module.WAIT_FOR = 0.0
            try:
                result["tool"] = Ask().run(context, questions=[
                    {"header": "approach", "prompt": "Which approach?",
                     "options": [{"label": "Refactor"}, {"label": "Replace"}]}])
            finally:
                ask_module.WAIT_FOR = 600.0

        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        worker.join(timeout=15.0)

        assert not worker.is_alive(), "the form waited for an answer nobody gave"
        assert result["tool"].meta.get("answered") is False
        resolved = [params for name, params in seen if name == "question.resolved"]
        assert len(resolved) == 1
        assert resolved[0]["cancelled"] is True
        assert "question" not in service.snapshot(session)
    finally:
        service.close()


# --------------------------------------------------------------------------- #
# cancelling while something is waiting
# --------------------------------------------------------------------------- #

def test_cancelling_unblocks_a_worker_parked_in_a_prompt(config):
    """Ctrl+C has to mean something to a turn that is waiting on a person.

    An interrupt is a flag the loop checks between steps, and a worker inside a
    permission wait is not between steps. Without this the session stayed busy
    for the whole prompt timeout after being cancelled, with the card still up.
    """
    service = CoreService(config)
    seen: list[tuple[str, dict]] = []
    service.on_event = lambda _s, name, params, _q: seen.append((name, params))
    try:
        session = service.create_session()["id"]
        handle = service.session(session)
        request = raise_permission(service, session)
        assert request.id in handle._pending

        answered = threading.Event()

        def wait_for_it() -> None:
            request.wait(30.0)
            answered.set()

        parked = threading.Thread(target=wait_for_it, daemon=True)
        parked.start()

        handle.busy = True                 # what a real turn would have set
        assert service.cancel(session)["cancelled"] is True

        assert answered.wait(10.0), "the prompt was never resolved"
        parked.join(timeout=5.0)
        assert request.choice == "deny"
        assert handle._pending == {}
        assert any(name == "permission.resolved" for name, _ in seen)
    finally:
        service.close()


# --------------------------------------------------------------------------- #
# two at once
# --------------------------------------------------------------------------- #

def test_a_client_that_cannot_draw_one_is_answered_with_its_own_fallback(config):
    """Every kind of request, not just the ones whose last option is `deny`.

    A mode proposal offers mode names with the current mode last, so answering
    it with a hardcoded "deny" was not one of its options: the reply was
    refused, the refusal swallowed, and the tool waited out its full timeout
    for a client that had already said it could not answer.
    """
    service = CoreService(config)
    service.client_capabilities = ()          # announces neither capability
    seen: list[tuple[str, dict]] = []
    service.on_event = lambda _s, name, params, _q: seen.append((name, params))
    try:
        session = service.create_session()["id"]
        request = Request(id="mode-1", prompt="Switch to plan mode?",
                          options=["plan", "ask", "act"], kind="mode",
                          meta={"current": "act", "target": "plan"})
        service.session(session).assembly.bus.emit(Kind.REQUEST, request=request)

        assert request.answered, "the tool was left waiting on a client that cannot answer"
        assert request.choice == "act", "the last option is the safe one"
        assert not [name for name, _ in seen if name == "permission.requested"], \
            "a prompt was sent to a client that said it could not draw one"
        assert service.session(session)._pending == {}
    finally:
        service.close()


def test_two_interactions_waiting_at_once_are_both_carried(service):
    """Neither is written over the other.

    Two can be live: a batch of read-only tools runs in parallel and each may
    ask a question, and a delegate shares its parent's event bus, so its
    question arrives while the parent waits on a permission. A snapshot with
    one slot would strand whichever came second, and a stranded prompt is a
    tool that looks hung.
    """
    session = service.create_session()["id"]
    raise_permission(service, session, request_id="perm-1")
    service.session(session).assembly.bus.emit(Kind.REQUEST, request=Request(
        id="ask-1", prompt="Which approach?", options=[], kind="questions",
        meta={"questions": json.dumps(
            [{"header": "approach", "prompt": "Which approach?",
              "options": [{"label": "Refactor"}]}])}))

    snapshot = service.snapshot(session)
    waiting = snapshot["interactions"]
    assert [entry["kind"] for entry in waiting] == ["permission", "question"], \
        "oldest first, and both of them"
    assert waiting[0]["permission"]["id"] == "perm-1"
    assert waiting[1]["question"]["id"] == "ask-1"

    # The singular fields stay, for a client that shows one at a time.
    assert snapshot["permission"]["id"] == "perm-1"
    assert snapshot["question"]["id"] == "ask-1"


def test_resolving_one_leaves_the_other_waiting(service):
    session = service.create_session()["id"]
    raise_permission(service, session, request_id="perm-1")
    service.session(session).assembly.bus.emit(Kind.REQUEST, request=Request(
        id="ask-1", prompt="Which approach?", options=[], kind="questions",
        meta={"questions": json.dumps(
            [{"header": "approach", "prompt": "Which approach?",
              "options": [{"label": "Refactor"}]}])}))

    service.reply_permission("perm-1", "deny")

    snapshot = service.snapshot(session)
    assert [entry["kind"] for entry in snapshot["interactions"]] == ["question"]
    assert "permission" not in snapshot
    assert snapshot["question"]["id"] == "ask-1"


def test_a_second_question_does_not_replace_the_first(service):
    session = service.create_session()["id"]
    bus = service.session(session).assembly.bus
    for request_id in ("ask-1", "ask-2"):
        bus.emit(Kind.REQUEST, request=Request(
            id=request_id, prompt=f"question {request_id}", options=[],
            kind="questions", meta={"questions": json.dumps(
                [{"header": request_id, "prompt": "Which?",
                  "options": [{"label": "This"}]}])}))

    snapshot = service.snapshot(session)
    assert [entry["question"]["id"] for entry in snapshot["interactions"]] \
        == ["ask-1", "ask-2"]


# --------------------------------------------------------------------------- #
# one resolution, whatever order the threads arrive in
# --------------------------------------------------------------------------- #

def test_an_answer_and_a_timeout_produce_one_resolution(config):
    """The claim decides who won, and the loser is told.

    Both happen on their own thread and can land in the same instant. Resolving
    twice would tell a client two different things about one request.
    """
    service = CoreService(config)
    seen: list[tuple[str, dict]] = []
    service.on_event = lambda _s, name, params, _q: seen.append((name, params))
    try:
        session = service.create_session()["id"]
        request = raise_permission(service, session)
        gate = threading.Barrier(2, timeout=10.0)
        outcomes: list[str] = []

        def answer_it() -> None:
            gate.wait()
            outcomes.append("answered" if request.answer("allow") else "lost")

        def expire_it() -> None:
            gate.wait()
            outcomes.append("expired" if request.expire() else "lost")

        threads = [threading.Thread(target=answer_it, daemon=True),
                   threading.Thread(target=expire_it, daemon=True)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10.0)

        assert sorted(outcomes) == ["lost", "answered"] or \
            sorted(outcomes) == ["expired", "lost"], outcomes
        assert request.answered
        # Exactly one of the two paths may speak for it.
        assert request.choice in ("allow", "deny")
    finally:
        service.close()
