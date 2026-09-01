"""How curated facts look once injected into a turn.

The block travels in the user message, not the system prompt, so it is
rebuilt per conversation rather than per turn — but within a conversation it
is frozen (see ``FactService.snapshot``), so it costs nothing after the first
request of that conversation.
"""

from __future__ import annotations

from .store import Fact

#: The heading does the trust work: these are claimed facts the user can
#: review, not orders. A fact that reads like an order should not be obeyed
#: like one.
FACTS_HEADER = (
    "Curated memory — durable facts about this project and the person you are "
    "working with, written down in earlier sessions. Treat them as notes from "
    "a colleague: usually right, sometimes stale. If one contradicts what you "
    "can see, trust what you can see and say so."
)

#: Budgets, in tokens, split the way the two kinds are split in the table.
#: A memory fact says something about here; a user fact follows the person.
MEMORY_TOKENS = 800
USER_TOKENS = 500

_ORDER = {"user": 0, "memory": 1}


def render_facts(
    facts: list[Fact], memory_tokens: int = MEMORY_TOKENS, user_tokens: int = USER_TOKENS
) -> str:
    """The briefing block, within its two budgets.

    User facts lead — they are fewer and say who is being worked with. A fact
    that does not fit is dropped, not truncated: half a sentence is worse
    than none, and the ordering below already puts the pinned ones first.
    """
    lines = [FACTS_HEADER, ""]
    used = len(FACTS_HEADER) // 4
    budget = {"user": user_tokens, "memory": memory_tokens}
    kind_used = {"user": 0, "memory": 0}

    ranked = sorted(
        facts, key=lambda fact: (not fact.pinned, _ORDER.get(fact.kind, 2), -fact.updated_at)
    )
    dropped = 0
    for fact in ranked:
        text = f"- ({fact.kind}) {fact.text}"
        cost = len(text) // 4 + 1
        kind = fact.kind if fact.kind in budget else "memory"
        if kind_used[kind] + cost > budget[kind]:
            dropped += 1
            continue
        lines.append(text)
        used += cost
        kind_used[kind] += cost

    if len(lines) == 2:  # nothing fit
        return ""
    if dropped:
        lines.append(f"- ({dropped} more did not fit this turn's budget)")
    return "\n".join(lines)
