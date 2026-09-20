"""The mutation preflight: a material decision cannot be skipped by not asking.

The clarification architecture registers a material decision when the model
calls `ask` (`tools/ask.py`) or a delegate hands one back. A model that simply
forgets to ask can therefore change the project first, and the benchmark's
`careful` tasks found exactly that: a quota nothing in the repository states
was invented and written, and the `ask` that should have come before it never
happened.

So the Core makes the check itself, once per turn, before the first call that
can change anything. It is not a second clarification mechanism: a missing
decision it finds enters the existing ledger through `open_decision`, reaches
`REQUIRES_CLARIFICATION`, and withholds the mutation by the same rule that
already withholds dependent work. It is not a prohibition parser either — the
stated constraints travel with the assessment so the decision is made on the
whole request, not on a path heuristic.

It costs one bounded model call per turn, made only when a mutation is about
to run. The call's usage is recorded on the turn's measurement separately, so
the preflight's own cost is visible rather than folded into the task's.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .evidence import MATERIALITY

#: The assessment prompt. Deliberately one question with a fixed answer shape:
#: an assessment that cannot be read exactly must not be guessed at.
PROMPT = """\
You are the mutation preflight. A coding agent is about to change the project,
and you decide whether that change depends on a decision nobody has made yet.

You are given the user's request, any constraints they stated, the action about
to run, and what the agent has already observed. Decide whether the action
depends on a decision that is not settled by the request, the repository,
project configuration or trustworthy stored knowledge, and that could
materially change any of these:

  behaviour, architecture, data_loss, security, compatibility, api_contract,
  interface_behaviour, destructive_operation, release_action,
  external_side_effect, persisted_state

A decision that could change none of those is the agent's own implementation
discretion: allow it. Do not ask about permission to proceed, about a plan the
request already settles, or about a choice with an obvious default.

Answer with JSON only, no prose around it:

{"status": "allow" | "requires_clarification",
 "decisions": [{"what": "<the decision, one sentence>",
                "affects": ["<one or more of the classes above>"]}],
 "reason": "<one sentence>"}

`decisions` is empty for `allow`, and non-empty for
`requires_clarification`. `affects` uses the class names exactly as listed.\
"""

_STATUSES = ("allow", "requires_clarification")

#: What a class name is allowed to look like, before the ledger canonicalises
#: it. Only used to drop a word the table does not know; the ledger's own
#: `assess` remains the authority on materiality.
_CLASS = re.compile(r"^[a-z_ ]{2,40}$")


@dataclass
class MissingDecision:
    """One decision the preflight says is unresolved and material."""

    what: str
    affects: list[str] = field(default_factory=list)


@dataclass
class MutationAssessment:
    """What the preflight decided about one proposed action.

    `status` is `allow` (the action may run), `requires_clarification` (a
    material decision is missing and the action must not run), or `blocked`
    (the assessment itself could not be read, which never becomes `allow`).
    """

    status: str = "blocked"
    proposed_action: str = ""
    dependencies: list[str] = field(default_factory=list)
    missing_decisions: list[MissingDecision] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    materiality: str = ""
    reason: str = ""

    @property
    def allows(self) -> bool:
        return self.status == "allow"


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


def parse(raw: str, *, proposed_action: str = "") -> MutationAssessment:
    """Read a preflight answer into an assessment. Never silently `allow`.

    A malformed answer is `blocked`, not `allow`: an assessment nobody can read
    is not permission, and the safe side of an unreadable guard is to withhold
    the mutation rather than run it.
    """
    data = _object(raw)
    if data is None:
        return MutationAssessment(status="blocked", proposed_action=proposed_action,
                                  reason="the preflight answer was not JSON")
    status = str(data.get("status") or "").strip()
    if status not in _STATUSES:
        return MutationAssessment(status="blocked", proposed_action=proposed_action,
                                  reason=f"the preflight answer had no usable status ({status!r})")
    assessment = MutationAssessment(
        status=status, proposed_action=proposed_action,
        reason=str(data.get("reason") or "").strip())
    if status == "allow":
        return assessment
    raw_decisions = data.get("decisions")
    if not isinstance(raw_decisions, list):
        return MutationAssessment(status="blocked", proposed_action=proposed_action,
                                  reason="requires_clarification with no decisions")
    for item in raw_decisions:
        if not isinstance(item, dict):
            continue
        what = str(item.get("what") or "").strip()
        if not what:
            continue
        affects = [str(a).strip().lower() for a in item.get("affects") or []
                   if str(a).strip() and _CLASS.match(str(a).strip().lower())]
        assessment.missing_decisions.append(MissingDecision(what=what, affects=affects))
    if not assessment.missing_decisions:
        return MutationAssessment(status="blocked", proposed_action=proposed_action,
                                  reason="requires_clarification with no readable decision")
    assessment.materiality = MATERIALITY[0] if any(
        d.affects for d in assessment.missing_decisions) else ""
    return assessment


def brief(value: str, limit: int = 600) -> str:
    text = " ".join((value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
