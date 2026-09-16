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

from typing import Any, Iterable

#: The product as shipped, and the comparison it is measured against.
CURRENT = "current"
NAIVE = "naive"
STRATEGIES = (CURRENT, NAIVE)


def settings(strategy: str, without: Iterable[str] = ()) -> dict[str, Any]:
    """The `agent` settings that make one attempt run under `strategy`.

    Merged over the runner's own settings, so the step, time and cost
    ceilings a task declares are the same for both strategies — otherwise the
    comparison would be between two budgets, not two strategies. `without`
    names context optimizations to switch off under the current strategy,
    one at a time, so each can be measured against the rest (T096).
    """
    if strategy == CURRENT:
        off = [str(name) for name in without if str(name)]
        return {"context_strategy": CURRENT, "optimizations_off": off}
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


# --------------------------------------------------------------------------- #
# the single-optimization experiment (T096)
# --------------------------------------------------------------------------- #
#
# One configuration is the product as shipped (`current`); each other names the
# one context optimization switched off under it. They are measured against
# each other *within a block*, so the only thing that differs between two
# attempts in a block is the switch — not the time of day, not the model's
# mood, not the provider's cache warmth.

CURRENT_CONFIG = "current"

#: The optimizations that can be switched off, in report order. `log_summary`
#: lives in `tools/overflow`, the rest in `agent/context.py`; both are read
#: from the same `agent.optimizations_off` setting.
ABLATIONS: tuple[str, ...] = ("dedup", "delta", "budget", "ranking",
                              "summary_provenance", "log_summary")

#: Every configuration of the experiment: the product, then one per ablation.
CONFIGURATIONS: tuple[str, ...] = (CURRENT_CONFIG,) + ABLATIONS


def switch_of(config: str) -> tuple[str, ...]:
    """The `optimizations_off` value for a configuration, or empty for current."""
    return () if config == CURRENT_CONFIG else (config,)


def block_order(block_index: int,
                configurations: tuple[str, ...] = CONFIGURATIONS) -> list[int]:
    """The order to run the configurations in one block, counterbalanced.

    Position is `(config_index + block_index) mod n`, and the block runs in
    position order, so over a run each configuration lands in each position
    about equally. A fixed order would confound the configuration with the
    time it ran and with whatever the provider had cached just before it.
    Deterministic: the same block index always gives the same order.
    """
    size = len(configurations)
    return sorted(range(size), key=lambda index: (index + block_index) % size)
