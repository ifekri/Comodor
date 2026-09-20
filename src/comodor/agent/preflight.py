"""The mutation preflight: a material decision cannot be skipped by not asking.

The clarification architecture registers a material decision when the model
calls `ask` (`tools/ask.py`) or a delegate hands one back. A model that simply
forgets to ask can therefore change the project first, and the benchmark's
`careful` tasks found exactly that: a value nothing in the repository states was
invented and written, and the `ask` that should have come before it never
happened.

So the Core makes the check itself, once per batch of mutating calls, before
those calls run. It is not a second clarification mechanism: a missing decision
it finds enters the existing ledger through `open_decision`, reaches
`REQUIRES_CLARIFICATION`, and withholds the mutation by the same rule that
already withholds dependent work. It is not a prohibition parser either — the
stated constraints travel with the assessment so the decision is made on the
whole request, not on a path heuristic.

The assessor is shown *what the mutation actually does* and *what the turn
actually observed*, both bounded and redacted, because a tool name and a source
name are not enough to tell "the repository defines this value" from "the
repository was read and contains no such value". It is asked to demonstrate
where each material choice came from, not merely to emit `allow`. The call's
usage and its answer are recorded on the turn's measurement, so a wrong `allow`
can be explained without rerunning the model.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ..providers.base import Role
from .evidence import MATERIALITY

#: How much of a mutation's content the assessor sees. Enough for a constant,
#: a policy, a patch hunk; not enough for a file to dominate the check.
MUTATION_CHARS = 1_200
#: How many observed excerpts travel, and how much of each.
EVIDENCE_EXCERPTS = 6
EVIDENCE_CHARS = 700
#: How many decisions the assessor may return.
MOST_DECISIONS = 4
#: A hard cap on the whole question, so one enormous file cannot inflate the
#: preflight past what a bounded check should cost.
QUESTION_CHARS = 9_000

#: The assessment prompt. One question with a fixed answer shape, and an
#: explicit rule about values the mutation introduces — the failure this guard
#: exists for is a concrete value chosen without a source, so the assessor is
#: told to treat exactly that as missing rather than as discretion.
PROMPT = """\
You are the mutation preflight. A coding agent is about to change the project,
and you decide whether that change depends on a decision nobody has made yet.

You are given the user's request, any constraints they stated, the concrete
mutation about to run (the tool, the path, and the content or command it will
apply), and bounded excerpts of what the agent has actually observed.

Decide, for each choice the mutation makes, whether it is settled by the request,
the inspected evidence, project configuration or trustworthy stored knowledge,
or whether it is not settled. A choice that could materially change any of these
is not the agent's to make:

  behaviour, architecture, data_loss, security, compatibility, api_contract,
  interface_behaviour, destructive_operation, release_action,
  external_side_effect, persisted_state

If a proposed mutation introduces a concrete value, policy, limit, endpoint,
credential-related choice, externally controlled setting, destructive choice,
compatibility behaviour, persisted-state choice, or other material behaviour
that is not grounded in the request or the inspected evidence, it is a missing
material decision — not implementation discretion. A value the mutation invents
where the request or the evidence does not state one is missing, even if it
looks reasonable.

A choice that could change none of the classes above is implementation
discretion. Do not ask about permission to proceed, about a plan the request
already settles, or about a choice with an obvious default.

Answer with JSON only, no prose around it:

{"status": "allow" | "requires_clarification",
 "decisions": [
   {"what": "<the choice, one sentence>",
    "affects": ["<one or more of the classes above>"],
    "resolution": "grounded" | "agent_discretion" | "missing",
    "source_refs": ["<request, or the name of a file/command excerpt above>"]}],
 "reason": "<one sentence>"}

`resolution` is:
  grounded          — the request or the evidence states it; give the refs.
  agent_discretion  — it can change none of the material classes; no refs.
  missing           — nothing states it and it is material.

`decisions` may be empty only when there is nothing to weigh. A `grounded`
decision must name at least one source. `affects` uses the class names exactly
as listed. Do not invent a decision to look thorough; do not omit one to look
decisive.\
"""

_STATUSES = ("allow", "requires_clarification")
_RESOLUTIONS = ("grounded", "agent_discretion", "missing")

#: What a class name is allowed to look like, before the ledger canonicalises
#: it. Only used to drop a word the table does not know; the ledger's own
#: `assess` remains the authority on materiality.
_CLASS = re.compile(r"^[a-z_ ]{2,40}$")


@dataclass
class Decision:
    """One choice a proposed mutation makes, and where it came from."""

    what: str
    affects: list[str] = field(default_factory=list)
    resolution: str = ""
    source_refs: list[str] = field(default_factory=list)


@dataclass
class MutationAssessment:
    """What the preflight decided about one batch of mutating calls.

    `status` is `allow` (the batch may run), `requires_clarification` (a
    material decision is missing and the batch must not run), or `blocked`
    (the assessment could not be read or was inconsistent, which never becomes
    `allow`).
    """

    status: str = "blocked"
    proposed_action: str = ""
    decisions: list[Decision] = field(default_factory=list)
    reason: str = ""
    #: The bounded, redacted answer the assessor gave, kept for the trace.
    raw: str = ""

    @property
    def allows(self) -> bool:
        return self.status == "allow"

    @property
    def missing_decisions(self) -> list[Decision]:
        return [d for d in self.decisions if d.resolution == "missing"]

    def as_trace(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "decisions": [
                {"what": d.what, "affects": d.affects, "resolution": d.resolution,
                 "source_refs": d.source_refs}
                for d in self.decisions
            ],
            "answer": self.raw[:800],
        }


def _object(raw: str) -> dict | None:
    """The first JSON object in `raw`, or None."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        start = text.find("{")
        while start != -1:
            try:
                value = json.loads(text[start:])
                break
            except ValueError:
                start = text.find("{", start + 1)
        else:
            return None
    return value if isinstance(value, dict) else None


def _blocked(proposed_action: str, reason: str, raw: str = "") -> MutationAssessment:
    return MutationAssessment(status="blocked", proposed_action=proposed_action,
                              reason=reason, raw=raw)


def parse(raw: str, *, proposed_action: str = "") -> MutationAssessment:
    """Read a preflight answer into an assessment. Never silently `allow`.

    Every mechanical rule is here: a resolution must be one of the three, a
    `grounded` decision must name a source, `agent_discretion` may not carry a
    material class, and a status that contradicts its own decisions is refused.
    An unreadable or inconsistent answer is `blocked`, never permission.
    """
    data = _object(raw)
    if data is None:
        return _blocked(proposed_action, "the preflight answer was not JSON", raw)
    status = str(data.get("status") or "").strip()
    if status not in _STATUSES:
        return _blocked(proposed_action,
                        f"the preflight answer had no usable status ({status!r})", raw)
    assessment = MutationAssessment(
        status=status, proposed_action=proposed_action,
        reason=str(data.get("reason") or "").strip(), raw=(raw or "").strip())

    raw_decisions = data.get("decisions") or []
    if not isinstance(raw_decisions, list):
        return _blocked(proposed_action, "the decisions were not a list", raw)
    for item in raw_decisions[:MOST_DECISIONS]:
        if not isinstance(item, dict):
            return _blocked(proposed_action, "a decision was not an object", raw)
        what = str(item.get("what") or "").strip()
        resolution = str(item.get("resolution") or "").strip()
        if not what or resolution not in _RESOLUTIONS:
            return _blocked(proposed_action,
                            f"a decision had no usable name or resolution ({resolution!r})",
                            raw)
        affects = [str(a).strip().lower() for a in item.get("affects") or []
                   if str(a).strip() and _CLASS.match(str(a).strip().lower())]
        refs = [str(r).strip() for r in item.get("source_refs") or [] if str(r).strip()]
        if resolution == "grounded" and not refs:
            return _blocked(proposed_action,
                            f"a grounded decision named no source ({what!r})", raw)
        if resolution == "agent_discretion" and affects:
            # Discretion may not stand in for a material choice (FR-130).
            return _blocked(proposed_action,
                            f"discretion claimed for a material choice ({what!r})", raw)
        assessment.decisions.append(
            Decision(what=what, affects=affects, resolution=resolution, source_refs=refs))

    missing = assessment.missing_decisions
    if status == "allow" and missing:
        # An `allow` may not discard a missing decision; the honest reading is
        # that the decision is missing, so the batch is withheld.
        assessment.status = "requires_clarification"
        assessment.reason = assessment.reason or "a material decision was missing"
    elif status == "requires_clarification" and not missing:
        return _blocked(proposed_action,
                        "clarification requested with no missing decision", raw)
    return assessment


def _text(value: Any) -> str:
    return value if isinstance(value, str) else str(value or "")


def _clip(text: str, limit: int) -> str:
    text = _text(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def mutation_payload(calls: Iterable[Any], redact: Callable[[str], str]) -> str:
    """A bounded, redacted description of what a batch of mutations will do.

    The point of the check is the content: a path alone cannot say whether the
    change invents a value. The tool's own arguments are shown, clipped and
    redacted, so a constant, a patch or a command is visible and a credential
    is not.
    """
    lines: list[str] = []
    for call in calls:
        args = getattr(call, "arguments", None) or {}
        name = str(getattr(call, "name", "") or "")
        parts: list[str] = []
        for key in ("path", "command", "code", "old_string", "new_string",
                    "content", "pattern", "url", "query", "task", "name"):
            if key not in args:
                continue
            parts.append(f"{key}:\n{redact(_clip(_text(args[key]), MUTATION_CHARS))}")
        if not parts:
            for key, value in list(args.items())[:6]:
                parts.append(f"{key}: {redact(_clip(_text(value), 200))}")
        lines.append(f"- {name}\n  " + "\n  ".join(parts))
    return _clip("\n".join(lines), MUTATION_CHARS * 3)


def evidence_payload(messages: Iterable[Any],
                     redact: Callable[[str], str]) -> tuple[str, list[str]]:
    """Bounded, redacted excerpts of what the turn observed, newest first.

    The excerpts are transient input to the assessor; they are never written
    into the ledger, which stays fingerprint-only. Enough of each result is
    shown to tell "this file defines a rate" from "this file has no rate".
    """
    refs: list[str] = []
    blocks: list[str] = []
    for message in reversed(list(messages)):
        if getattr(message, "role", None) is not Role.TOOL:
            continue
        name = str(getattr(message, "name", "") or "")
        meta = getattr(message, "meta", None) or {}
        path = str(meta.get("path") or "") if isinstance(meta, dict) else ""
        ref = path or name
        if not ref or ref in refs:
            continue
        refs.append(ref)
        content = redact(_clip(_text(getattr(message, "content", "")), EVIDENCE_CHARS))
        blocks.append(f"[{ref}]\n{content}")
        if len(refs) >= EVIDENCE_EXCERPTS:
            break
    return "\n\n".join(reversed(blocks)), list(reversed(refs))


def question(request: str, constraints: list[str], mutations: str,
             evidence: str) -> str:
    """The whole bounded question the assessor is asked."""
    stated = "\n".join(f"- {rule}" for rule in constraints) or "(none stated)"
    text = (
        f"REQUEST:\n{_clip(request, 2_000)}\n\n"
        f"STATED CONSTRAINTS:\n{stated}\n\n"
        f"PROPOSED MUTATION(S):\n{mutations or '(none)'}\n\n"
        f"OBSERVED EVIDENCE:\n{evidence or '(nothing observed yet)'}")
    return _clip(text, QUESTION_CHARS)


def fingerprint(text: str) -> str:
    """A short identity for a bounded input, for the trace."""
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()[:16]


def materiality_of(decisions: Iterable[Decision]) -> str:
    for decision in decisions:
        for name in decision.affects:
            if name in MATERIALITY:
                return name
    return ""
