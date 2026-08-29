"""What each plan pays for each metered thing.

The tiers are deliberately not a simple multiplication: past the included
allowance the unit price drops, which is the part everyone gets wrong when they
reimplement it somewhere else. There is one implementation and this is it.
"""

from __future__ import annotations

#: plan -> meter -> (included units, price per unit, price per unit past a
#: thousand)
TABLE = {
    "starter": {
        "requests": (1_000, 0.0020, 0.0015),
        "storage_gb": (1, 0.1000, 0.0800),
    },
    "growth": {
        "requests": (10_000, 0.0010, 0.0007),
        "storage_gb": (10, 0.0500, 0.0400),
    },
    "enterprise": {
        "requests": (100_000, 0.0004, 0.0003),
        "storage_gb": (100, 0.0200, 0.0150),
    },
}


def included(plan: str, meter: str) -> int:
    """How much of `meter` this plan gets for nothing."""
    return TABLE.get(plan, {}).get(meter, (0, 0.0, 0.0))[0]


def apply_rate(plan: str, meter: str, quantity: int) -> float:
    """What `quantity` of `meter` costs on `plan`.

    The included allowance is free. The next thousand units are at the standard
    price, and everything past that is at the reduced one.
    """
    free, standard, reduced = TABLE.get(plan, {}).get(meter, (0, 0.0, 0.0))
    billable = max(0, quantity - free)
    if billable <= 1_000:
        return round(billable * standard, 4)
    return round(1_000 * standard + (billable - 1_000) * reduced, 4)
