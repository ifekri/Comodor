"""Where the domain's two invariants are enforced, once.

**Money is `Decimal`, never `float`.** `0.1 + 0.2` is not `0.3` in binary
floating point, and a fee schedule applied a few thousand times over a backtest
turns that into a balance that does not reconcile. Worse, `Decimal(0.1)` is
`0.1000000000000000055511151231257827021181583404541015625` — passing a float
through the `Decimal` constructor imports the error rather than avoiding it,
which is why `decimal_of` refuses floats outright instead of converting them.

**Time is timezone-aware UTC.** A naive datetime is a timestamp whose meaning
depends on the machine that reads it. Two runs of the same backtest on two
laptops must produce the same fills, and an hour of ambiguity twice a year is
not a rounding error.

Both rules are checked at construction. A value that cannot describe a real
trade should fail where it was written, not three layers later where the
message can only say that something was wrong somewhere.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, DecimalException, InvalidOperation
from typing import Union

from .enums import Rounding
from .errors import TradingValidationError

#: What may become a `Decimal` without losing anything.
#:
#: `int` and `str` are exact. `float` is not, and is refused rather than
#: converted — see the module docstring.
DecimalLike = Union[Decimal, int, str]


def decimal_of(value: object, field: str) -> Decimal:
    """A `Decimal` from something that can be one exactly.

    Floats are rejected with their own message, because the fix is different:
    every other bad value is a typo, and a float is a habit that has to be
    changed at the call site.
    """
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TradingValidationError(f"{field} must be a finite number, got {value}")
        return value
    if isinstance(value, bool):
        # `bool` is an `int`, and `True` is not a price.
        raise TradingValidationError(f"{field} must be a number, got a bool")
    if isinstance(value, float):
        raise TradingValidationError(
            f"{field} must not be a float: {value!r} cannot be represented exactly. "
            f"Pass a Decimal, an int, or a string such as '{value!r}'."
        )
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise TradingValidationError(f"{field} must not be empty")
        try:
            parsed = Decimal(text)
        except (InvalidOperation, DecimalException, ValueError) as exc:
            raise TradingValidationError(f"{field} is not a number: {value!r}") from exc
        if not parsed.is_finite():
            raise TradingValidationError(f"{field} must be a finite number, got {value!r}")
        return parsed
    raise TradingValidationError(
        f"{field} must be a Decimal, int or str, got {type(value).__name__}")


def positive(value: object, field: str) -> Decimal:
    """A `Decimal` strictly greater than zero."""
    number = decimal_of(value, field)
    if number <= 0:
        raise TradingValidationError(f"{field} must be greater than zero, got {number}")
    return number


def non_negative(value: object, field: str) -> Decimal:
    """A `Decimal` of zero or more.

    Separate from `positive` because the difference is real: a fill quantity of
    zero is meaningless, and a fee of zero is a maker rebate schedule working
    as intended.
    """
    number = decimal_of(value, field)
    if number < 0:
        raise TradingValidationError(f"{field} must not be negative, got {number}")
    return number


def utc_of(value: object, field: str) -> datetime:
    """A timezone-aware datetime, expressed in UTC.

    Aware datetimes in other zones are converted rather than refused — the
    caller has said what instant they mean, which is the part that matters.
    Naive ones are refused, because they have not.
    """
    if not isinstance(value, datetime):
        raise TradingValidationError(
            f"{field} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise TradingValidationError(
            f"{field} must be timezone-aware; a naive datetime has no defined instant")
    return value.astimezone(timezone.utc)


def identifier(value: object, field: str, *, limit: int = 128) -> str:
    """A non-empty label — a symbol, an asset code, an order id.

    Whitespace is stripped and the result must still be something. An asset
    called `" "` is not a currency, and letting it through means a portfolio
    keyed on a space.
    """
    if not isinstance(value, str):
        raise TradingValidationError(
            f"{field} must be a string, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise TradingValidationError(f"{field} must not be empty")
    if len(text) > limit:
        raise TradingValidationError(
            f"{field} must be at most {limit} characters, got {len(text)}")
    return text


def quantize(value: Decimal, step: Decimal, rounding: Rounding, field: str) -> Decimal:
    """`value` moved onto the grid `step` defines, the way `rounding` says.

    Done with integer arithmetic on the quotient rather than with `Decimal`'s
    own quantiser, because a step is not always a power of ten — a lot size of
    `0.05` or a tick of `2.5` is ordinary, and `Decimal.quantize` can only
    express exponents.

    `NEAREST` breaks ties upward. That is a choice rather than a law, and it is
    written down here so that two engines cannot disagree about it.
    """
    if step <= 0:
        raise TradingValidationError(f"{field} step must be greater than zero, got {step}")

    quotient = value / step
    whole = int(quotient.to_integral_value(rounding="ROUND_FLOOR"))
    remainder = quotient - whole

    if remainder == 0:
        steps = whole
    elif rounding is Rounding.FLOOR:
        steps = whole
    elif rounding is Rounding.CEIL:
        steps = whole + 1
    elif rounding is Rounding.NEAREST:
        steps = whole + 1 if remainder >= Decimal("0.5") else whole
    else:                                       # pragma: no cover - enum is closed
        raise TradingValidationError(f"unknown rounding {rounding!r}")

    # Multiplying back through the step keeps the result on the grid exactly,
    # and `normalize` would strip the trailing zeros that make a price look
    # like the venue's own quote, so it is deliberately not applied.
    return steps * step
