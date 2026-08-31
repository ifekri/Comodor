"""The background review: one quiet pass over a finished turn.

Every completed turn, a daemon thread hands the transcript to the model with
one question: did anything durable come out of this that is not already
written down? The answer is JSON — a handful of facts, or NOTHING. The prompt
leans hard toward NOTHING, because a memory that records something after
every task is a log of noise, and noise is injected into every future turn.

The rules the review lives by, all of them structural:

* It never runs during a turn, only after one has fully ended.
* A new review replaces the one still running — only the latest turn's
  opinion of the conversation can matter.
* It runs on a cheaper model when one is configured
  (``learning.review_model``) and every token it spends is counted
  separately, so the review shows up in /cost as its own line, not blended
  into the turn's.
* Nothing is deleted by review. It proposes; staging and caps decide.
"""

from __future__ import annotations

import threading
from typing import Any

from ..agent.prompts import REVIEW_PROMPT
from ..providers.base import Message, collapse
from .reflect import build_transcript, extract_json
from .store import Fact

#: Cap the prompt states and the parse enforces. Three is enough for what a
#: single turn can genuinely establish.
MAX_NEW_FACTS = 3

VALID_KINDS = ("memory", "user")


class ReviewResult:
    """What one review pass produced."""

    __slots__ = ("facts", "raw", "usage", "accepted")

    def __init__(self) -> None:
        self.facts: list[Fact] = []
        self.raw = ""
        self.usage: Any = None
        self.accepted = 0

    @property
    def empty(self) -> bool:
        return not self.facts


def parse_review(text: str) -> list[Fact]:
    """Validate the model's JSON into facts we are willing to consider.

    Rejected outright: text over the length a fact may hold, kinds that do
    not exist, and anything that is not a plain sentence. The cap is enforced
    here rather than trusted to the prompt.
    """
    from .facts import FACT_MAX_CHARS, _check_injection, _clean_text

    payload = extract_json(text)
    facts: list[Fact] = []
    for entry in payload.get("facts") or []:
        if not isinstance(entry, dict):
            continue
        text_value = _clean_text(str(entry.get("text") or ""))
        if len(text_value) < 8 or len(text_value) > FACT_MAX_CHARS:
            continue
        kind = str(entry.get("kind") or "memory").lower()
        if kind not in VALID_KINDS:
            kind = "memory"
        try:
            _check_injection(text_value)
        except ValueError:
            continue
        facts.append(Fact(kind=kind, text=text_value, score=0.5))
    return facts[:MAX_NEW_FACTS]


class Reviewer:
    """Runs review passes over one fact service and one gateway."""

    def __init__(
        self,
        service: Any,
        gateway: Any,
        model: str = "",
        write_scope: str = "global",
        staging: bool = False,
    ) -> None:
        self.service = service
        self.gateway = gateway
        self.model = model
        self.write_scope = write_scope
        self.staging = staging
        self._current: threading.Thread | None = None
        self._lock = threading.Lock()
        self._generation = 0
        #: Called with the accepted facts once they are written. The engine
        #: sets this to announce them; the review itself knows no bus.
        self.on_accepted: Any = None
        #: Tokens the review itself consumed, kept apart from the turns'.
        self.usage: Any = None

    # -- the pass ------------------------------------------------------------ #

    def review(self, messages: list, outcome: str, episode_id: int = 0,
               generation: int | None = None) -> ReviewResult:
        """One synchronous pass, absorbed before it returns.

        ``generation`` is the async caller's ticket: when a newer review has
        started since this one was launched, the pass returns its result
        without absorbing it. Returns an empty result on any failure.
        """
        result = ReviewResult()
        transcript = build_transcript(messages, goal="", outcome=outcome)
        model = self.model  # blank means the gateway's active model
        try:
            completion = collapse(
                self.gateway.stream(
                    [Message.system(REVIEW_PROMPT), Message.user(transcript)],
                    model=model,
                    temperature=0.2,
                    max_tokens=500,
                )
            )
        except Exception:
            return result
        result.raw = completion.text
        result.usage = completion.usage
        self.usage = completion.usage
        result.facts = parse_review(completion.text)
        with self._lock:
            stale = (generation is not None and generation != self._generation)
        if not stale:
            result.accepted = self._absorb(result, episode_id)
        return result

    def review_async(
        self, messages: list, outcome: str, episode_id: int = 0
    ) -> threading.Thread | None:
        """Start one pass on a daemon thread, replacing any in-flight one.

        The collision rule is "latest wins": a turn that just ended describes
        the conversation better than the turn before it did. The replaced
        thread is not killed — Python offers no safe way — but it carries the
        generation it was born into, and only its own generation's result is
        ever absorbed, which is the same thing from the memory's point of view.
        """
        with self._lock:
            self._generation += 1
            mine = self._generation
            thread = threading.Thread(
                target=self._work,
                args=(list(messages), outcome, episode_id, mine),
                daemon=True,
                name="comodor-review",
            )
            self._current = thread
        thread.start()
        return thread

    def wait(self, timeout: float = 10.0) -> None:
        """Block until the current pass settles — used at shutdown and in tests."""
        with self._lock:
            thread = self._current
        if thread is not None:
            thread.join(timeout=timeout)

    def _work(self, messages: list, outcome: str, episode_id: int,
              generation: int) -> None:
        try:
            self.review(messages, outcome, episode_id, generation=generation)
        except Exception:
            return

    def _absorb(self, result: ReviewResult, episode_id: int) -> int:
        """Offer each proposed fact to the service. Returns how many stuck.

        A proposed fact that already exists simply lands as the same fact —
        ``add`` treats a duplicate as a success that changed nothing. When
        staging is on, everything lands as ``staged`` and waits for the
        person; nothing important is written without a human's yes.
        """
        accepted: list[Fact] = []
        for fact in result.facts:
            try:
                self.service.add(
                    fact.text, kind=fact.kind, staged=self.staging, origin_episode=episode_id
                )
                accepted.append(fact)
            except Exception:
                continue
        if accepted and self.on_accepted is not None:
            try:
                self.on_accepted(accepted, self.staging)
            except Exception:
                pass
        return len(accepted)
