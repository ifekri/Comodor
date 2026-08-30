"""Turning a usage record into money.

Rates are held per plan; the arithmetic that applies them is in `rates.py`.
"""

from __future__ import annotations

from .plans import plan_for
from .rates import apply_rate


def invoice_lines(account: str, usage: dict[str, int]) -> list[tuple[str, float]]:
    """One line per metered thing, priced for this account's plan."""
    plan = plan_for(account)
    lines = []
    for meter, quantity in sorted(usage.items()):
        lines.append((meter, apply_rate(plan, meter, quantity)))
    return lines


def invoice_total(account: str, usage: dict[str, int]) -> float:
    return round(sum(amount for _, amount in invoice_lines(account, usage)), 2)
