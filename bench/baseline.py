"""The naive comparison strategy: everything re-sent, every turn.

A token figure on its own says nothing. "The task cost 40,000 tokens" is a
number; "it cost 40,000 tokens where re-sending everything costs 190,000, and
it passed the same three of three attempts" is a result. This is the second
half of that sentence.

The naive strategy is the product with its context work switched off: full
history, full file contents and full tool output re-sent on every turn; no
superseded-read sweep, no screenshot pruning, no optimization behind the
render funnel. Compaction is the one thing left on, because a request larger
than the model's window is refused and a baseline that cannot finish a task
measures nothing — it fires only when the window is nearly full.

It is expressed entirely as *settings* the runtime already reads, written into
the attempt's own config file. This module never touches the product: it is
benchmark infrastructure, nothing under `src/comodor/` imports it, and the
runtime learns which strategy it is running from `agent.context_strategy`
and nothing else. Keeping the naive path outside the product is what stops
benchmark code from quietly becoming runtime behaviour.
"""

from __future__ import annotations

from typing import Any

#: The product as shipped, and the comparison it is measured against.
CURRENT = "current"
NAIVE = "naive"
STRATEGIES = (CURRENT, NAIVE)


def settings(strategy: str) -> dict[str, Any]:
    """The `agent` settings that make one attempt run under `strategy`.

    Merged over the runner's own settings, so the step, time and cost
    ceilings a task declares are the same for both strategies — otherwise the
    comparison would be between two budgets, not two strategies.
    """
    if strategy == CURRENT:
        return {"context_strategy": CURRENT}
    if strategy == NAIVE:
        return {
            "context_strategy": NAIVE,
            # Nothing moved aside: a tool result is carried whole. The
            # figure is a ceiling no real result reaches, not a real budget.
            "max_tool_chars": 2_000_000,
            # Every screenshot stays.
            "keep_screenshots": 1_000_000,
            # Only when the window is nearly full — see the module docstring.
            "compact_at": 0.95,
        }
    raise ValueError(f"unknown strategy {strategy!r}; expected one of "
                     f"{', '.join(STRATEGIES)}")


def describe(strategy: str) -> str:
    return {
        CURRENT: "the product as shipped",
        NAIVE: "full history, full files and full tool output re-sent every turn",
    }[strategy]
