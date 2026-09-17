"""Conversation state and the context budget.

A long agent session will always outgrow its context window — tool output is
verbose and there is a lot of it. When usage crosses the configured fraction of
the window, the oldest middle section is replaced by an LLM-written brief.

The subtle part is *where* to cut. Every assistant message that requests tools
must keep its matching tool results, or the next request is rejected outright by
the provider. So compaction only ever cuts at a boundary where no tool call is
outstanding, and the original request is always preserved — losing the goal is
the one failure a summary cannot recover from.
"""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ..providers.base import Message, Role, ToolSpec, Usage
from .tokens import TokenCounter, estimate_text

Summariser = Callable[[list[Message]], str]


# --------------------------------------------------------------------------- #
# the funnel: what enters the conversation, and what stays resident under pressure
# --------------------------------------------------------------------------- #
#
# Two places, deliberately, and neither is "every turn rewrite the middle":
#
# *At append time* — a tool result that repeats material already resident is
# admitted as a reference to that material (dedup, unchanged-content
# referencing) or as a delta against it (delta context). The earlier message
# is never touched, so the provider's cached prefix is undisturbed; only the
# new bytes shrink. A reference resolves to exactly the content it names
# because that content is still in the conversation, and it is used only
# while it is: a resident copy that was compacted or withheld makes the next
# copy full again.
#
# *Under pressure* — before compaction summarises history away with a model
# call, the budget manager withholds retrievable, low-relevance tool results
# in favour of pointers naming how to get them back. This runs where the
# superseded-read sweep already runs, because both rewrite messages the
# provider has cached, and the one moment that is worth paying for is the
# moment compaction would bust the same cache anyway.
#
# Every optimization here has a switch (`OPTIMIZATIONS`), so the benchmark
# can measure each one against the paired baseline, and the naive strategy
# turns all of them off.

#: The optimizations behind the funnel, by the name the config switches them
#: off with (`agent.optimizations_off`).
OPTIMIZATIONS = ("dedup", "delta", "budget", "ranking", "summary_provenance")

#: Below this a reference or a delta saves less than the sentence costs.
WORTH_REFERENCING = 240

#: A tool result the budget manager may withhold has to be retrievable —
#: a file the agent can read again, or output spilled to one — and old enough
#: that the model is not reading it right now.
KEEP_RECENT_RESULTS = 6

#: Tool results the funnel never touches: a question form and how it ended
#: are the evidence a decision rests on, and they are neither repeated
#: material nor retrievable output. Deduplicating one would hide that a
#: decision was asked twice; withholding one would hide how it ended.
PROTECTED_TOOLS = frozenset({"ask"})

#: The note left where a withheld result was. Names how to get it back.
WITHHELD_NOTE = ("[{what} was moved out of the conversation to stay within the "
                 "context budget. Nothing is lost: {how}]")


@dataclass
class Resident:
    """One tool result still carried in full, by the identity of its material."""

    call_id: str
    index: int
    name: str
    path: str
    fingerprint: str
    content: str


@dataclass
class Withheld:
    """One result the budget manager moved aside this turn, and why."""

    call_id: str
    name: str
    path: str
    tokens: int
    reason: str


class Optimizer:
    """The switches, read once per conversation from the agent settings."""

    def __init__(self, enabled: Iterable[str] | None = None) -> None:
        self.enabled = set(OPTIMIZATIONS if enabled is None else enabled)

    @classmethod
    def from_config(cls, config: Any) -> "Optimizer":
        agent = getattr(config, "agent", None)
        if getattr(agent, "context_strategy", "current") == "naive":
            return cls(())
        off = set(getattr(agent, "optimizations_off", None) or ())
        return cls(name for name in OPTIMIZATIONS if name not in off)

    def on(self, name: str) -> bool:
        return name in self.enabled


@dataclass
class Conversation:
    """The message history plus everything we track about its size."""

    messages: list[Message] = field(default_factory=list)
    counter: TokenCounter = field(default_factory=TokenCounter)
    usage: Usage = field(default_factory=Usage)
    compactions: int = 0
    #: The estimated size of the last payload `render()` produced, counted
    #: where it was assembled so the gauge and the request agree (FR-051).
    last_request_tokens: int = 0
    #: Which optimizations are on for this conversation (see `OPTIMIZATIONS`).
    optimizer: Optimizer = field(default_factory=Optimizer)
    #: What the budget manager moved aside in the current turn. Recomputed
    #: every turn and never carried across one: it describes this request.
    withheld: list[Withheld] = field(default_factory=list)
    #: How many results were admitted as a reference or a delta rather than
    #: in full, and the bytes that did not have to be sent because of it.
    referenced: int = 0
    bytes_saved: int = 0

    # -- basics ----------------------------------------------------------- #

    def add(self, message: Message) -> Message:
        self.messages.append(message)
        return message

    def extend(self, messages: list[Message]) -> None:
        self.messages.extend(messages)

    def clear(self) -> None:
        self.messages.clear()
        self.usage = Usage()
        self.compactions = 0
        self.withheld = []

    # -- the funnel, at append time ---------------------------------------- #

    def admit(self, message: Message, *, path: str = "", material: str = "") -> Message:
        """Add a tool result, as a reference or delta where the material is already here.

        `material` is the result's content as the tool produced it (before
        any spill); `path` is the file it is about, when it is about one.
        Identical content already resident becomes a reference to the call
        that holds it (FR-099, FR-101, FR-052, FR-093); a changed file whose
        earlier version is resident becomes a delta against it when that is
        smaller (FR-100). The earlier message is never rewritten. A result
        that is small, that failed, or whose earlier copy is gone is carried
        in full.
        """
        content = material or message.content
        if message.role is not Role.TOOL or not content or message.is_error \
                or message.name in PROTECTED_TOOLS:
            return self.add(message)
        fingerprint = _fingerprint(content)
        message.meta.setdefault("fingerprint", fingerprint)
        if len(content) < WORTH_REFERENCING:
            return self.add(message)

        resident = self._resident(path)
        if self.optimizer.on("dedup") and resident is not None \
                and resident.fingerprint == fingerprint:
            what = f"{message.name} {path}".strip() if path else message.name
            message.content = (
                f"[{what}: unchanged since the result of call {resident.call_id} "
                f"above — identical content, {len(content):,} characters, not "
                f"repeated. Refer to that result; it is still current.]")
            message.meta["reference"] = resident.call_id
            self.referenced += 1
            self.bytes_saved += len(content) - len(message.content)
            return self.add(message)

        if self.optimizer.on("delta") and resident is not None and path \
                and resident.fingerprint != fingerprint:
            delta = _delta(resident.content, content, path)
            if delta and len(delta) < len(content) * 0.6:
                message.content = (
                    f"[{path} changed since the result of call {resident.call_id} "
                    f"above; the change against that copy, which is still in "
                    f"the conversation:]\n{delta}")
                message.meta["delta_base"] = resident.call_id
                message.meta["delta"] = True
                self.referenced += 1
                self.bytes_saved += len(content) - len(message.content)
                return self.add(message)
        return self.add(message)

    def _resident(self, path: str) -> Resident | None:
        """The newest full copy of `path` (or of the same tool output) still resident.

        Only a message carried in full counts: a reference, a delta, a
        withheld pointer or a compacted marker is not material anything may
        be measured against. So a copy that was moved out makes the next
        result full again, by construction (invalidation by absence).
        """
        for index in range(len(self.messages) - 1, -1, -1):
            candidate = self.messages[index]
            if candidate.role is not Role.TOOL:
                continue
            if path and str(candidate.meta.get("path") or "") != path:
                continue
            if not path:
                continue
            if any(key in candidate.meta for key in
                   ("reference", "delta", "withheld", "superseded")):
                return None
            fingerprint = str(candidate.meta.get("fingerprint") or "")
            if not fingerprint:
                return None
            return Resident(call_id=candidate.tool_call_id, index=index,
                            name=candidate.name, path=path,
                            fingerprint=fingerprint, content=candidate.content)
        return None

    # -- the funnel, under pressure ---------------------------------------- #

    def withhold(self, budget_tokens: int, query: str = "",
                 estimate: Callable[[str], int] = estimate_text) -> tuple[int, int]:
        """Move low-relevance, retrievable tool results aside until the
        history fits `budget_tokens`. Returns `(results withheld, tokens freed)`.

        Recomputed every call from the messages as they stand: the withheld
        set is derived, never remembered. Only a result that can be got back
        is a candidate — a file the agent can read again, or output that was
        spilled to one — and never the current request, an outstanding tool
        result, or one of the most recent results. Candidates go in
        relevance order, least relevant first (FR-097), so what the request
        is about stays; what it is not about is a pointer away.
        """
        self.withheld = []
        if not self.optimizer.on("budget") or budget_tokens <= 0:
            return 0, 0
        excess = estimate_messages_total(self.messages, estimate) - budget_tokens
        if excess <= 0:
            return 0, 0
        candidates = self._withholdable()
        if not candidates:
            return 0, 0
        ordered = self._rank(candidates, query) if self.optimizer.on("ranking") \
            else candidates
        freed = 0
        for index in ordered:
            if freed >= excess:
                break
            message = self.messages[index]
            before = estimate(message.content)
            path = str(message.meta.get("path") or "")
            spill = str(message.meta.get("spill") or "")
            if path:
                how = f"read {path} again with read_file, or grep it"
                what = f"the result of {message.name} ({path})"
            elif spill:
                # The output was saved before it was moved aside, so point at
                # the saved copy: a command is not safe to replay — a commit or
                # a migration would happen twice.
                how = (f"read {spill} with read_file using offset and limit, "
                       f"or grep it")
                what = f"the result of {message.name}"
            else:
                how = f"re-run {message.name} if you need it"
                what = f"the result of {message.name}"
            message.content = WITHHELD_NOTE.format(what=what, how=how)
            message.meta["withheld"] = True
            after = estimate(message.content)
            freed += max(0, before - after)
            self.withheld.append(Withheld(call_id=message.tool_call_id,
                                          name=message.name, path=path,
                                          tokens=before - after,
                                          reason="over budget, retrievable"))
        return len(self.withheld), freed

    def _referenced_bases(self) -> set[str]:
        """Call ids a live reference or delta points at.

        A later message may name an earlier full result as the base it is
        written against. That base is not itself marked in any way, so
        withholding it would leave the reference pointing at a retrieval
        pointer instead of the content it promised.
        """
        bases: set[str] = set()
        for message in self.messages:
            for key in ("reference", "delta_base"):
                base = message.meta.get(key)
                if base:
                    bases.add(str(base))
        return bases

    def _withholdable(self) -> list[int]:
        """Indexes of results that may be moved aside: resident in full,
        retrievable, not among the most recent, not the request itself."""
        found: list[int] = []
        recent = len(self.messages) - KEEP_RECENT_RESULTS
        bases = self._referenced_bases()
        for index, message in enumerate(self.messages):
            if index == 0 or index >= recent or message.role is not Role.TOOL:
                continue
            if message.is_error or message.name in PROTECTED_TOOLS:
                continue
            if any(key in message.meta for key in ("withheld", "reference", "superseded")):
                continue
            if message.tool_call_id in bases:
                # A live reference or delta depends on this content; moving it
                # aside would break the promise the reference made.
                continue
            path = str(message.meta.get("path") or "")
            spill = str(message.meta.get("spill") or "")
            # Retrievable means it can be got back without repeating a side
            # effect: a file the agent can read again, output saved to a spill
            # file, or a read-only listing/search. A command whose output was
            # not saved is not a candidate — "run it again" is not safe for a
            # commit, a migration or a deployment.
            retrievable = bool(path) or bool(spill) or message.name in (
                "grep", "glob", "list_dir", "web_search", "web_fetch")
            if not retrievable or len(message.content) < WORTH_REFERENCING:
                continue
            found.append(index)
        return found

    def _rank(self, indexes: list[int], query: str) -> list[int]:
        """Least relevant first, for a fixed query and corpus, deterministically.

        Reuses the learning package's BM25. The query is the request plus
        what the model has said since; ties break by age (older first), so
        an identical corpus always yields an identical order.
        """
        from ..learning.bm25 import BM25Index

        text = query or self.last_user_text
        recent_words = " ".join(m.content for m in self.messages[-4:]
                                if m.role is Role.ASSISTANT)
        index = BM25Index()
        for position in indexes:
            message = self.messages[position]
            index.add(str(position), f"{message.name} {message.meta.get('path', '')} "
                                     f"{message.content[:4000]}")
        scores = dict(index.search(f"{text} {recent_words}", limit=len(indexes)))
        # Ties break by age, older first: ascending position. Newest-first here
        # would withhold the more recent observations while keeping the older
        # ones, the opposite of what the docstring promises.
        return sorted(indexes, key=lambda position: (scores.get(str(position), 0.0), position))

    def render(self, system_prompt: str,
               tools: list[ToolSpec] | None = None) -> list[Message]:
        """The full payload for one request.

        Its size is recorded here, once, as it goes out: everything that
        reports context size reads this rather than assembling the payload
        a second time to count it.
        """
        payload = [Message.system(system_prompt), *self.messages]
        self.last_request_tokens = self.counter.count(payload, tools)
        return payload

    @property
    def last_user_text(self) -> str:
        for message in reversed(self.messages):
            if message.role is Role.USER:
                return message.content
        return ""

    # -- accounting ------------------------------------------------------- #

    def used_tokens(self, system_prompt: str = "", tools: list[ToolSpec] | None = None) -> int:
        payload = self.render(system_prompt) if system_prompt else self.messages
        return self.counter.count(payload, tools)

    def record_usage(self, usage: Usage) -> None:
        self.usage = self.usage.merge(usage)

    def fill(self, limit: int, system_prompt: str = "",
             tools: list[ToolSpec] | None = None) -> float:
        """How full the context window is, as a fraction."""
        if limit <= 0:
            return 0.0
        return min(1.0, self.used_tokens(system_prompt, tools) / limit)

    # -- compaction ------------------------------------------------------- #

    def needs_compaction(self, limit: int, threshold: float,
                         system_prompt: str = "",
                         tools: list[ToolSpec] | None = None) -> bool:
        return self.fill(limit, system_prompt, tools) >= threshold

    def safe_cut(self, keep_recent: int = 8) -> int:
        """Index up to which messages may be summarised away.

        A cut is only safe where the conversation is *settled*: a user turn
        with no assistant tool call still awaiting its result. Returns 0 when
        no safe point exists, which simply means compaction waits a turn.
        """
        if len(self.messages) <= keep_recent + 2:
            return 0

        latest_allowed = len(self.messages) - keep_recent
        pending: set[str] = set()
        last_safe = 0

        for index, message in enumerate(self.messages):
            if message.role is Role.ASSISTANT and message.tool_calls:
                pending.update(call.id for call in message.tool_calls)
            elif message.role is Role.TOOL:
                pending.discard(message.tool_call_id)

            # A user message with nothing outstanding is a clean seam.
            if (index > 0 and not pending and message.role is Role.USER
                    and index <= latest_allowed):
                last_safe = index

        return last_safe

    def compact(self, summarise: Summariser, keep_recent: int = 8) -> int:
        """Replace the middle of the history with a brief. Returns messages removed."""
        cut = self.safe_cut(keep_recent)
        if cut <= 1:
            return 0
        cut = self._protect_reference_bases(cut)
        if cut <= 1:
            return 0

        head = self.messages[0]            # the original request stays verbatim
        middle = self.messages[1:cut]
        tail = self.messages[cut:]
        if not middle:
            return 0

        try:
            brief = summarise(middle).strip()
        except Exception:
            # A failed summary must not lose messages; better a full context
            # and a hard error later than silently discarded work now.
            return 0
        if not brief:
            return 0

        marker = Message(
            role=Role.USER,
            content=(self._provenance(middle) + "\n\n" + brief),
            meta={"compacted": True, "replaced": len(middle),
                  "sources": _sources_of(middle)},
        )
        self.messages = [head, marker, *tail]
        self.compactions += 1
        return len(middle)

    def _protect_reference_bases(self, cut: int) -> int:
        """Move `cut` back so a surviving reference keeps its base verbatim.

        A reference or a delta among the messages that stay names an earlier
        full result and promises it is still there. Summarising that base away
        would leave the pointer referring to a lossy summary instead of the
        content it named, so the cut moves back to the settled seam at or
        before the earliest base a survivor depends on (FR-100, FR-101).
        """
        wanted: set[str] = set()
        for message in self.messages[cut:]:
            for key in ("reference", "delta_base"):
                base = message.meta.get(key)
                if base:
                    wanted.add(str(base))
        if not wanted:
            return cut
        earliest: int | None = None
        for index, message in enumerate(self.messages[:cut]):
            if message.tool_call_id and str(message.tool_call_id) in wanted:
                earliest = index if earliest is None else min(earliest, index)
        if earliest is None:
            return cut
        return self._seam_at_or_before(earliest)

    def _seam_at_or_before(self, index: int) -> int:
        """The largest settled user seam at or before `index`, or 0."""
        pending: set[str] = set()
        last = 0
        for position, message in enumerate(self.messages[:index + 1]):
            if message.role is Role.ASSISTANT and message.tool_calls:
                pending.update(call.id for call in message.tool_calls)
            elif message.role is Role.TOOL:
                pending.discard(message.tool_call_id)
            if position > 0 and not pending and message.role is Role.USER:
                last = position
        return last

    def _provenance(self, middle: list[Message]) -> str:
        """What a summary replaced, so every summary names its sources (FR-102).

        The original request is never among them: compaction keeps it
        verbatim. Off, the marker says only that it is a summary.
        """
        head = "[Earlier in this session — compacted summary"
        if not self.optimizer.on("summary_provenance"):
            return head + "]"
        sources = _sources_of(middle)
        tools = sum(1 for m in middle if m.role is Role.TOOL)
        assistant = sum(1 for m in middle if m.role is Role.ASSISTANT)
        parts = [f"of {len(middle)} messages: {assistant} model replies, {tools} tool results"]
        if sources:
            parts.append("from " + ", ".join(sources[:12])
                         + (f" and {len(sources) - 12} more" if len(sources) > 12 else ""))
        return head + " " + "; ".join(parts) + "]"

    def forget_old_pictures(self, keep: int = 2) -> int:
        """Drop all but the newest screenshots. Returns how many went.

        A picture costs the same every turn it stays in the history, and a
        screen from twenty clicks ago is not what is on the screen now. The
        message is left in place with a note where the image was, so the model
        can see that it looked and when, without paying to look again.

        `keep` is small on purpose. Two is enough to compare "before" with
        "after"; a third is a screen two actions old, which is history.
        """
        seen = 0
        dropped = 0
        for message in reversed(self.messages):
            if not message.images:
                continue
            seen += 1
            if seen <= keep:
                continue
            dropped += len(message.images)
            message.images = []
            note = "[the screenshot from this step is no longer in context]"
            if note not in message.content:
                message.content = (message.content + "\n" + note).strip()
        return dropped

    def forget_superseded_reads(self) -> tuple[int, int]:
        """Blank out file reads that a later edit made untrue.

        Returns `(reads dropped, tokens freed)`. See `agent/staleness.py` for
        why the newest read of a file is always kept, and why a read of a file
        nothing has written to is left alone even when it is a duplicate.
        """
        from .staleness import forget_superseded_reads as sweep
        from .tokens import estimate_text

        return sweep(self.messages, estimate_text)

    # -- introspection ---------------------------------------------------- #


def _fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]


def _delta(before: str, after: str, path: str) -> str:
    """A unified diff from the resident copy to the new one; empty if identical."""
    lines = list(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"{path} (as in the conversation)", tofile=f"{path} (now)", n=2))
    return "".join(lines)


def _sources_of(messages: list[Message]) -> list[str]:
    seen: list[str] = []
    for message in messages:
        if message.role is Role.TOOL:
            source = str(message.meta.get("path") or "") or message.name
            if source and source not in seen:
                seen.append(source)
    return seen


def estimate_messages_total(messages: list[Message], estimate: Callable[[str], int]) -> int:
    return sum(estimate(message.content) + estimate(message.briefing) for message in messages)

