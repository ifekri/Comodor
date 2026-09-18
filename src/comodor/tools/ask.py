"""Ask the user several multiple-choice questions at once.

The rule this tool exists to enforce is *ask before building, not after*. An
agent that guesses at an ambiguous requirement and writes two hundred lines has
spent the user's time and its own; one that asks four short questions first
spends thirty seconds and gets the requirement right.

It is deliberately one call for the whole set. A tool that asked one question
per call would produce exactly the drip of interruptions this replaces — the
model would ask, get an answer, think of the next thing, ask again — and each
round trip is a fresh interruption to somebody who was doing something else.
Working out the whole set first is more work for the model and much less for
the person answering, which is the right way round.

The tool is SAFE, which has a consequence worth naming: it is available in Plan
mode. Planning is when the ambiguity actually bites, so a planning agent that
could not ask would be the one most in need of it.

Three things decide what happens when the form comes back, and none of them
is the model's to decide.

*Only an answer is an answer.* A form that is dismissed, that expires, or that
is raised where nobody is listening comes back with the decision still open.
The tool says which of the three happened — they are different events with
different next steps — and it says the decision is unresolved. It never tells
the model to choose a default and carry on: a mandatory clarification that
the person did not answer is not the model's to fill in (FR-019, FR-035).

*A candidate has to come from somewhere.* Every option the model offers names
where it came from — the request, a file that was read, a setting, a learned
item — and the tool checks that against what this turn actually stated, read
or recalled. An option it cannot confirm is not shown as a real choice; the
person still has the write-your-own row, which is always there (FR-016).

*A decision the ledger already settles is not asked.* Read from the
repository, stated in the request, established by knowledge: the question is
answered before it is put, and no form is raised for it (FR-008).
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from .. import questions as forms
from ..events import Request
from ..safety import Risk
from .base import Tool, ToolContext, ToolResult

#: Long enough that somebody can go and check something before answering,
#: short enough that a form nobody is looking at does not hold a thread for the
#: rest of the day. On expiry the decision stays open: the tool reports that
#: the form expired, and nothing is decided on the person's behalf.
WAIT_FOR = 1800.0

#: How many consulted sources a form names. Enough to show the work; not the
#: whole ledger.
CONSULTED_MAX = 12


class Ask(Tool):
    """Put a short form to the user and wait for it."""

    name = "ask"
    risk = Risk.SAFE
    description = (
        "Ask the user to settle things you cannot settle yourself, as a short "
        "multiple-choice form. Call this ONCE, with every question you have, "
        "before you start building — not one question at a time, and not after "
        "the work is done.\n"
        "\n"
        "Ask when a reasonable person would read the request two different ways "
        "and the two readings lead to materially different work: which "
        "framework, which of two files is meant, whether an existing thing is "
        "replaced or kept alongside, what should happen in a case the request "
        "does not mention.\n"
        "\n"
        "Do not ask about things you can find out. Read the file, search the "
        "project, check what is already installed. Do not ask for permission "
        "to proceed, do not ask the user to confirm your plan back to you, and "
        "do not ask about matters with an obvious default — pick the default "
        "and say that you did.\n"
        "\n"
        "Every option needs a label a person can choose between at a glance, "
        "a description saying what picking it would mean, and where it came "
        "from: `source` is one of request, repository, configuration, "
        "knowledge or derivation, and `evidence` is the words in the request, "
        "the path you read, the setting, or the item you recalled. An option "
        "you cannot trace to one of those is not offered. A row for the user "
        "to write their own answer is added automatically to every question — "
        "never write one yourself.\n"
        "\n"
        "Say what each decision can change in `affects` (behaviour, "
        "architecture, data loss, security, compatibility, api, interface, "
        "destructive, release, side effect, persistence). If the user does not "
        "answer, the decision stays open: you will be told so, and you must not "
        "choose for them."
    )

    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": forms.MAX_QUESTIONS,
                "description": (
                    f"Every question you need answered, at most "
                    f"{forms.MAX_QUESTIONS}. They are shown together as one "
                    f"form."),
                "items": {
                    "type": "object",
                    "required": ["question", "header", "options"],
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": (
                                "The question, in full, ending in a question "
                                "mark. Specific enough to answer without "
                                "re-reading the request."),
                        },
                        "header": {
                            "type": "string",
                            "description": (
                                f"A tab label of two or three words, at most "
                                f"{forms.MAX_HEADER} characters — "
                                f"\"Database\", \"Error handling\"."),
                        },
                        "affects": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "What this decision can change: any of "
                                "behaviour, architecture, data loss, security, "
                                "compatibility, api, interface, destructive, "
                                "release, side effect, persistence. An empty "
                                "list means nothing material turns on it."),
                        },
                        "options": {
                            "type": "array",
                            "minItems": forms.MIN_OPTIONS,
                            "maxItems": forms.MAX_OPTIONS,
                            "description": (
                                "The realistic answers. If you have a "
                                "recommendation put it first and end its "
                                "label with \" (recommended)\"."),
                            "items": {
                                "type": "object",
                                "required": ["label"],
                                "properties": {
                                    "label": {
                                        "type": "string",
                                        "description": "The choice itself, a few words.",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": (
                                            "One sentence on what choosing this "
                                            "would mean — the trade-off, not a "
                                            "restatement of the label."),
                                    },
                                    "source": {
                                        "type": "string",
                                        "enum": list(forms.SOURCES),
                                        "description": (
                                            "Where this candidate comes from."),
                                    },
                                    "evidence": {
                                        "type": "string",
                                        "description": (
                                            "What shows it: the words in the "
                                            "request, the path read, the setting "
                                            "or the recalled item."),
                                    },
                                },
                            },
                        },
                        "multi": {
                            "type": "boolean",
                            "description": (
                                "True when several answers can hold at once. "
                                "Leave it out for a genuine either/or."),
                        },
                    },
                },
            },
        },
        "required": ["questions"],
    }

    def summary(self, args: dict[str, Any]) -> str:
        raw = args.get("questions")
        count = len(raw) if isinstance(raw, list) else 0
        if count == 1:
            return "asking a question"
        return f"asking {count} questions"

    def detail(self, ctx: ToolContext, args: dict[str, Any]) -> str:
        raw = args.get("questions")
        if not isinstance(raw, list):
            return ""
        lines = []
        for entry in raw:
            if isinstance(entry, dict) and entry.get("question"):
                lines.append(f"• {entry['question']}")
        return "\n".join(lines)

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        try:
            questions = forms.parse(args.get("questions"))
        except forms.MalformedQuestions as problem:
            return ToolResult.failure(str(problem))

        # A form is for a decision the person has to make, never for leave to
        # proceed or for a plan to be read back and approved (FR-011). Refused
        # as a tool error, so the model is told to get on with it.
        for question in questions:
            why = not_a_decision(question.prompt)
            if why:
                return ToolResult.failure(why)

        book = ctx.evidence

        # A decision the person already declined this attempt is not put to
        # them again (FR-129). The unresolved decision is reported instead.
        already = [decision for question in questions
                   for decision in book.decisions
                   if _same(decision.what, question.prompt)
                   and decision.material
                   and decision.state in ("unresolved", "blocked")]
        if already:
            return _unresolved(already, already[0].outcome or "cancelled", repeated=True)

        # Candidates are kept only where their provenance checks out; the
        # write-your-own row is always kept (FR-016, FR-017).
        for question in questions:
            question.options = ground(question.options, ctx)

        # Every question becomes a decision in the ledger. One the ledger can
        # already settle is answered here and not asked (FR-008); the rest are
        # classified, and the form carries why and what was checked (FR-034).
        consulted = consulted_sources(ctx)
        pending: list[tuple[forms.Question, Any]] = []
        settled: list[str] = []
        discretion: list[str] = []
        for question in questions:
            decision = book.open_decision(
                question.prompt, affects=question.affects,
                candidates=[option.label for option in question.options
                            if not option.free],
                evidence_consulted=consulted)
            if decision.state == "answered":
                settled.append(f"{question.prompt} — {decision.answer}")
                continue
            if not decision.material:
                # The ledger says this is the agent's own discretion, not a
                # decision the person has to make: do not interrupt them with
                # it (FR-003, FR-011). It is named back so the model says
                # which way it went.
                discretion.append(question.prompt)
                continue
            question.reason = decision.materiality
            question.evidence_consulted = list(decision.evidence_consulted)
            question.decision_ref = decision.id
            pending.append((question, decision))

        if not pending:
            if discretion:
                listed = "\n".join(f"  - {prompt}" for prompt in discretion)
                return ToolResult.success(
                    "Nothing here needs the person — these are yours to decide, "
                    "and you must say which way you went:\n" + listed,
                    display="Decided here.", answered=False, given=0, asked=0)
            return ToolResult.success(
                "No question was needed — every one is already settled by what "
                "this turn read or was told:\n" + "\n".join(f"  - {line}" for line in settled),
                display="Already settled.", answered=True, given=0, asked=0)

        asked = [question for question, _ in pending]

        # Nobody to answer: the decision is blocked, not decided (FR-033).
        if not ctx.bus.listening:
            for _, decision in pending:
                book.ended_without_answer(decision.id, "unattended")
            result = _unresolved([decision for _, decision in pending], "unattended")
            result.meta["form"] = form_record(asked, [], "unattended")
            return result

        request = Request(
            id=f"ask-{uuid.uuid4().hex[:8]}",
            prompt=asked[0].prompt if len(asked) == 1
            else f"{len(asked)} questions before I start",
            # Empty on purpose. The answer to this is a JSON document, not one
            # of a fixed set, and the interfaces validate a non-empty `options`
            # by membership — which would reject every real answer.
            options=[],
            detail="",
            kind="questions",
            meta={"questions": forms.encode(asked)},
        )
        for _, decision in pending:
            book.asked(decision.id)

        choice, expired = ctx.bus.resolve(request, WAIT_FOR)
        answers = forms.decode_answers(choice)

        if answers is None:
            # No answer came. Which of the three ways it ended is reported;
            # what is *not* reported is anything the model may fill in.
            outcome = ("expired" if expired
                       else "unattended" if choice == forms.UNATTENDED
                       else "cancelled")
            for _, decision in pending:
                book.ended_without_answer(decision.id, outcome)
            result = _unresolved([decision for _, decision in pending], outcome)
            result.meta["form"] = form_record(asked, [], outcome)
            return result

        by_header = {answer.header: answer for answer in answers}
        left_open = []
        for question, decision in pending:
            answer = by_header.get(question.header)
            if answer is not None and answer.given:
                book.answered(decision.id, answer.text)
            else:
                # Sent with this one blank. A material decision left blank
                # was declined, and stays open; a non-material one is the
                # model's to decide, and `summarise` says so.
                book.ended_without_answer(decision.id, "cancelled")
                if decision.material:
                    left_open.append(decision)

        summary = forms.summarise(asked, answers)
        given = sum(1 for answer in answers if answer.given)
        shown = "\n".join(
            f"{answer.header}: {answer.text}" for answer in answers if answer.given)
        result = ToolResult.success(
            summary,
            display=shown or "Every question skipped.",
            answered=True, given=given, asked=len(asked))
        result.meta["form"] = form_record(asked, answers,
                                          "cancelled" if left_open else "answered")
        if left_open:
            result.meta["outcome"] = "cancelled"
            result.meta["clarification"] = payload_for(left_open, "cancelled")
        return result


# --------------------------------------------------------------------------- #
# what a form is not for
# --------------------------------------------------------------------------- #

#: Prompts that ask for leave rather than for a decision. Anchored at the
#: start, so "Should failed requests be retried?" — a real decision — is not
#: caught by "should".
_PERMISSION = re.compile(
    r"^(?:(?:should|may|can|could|shall)\s+i\b|do\s+you\s+want\s+me\s+to\b"
    r"|is\s+it\s+(?:ok|okay|fine|alright|all\s+right)\s+(?:to|if\s+i)\b"
    r"|would\s+you\s+like\s+me\s+to\b)")

#: Prompts that hand the plan back for approval.
_CONFIRMATION = re.compile(
    r"(?:\bconfirm\b.*\b(?:plan|understanding|approach)\b"
    r"|\bdoes\s+(?:this|the|my)\s+(?:plan|approach)\b"
    r"|\bis\s+my\s+understanding\b|\blook\s+right\b|\bsound\s+(?:good|right|ok)\b"
    r"|\bthe\s+way\s+i\s+described\b|\bshall\s+i\s+do\s+it\b)")


def not_a_decision(prompt: str) -> str:
    """Why this prompt may not be asked, or an empty string."""
    text = " ".join(prompt.lower().split())
    if _PERMISSION.match(text):
        return (f"`ask` is not for permission to proceed ({prompt!r}). If the "
                f"work is allowed, do it; if a real decision is open, ask "
                f"about that decision instead.")
    if _CONFIRMATION.search(text):
        return (f"`ask` is not for confirming a plan back to the user "
                f"({prompt!r}). State the plan in your answer and carry it out; "
                f"ask only about a decision the plan cannot settle.")
    return ""


# --------------------------------------------------------------------------- #
# grounding: where a candidate came from
# --------------------------------------------------------------------------- #


def ground(options: list[forms.Option], ctx: ToolContext) -> list[forms.Option]:
    """Keep the candidates whose provenance checks out, plus the free row.

    Checkable per option: `source` says where the model got it, `evidence`
    says what shows it, and the check is against what this turn actually
    holds — the request text, the files read, the ledger's observations, the
    items recalled. An option the tool cannot confirm is dropped rather than
    shown as if it were grounded. A question may end with no candidate at
    all; the write-your-own row still makes it answerable.
    """
    kept: list[forms.Option] = []
    for option in options:
        if option.free:
            kept.append(option)
            continue
        if _grounded(option, ctx):
            option.grounded = True
            kept.append(option)
    return kept


def _grounded(option: forms.Option, ctx: ToolContext) -> bool:
    source = option.source or "request"
    evidence = (option.evidence or option.label).strip()
    if not evidence:
        return False
    if source == "request":
        request = str(getattr(ctx, "request_text", "") or "")
        return _mentioned(evidence, request) or _mentioned(option.label, request)
    if source in ("repository", "configuration", "derivation"):
        return _observed(evidence, option, ctx)
    if source == "knowledge":
        recalled = [str(item) for item in (getattr(ctx, "recalled", None) or [])]
        return any(_mentioned(evidence, item) or _mentioned(option.label, item)
                   for item in recalled)
    return False


def _mentioned(needle: str, haystack: str) -> bool:
    """Whether `needle` appears in `haystack` as words, not as a substring.

    A plain substring test grounds an option that was never mentioned: "Go"
    is inside "Django", and a short evidence string is inside longer prose.
    The boundaries make a candidate grounded only by the words that were
    actually said.
    """
    needle = " ".join(needle.lower().split())
    if not needle:
        return False
    haystack = " ".join(haystack.lower().split())
    return re.search(r"(?<![a-z0-9_])" + re.escape(needle) + r"(?![a-z0-9_])",
                     haystack) is not None


def _establishes(option: forms.Option, text: str) -> bool:
    """Whether this source's words actually back the candidate.

    Being read is not being evidence. A file that was read establishes the
    candidate only if it names it — "PostgreSQL" is not grounded by a README
    that never mentions it — so the check is on what the source says, not on
    the fact that it was consulted. A parenthetical on the label is the
    model's own aside ("redis (as settings.py has)"); the words before it are
    the candidate.
    """
    if not text:
        return False
    if _mentioned(option.label, text):
        return True
    core = re.sub(r"\([^)]*\)", " ", option.label).strip()
    return bool(core) and core != option.label and _mentioned(core, text)


def _observed(evidence: str, option: forms.Option, ctx: ToolContext) -> bool:
    """Whether a source this turn consulted establishes the candidate.

    Two things qualify, and both are about this turn. A source the turn read
    whose text backs the candidate; or a claim the turn verified that backs
    it. `ToolContext.seen` deliberately does not: it remembers every read of
    the session so a write can tell what it is replacing, and reading it here
    would let a file read in an earlier turn keep grounding an option in this
    one — an unrelated path from the past is not evidence for the present.
    """
    if not evidence:
        return False
    wanted = evidence.replace("\\", "/").strip().lower()
    if not wanted:
        return False
    for path, text in ctx.read_this_turn.items():
        name = path.replace("\\", "/").lower()
        if (name == wanted or name.endswith("/" + wanted)) \
                and _establishes(option, text):
            return True
    try:
        from ..agent.evidence import EvidenceState

        for entry in ctx.evidence.entries:
            if entry.state is not EvidenceState.VERIFIED:
                continue
            source = entry.source.replace("\\", "/").lower()
            if source == wanted or source.endswith("/" + wanted) \
                    or wanted in entry.claim.lower():
                if _establishes(option, entry.claim):
                    return True
    except Exception:
        pass
    return False


def consulted_sources(ctx: ToolContext) -> list[str]:
    """What this turn already checked, for the form to say so (FR-034)."""
    try:
        from ..agent.evidence import EvidenceState

        seen: list[str] = []
        for entry in ctx.evidence.entries:
            if entry.state is EvidenceState.VERIFIED and entry.source not in seen:
                seen.append(entry.source)
        return seen[:CONSULTED_MAX]
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# the unresolved outcome
# --------------------------------------------------------------------------- #


def _same(left: str, right: str) -> bool:
    return " ".join(left.lower().split()) == " ".join(right.lower().split())


def form_record(questions: list[forms.Question], answers: list[forms.Answer],
                outcome: str) -> dict[str, Any]:
    """The form as it was shown and how it ended, for the transcript (FR-030).

    The questions carry the options the person actually saw — the grounded
    candidates and the appended write-your-own row — the answers as given,
    and the final state. Kept on the tool message rather than in what the
    model reads, so the record costs no context.
    """
    return {
        "questions": forms.encode(questions),
        "answers": [{"header": answer.header, "chosen": list(answer.chosen),
                     "written": answer.written} for answer in answers],
        "outcome": outcome,
        "state": ("answered" if outcome == "answered"
                  else "blocked" if outcome == "unattended" else "unresolved"),
    }


def payload_for(decisions: list[Any], outcome: str) -> dict[str, Any]:
    """The structured clarification-required payload (contracts §C2).

    Singular fields describe the first open decision, as the contract
    shapes them; `decisions` carries every one that is open.
    """
    first = decisions[0]
    return {
        "kind": "clarification_required",
        "decision": first.what,
        "candidates": [{"label": label, "description": ""} for label in first.candidates],
        "evidence_consulted": list(first.evidence_consulted),
        "reason": first.materiality,
        "outcome": outcome,
        "decisions": [
            {"id": decision.id, "decision": decision.what,
             "candidates": list(decision.candidates),
             "evidence_consulted": list(decision.evidence_consulted),
             "reason": decision.materiality}
            for decision in decisions
        ],
    }


_ENDED = {
    "cancelled": "The user closed the form without answering",
    "expired": "The form expired before anyone answered",
    "unattended": "Nobody was there to answer",
}


def _unresolved(decisions: list[Any], outcome: str, repeated: bool = False) -> ToolResult:
    """What the model reads when the decision stayed open.

    It is told what happened and that the decision is unresolved. It is not
    told to decide. Work that depends on the decision does not run; the turn
    ends reporting what is needed.
    """
    material = [decision for decision in decisions if decision.material]
    named = "\n".join(f"  - {decision.what}" for decision in (material or decisions))
    if material:
        opening = ("That question was already declined this turn and is not "
                   "asked again" if repeated else _ENDED.get(outcome, _ENDED["cancelled"]))
        content = (
            f"{opening}. These decisions remain unresolved:\n{named}\n\n"
            "Do not choose a default, select an option or assume an answer. Do "
            "not do any work that depends on them. Stop here and report that "
            "these decisions are still needed.")
        result = ToolResult.success(
            content, display=f"Questions not answered ({outcome}).",
            answered=False, outcome=outcome, asked=len(material), given=0,
            clarification=payload_for(material, outcome))
        return result
    # Nothing material was asked: the model may settle these itself and say so.
    content = (
        f"{_ENDED.get(outcome, _ENDED['cancelled'])}. Nothing here changes the "
        f"outcome materially, so decide these yourself and say which way you "
        f"went:\n{named}")
    return ToolResult.success(content, display=f"Questions not answered ({outcome}).",
                              answered=False, outcome=outcome,
                              asked=len(decisions), given=0)
