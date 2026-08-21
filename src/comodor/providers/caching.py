"""Paying once for what the model reads many times.

An agent loop has a shape that is unusually wasteful. Every tool result must go
back to the model, and a model has no memory between requests, so each request
resends the entire conversation so far. Read a 500-line file at step two and its
tokens are billed again at step three, and four, and at every step until the
task ends. The content is written once and paid for *n* times.

Take this agent's real head — a system prompt and twelve tool schemas, 2,101
tokens — and an ordinary afternoon of work over it: twelve requests, six tool
calls each, a couple of thousand tokens per result. 150,000 tokens of content
are billed as 6,454,980. Forty-three times over. That arithmetic is a model of
a session rather than a recording of one, but it is not a delicate model: the
resend cost grows with the square of the number of steps, and no plausible
choice of the inputs makes the multiple small.

Every major provider will sell that resend at a discount, because their side of
it is a cache hit rather than a forward pass: Anthropic charges a tenth,
DeepSeek a tenth, OpenAI a half. The discount is not the interesting part. The
interesting part is the condition attached to it, which is unforgiving:

    **the request must begin with bytes the provider has seen before.**

Not similar bytes — the same ones, from the first character. One changed word
near the front and the whole prefix is a miss, at full price, however identical
the remaining hundred thousand tokens are.

That single rule decides the whole design, and it is where the obvious
implementation loses most of the money. Comodor used to inject recalled lessons
and matching skills into its *system prompt*, and recall runs against each new
request — so the first paragraph of every request differed from the last, and
nothing behind it could ever match. On the same modelled session, switching
caching on in that arrangement recovers 72% of the resends; moving the recalled
material out of the head and into the turn it belongs to, leaving a system
prompt identical for the life of the session, recovers 87%.

The part that is measured rather than modelled: a real session against a live
endpoint — three turns, tools running — read 22,093 prompt tokens and paid full
price for 3,021 of them. By the third turn the prompt had doubled and what it
cost had not moved, which is the property that decides whether a long session
is affordable.

So this module is not "enable caching". It is the rule that the front of the
request is immutable, and the bookkeeping that follows from it:

* what may sit in the prefix — facts about the machine and the tools, which do
  not change while the process runs;
* what may not — anything derived from what the user just typed, which belongs
  after the last cache mark, where it costs its own tokens and nothing else's;
* where to spend the four cache marks the API allows.

Nothing here changes what the model is told. Every lesson, every skill, every
tool result still reaches it, in the same words. Only the order changed, and
the order was never load-bearing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

#: Characters per token, for the one question this module asks: *is this block
#: big enough to be worth a cache mark?* Four is deliberately generous — real
#: code and JSON tokenise nearer three — because erring high here means erring
#: towards fewer marks, and an unmarked block costs nothing while a mark on a
#: block below the provider's floor costs the write premium and caches nothing.
#: The accurate counter lives in the agent, which this layer must not import.
CHARS_PER_TOKEN = 4.0

#: Anthropic will not cache a prefix shorter than this, and marking a shorter
#: one is simply ignored — no error, no cache, and a wasted breakpoint.
#:
#: The floor is not the same for every model, and treating it as though it were
#: is not the safe simplification it looks like. Comodor's own head — the system
#: prompt and twelve tool schemas — measures 2,101 tokens, which clears the
#: smaller floor easily and misses the larger one by twenty-one. Rounding up
#: therefore does not cost a little caching at the margin; it silently declines
#: to cache the one block that is identical for the entire session.
MIN_CACHEABLE = 1024
#: The small models want twice as much before they will hold anything.
MIN_CACHEABLE_SMALL = 2048
#: Model families with the higher floor.
_SMALL = ("haiku",)

#: The API accepts at most four. One is spent on the immutable head; the rest
#: roll along the tail of the conversation.
MAX_BREAKPOINTS = 4

#: Holding a prefix for an hour rather than five minutes is opt-in, and a
#: request asking for it without this header is rejected rather than downgraded.
LONG_TTL_BETA = "extended-cache-ttl-2025-04-11"

#: How many marks follow the conversation as it grows. Two is the number that
#: matters: the older one is the prefix the previous request wrote and this one
#: reads, the newer one extends the cache to cover what has been added since. A
#: single rolling mark still works — the provider matches the longest prefix it
#: has — but it leaves nothing cached when a turn is interrupted part-way, which
#: for an agent that is stopped by its user is not a rare case.
ROLLING = 2


def floor_for(model: str) -> int:
    """The shortest prefix this model will actually cache."""
    name = (model or "").lower()
    return MIN_CACHEABLE_SMALL if any(family in name for family in _SMALL) \
        else MIN_CACHEABLE


@dataclass(frozen=True)
class Marks:
    """Where the cache breakpoints go for one request.

    ``head`` marks the tools-and-system block; ``messages`` are indices into the
    encoded message list. Empty means this request is too small to be worth
    caching, which is the common case for the first exchange and stops the
    write premium being paid for nothing.
    """

    head: bool = False
    messages: tuple[int, ...] = ()

    def __bool__(self) -> bool:
        return self.head or bool(self.messages)

    @property
    def count(self) -> int:
        return int(self.head) + len(self.messages)


def plan(head_tokens: int, sizes: list[int], *, boundaries: list[int] | None = None,
         minimum: int = MIN_CACHEABLE, rolling: int = ROLLING) -> Marks:
    """Decide where to mark, given the head size and each message's size.

    ``sizes`` is one estimate per encoded message, in order. ``boundaries`` are
    the indices a mark may legally sit on — for Anthropic, the messages that end
    a turn, since a mark inside a run of tool results would split a block the
    next request will send as one and cache nothing.

    The rules are all consequences of the same arithmetic. A mark costs a 25%
    write premium on everything new behind it and saves 90% on every later read
    of it, so a block is worth marking when it will be read again — which for a
    prefix means always — and worth *not* marking when it is too small for the
    provider to keep.
    """
    if rolling < 0:
        raise ValueError("rolling must not be negative")

    head = head_tokens >= minimum
    budget = min(rolling, MAX_BREAKPOINTS - int(head))
    if budget <= 0 or not sizes:
        return Marks(head=head)

    allowed = sorted(set(boundaries)) if boundaries is not None else list(range(len(sizes)))
    allowed = [index for index in allowed if 0 <= index < len(sizes)]
    if not allowed:
        return Marks(head=head)

    # Running totals, so "is there enough behind this point" is a lookup rather
    # than a scan — this runs on every request of every turn.
    cumulative: list[int] = []
    running = head_tokens
    for size in sizes:
        running += size
        cumulative.append(running)

    chosen: list[int] = []
    for index in reversed(allowed):
        if cumulative[index] < minimum:
            break                    # everything earlier is smaller still
        chosen.append(index)
        if len(chosen) == budget:
            break

    # A second mark only earns its keep if a useful amount of conversation sits
    # between it and the first. Two marks a few hundred tokens apart spend a
    # breakpoint to cache almost nothing.
    kept: list[int] = []
    for index in chosen:
        if kept and cumulative[kept[-1]] - cumulative[index] < minimum:
            continue
        kept.append(index)

    return Marks(head=head, messages=tuple(sorted(kept)))


def weigh(payload: Any) -> int:
    """A rough token count for anything that goes on the wire."""
    if payload is None:
        return 0
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return int(len(text) / CHARS_PER_TOKEN)


def mark(block: dict[str, Any], *, ttl: str = "5m") -> dict[str, Any]:
    """Attach a cache breakpoint to one content block, in place.

    The default hour is five minutes, which is refreshed by every read: an agent
    that is working keeps its cache alive for free, and one left open in a
    forgotten terminal stops paying to hold anything.
    """
    control: dict[str, Any] = {"type": "ephemeral"}
    if ttl and ttl != "5m":
        control["ttl"] = ttl
    block["cache_control"] = control
    return block


def apply(body: dict[str, Any], marks: Marks, *, ttl: str = "5m") -> int:
    """Write ``marks`` into an Anthropic request body. Returns marks placed.

    The head mark goes on the system prompt rather than the tool list, because
    the API orders a request tools-then-system-then-messages and a breakpoint
    covers everything before it: one mark on the system block therefore caches
    the schemas as well, and leaves a breakpoint spare for the conversation.
    """
    placed = 0

    if marks.head:
        system = body.get("system")
        if isinstance(system, str) and system:
            body["system"] = [mark({"type": "text", "text": system}, ttl=ttl)]
            placed += 1
        elif isinstance(system, list) and system:
            mark(system[-1], ttl=ttl)
            placed += 1

    messages = body.get("messages") or []
    for index in marks.messages:
        if not 0 <= index < len(messages):
            continue
        content = messages[index].get("content")
        if isinstance(content, list) and content:
            mark(content[-1], ttl=ttl)
            placed += 1

    return placed


def refused(message: str) -> bool:
    """Whether an error is the endpoint objecting to the cache marks."""
    text = (message or "").lower()
    return "cache_control" in text or "cache control" in text


def strip(body: dict[str, Any]) -> bool:
    """Remove every cache mark from a request. True if any were there.

    The inverse of :func:`apply`, so a request refused for its marks can be
    resent as the plain request it would otherwise have been.
    """
    removed = False

    system = body.get("system")
    if isinstance(system, list):
        for block in system:
            removed |= block.pop("cache_control", None) is not None
        # Put it back the way it was: a list of one text block is only ever
        # something this module built.
        if len(system) == 1 and system[0].get("type") == "text":
            body["system"] = system[0].get("text", "")

    for message in body.get("messages") or []:
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                removed |= block.pop("cache_control", None) is not None

    for tool in body.get("tools") or []:
        if isinstance(tool, dict):
            removed |= tool.pop("cache_control", None) is not None

    return removed


def savings(usage_cached: int, usage_input: int, *, read: float = 0.10) -> float:
    """The fraction of the input bill that caching removed.

    Reported rather than assumed. ``usage_cached`` is what the provider says it
    served from cache; the ratio is what the user did not pay for, at the read
    rate the provider charges.
    """
    total = usage_cached + usage_input
    if total <= 0:
        return 0.0
    return (usage_cached * (1.0 - read)) / total
