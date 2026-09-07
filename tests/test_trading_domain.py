"""The two invariants everything else rests on: Decimal money, UTC time.

These are the tests that would fail first if somebody relaxed the domain, and
they are written against the reason rather than the mechanism. `0.1 + 0.2` is
not a style question — it is the arithmetic that turns a fee schedule applied
ten thousand times into a balance that does not reconcile.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from comodor.trading import (
    DEFAULT_TRADING_MODE,
    SIMULATED_MODES,
    Instrument,
    InstrumentSpec,
    LiveTradingDisabledError,
    MarketType,
    Rounding,
    TradingMode,
    TradingValidationError,
    require_simulated,
)
from comodor.trading.validation import (
    decimal_of,
    identifier,
    non_negative,
    positive,
    quantize,
    utc_of,
)

UTC = timezone.utc


# --------------------------------------------------------------------------- #
# money is Decimal
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value,expected", [
    (Decimal("1.25"), Decimal("1.25")),
    (5, Decimal(5)),
    ("0.00000001", Decimal("0.00000001")),
    ("  42  ", Decimal(42)),
    ("1E-8", Decimal("1E-8")),
])
def test_exact_inputs_become_exact_decimals(value, expected):
    assert decimal_of(value, "price") == expected


@pytest.mark.parametrize("value", [0.1, 1.0, -3.5, 1e-8])
def test_a_float_is_refused_rather_than_converted(value):
    """`Decimal(0.1)` is 0.1000000000000000055511151231257827021181583404541015625.

    Converting imports the error instead of avoiding it, so the constructor
    refuses and says what to pass instead.
    """
    with pytest.raises(TradingValidationError) as raised:
        decimal_of(value, "price")

    assert "float" in str(raised.value)
    assert "price" in str(raised.value)


def test_decimal_arithmetic_is_exact_where_float_is_not():
    """The whole reason for the rule, in one line."""
    assert 0.1 + 0.2 != 0.3
    assert decimal_of("0.1", "a") + decimal_of("0.2", "b") == Decimal("0.3")


def test_a_bool_is_not_a_number():
    """`True` is an `int` in Python, and `True` is not a quantity."""
    with pytest.raises(TradingValidationError, match="bool"):
        decimal_of(True, "quantity")


@pytest.mark.parametrize("value", ["", "   ", "abc", "1.2.3", None, [], {}])
def test_things_that_are_not_numbers_are_refused(value):
    with pytest.raises(TradingValidationError):
        decimal_of(value, "price")


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_a_number_that_is_not_finite_is_refused(value):
    with pytest.raises(TradingValidationError, match="finite"):
        decimal_of(value, "price")
    with pytest.raises(TradingValidationError, match="finite"):
        decimal_of(Decimal(value), "price")


def test_positive_and_non_negative_differ_where_it_matters():
    """A fill of nothing is meaningless; a fee of nothing is a rebate."""
    assert non_negative(0, "fee") == 0
    assert positive("0.5", "quantity") == Decimal("0.5")

    with pytest.raises(TradingValidationError, match="greater than zero"):
        positive(0, "quantity")
    with pytest.raises(TradingValidationError, match="not be negative"):
        non_negative("-1", "fee")


# --------------------------------------------------------------------------- #
# time is aware, and in UTC
# --------------------------------------------------------------------------- #


def test_an_aware_timestamp_is_kept():
    when = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    assert utc_of(when, "timestamp") == when


def test_a_naive_timestamp_is_refused():
    """It has no defined instant, so two machines would disagree about it."""
    with pytest.raises(TradingValidationError, match="timezone-aware"):
        utc_of(datetime(2026, 3, 1, 12, 0), "timestamp")


def test_another_zone_is_converted_rather_than_refused():
    """The caller said which instant they meant, which is the part that
    matters. Refusing would make every adapter convert by hand."""
    tehran = timezone(timedelta(hours=3, minutes=30))
    local = datetime(2026, 3, 1, 15, 30, tzinfo=tehran)

    converted = utc_of(local, "timestamp")

    assert converted.tzinfo is UTC
    assert converted == datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("value", ["2026-03-01", 1772000000, None])
def test_something_that_is_not_a_datetime_is_refused(value):
    with pytest.raises(TradingValidationError, match="datetime"):
        utc_of(value, "timestamp")


# --------------------------------------------------------------------------- #
# labels
# --------------------------------------------------------------------------- #


def test_an_identifier_is_trimmed_and_must_survive_it():
    assert identifier("  BTC  ", "asset") == "BTC"
    with pytest.raises(TradingValidationError, match="must not be empty"):
        identifier("   ", "asset")


def test_an_identifier_has_a_ceiling():
    with pytest.raises(TradingValidationError, match="at most"):
        identifier("x" * 200, "symbol")


# --------------------------------------------------------------------------- #
# normalisation, and the absence of a default
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value,step,rounding,expected", [
    ("43210.567", "0.01", Rounding.FLOOR, "43210.56"),
    ("43210.567", "0.01", Rounding.CEIL, "43210.57"),
    ("43210.567", "0.01", Rounding.NEAREST, "43210.57"),
    ("43210.564", "0.01", Rounding.NEAREST, "43210.56"),
    # A step that is not a power of ten, which `Decimal.quantize` cannot do.
    ("101.3", "2.5", Rounding.FLOOR, "100.0"),
    ("101.3", "2.5", Rounding.CEIL, "102.5"),
    ("101.3", "2.5", Rounding.NEAREST, "102.5"),
    # Already on the grid: every mode agrees and nothing moves.
    ("100.0", "2.5", Rounding.FLOOR, "100.0"),
    ("100.0", "2.5", Rounding.CEIL, "100.0"),
    ("100.0", "2.5", Rounding.NEAREST, "100.0"),
])
def test_rounding_goes_exactly_where_it_was_told(value, step, rounding, expected):
    assert quantize(Decimal(value), Decimal(step), rounding, "price") == Decimal(expected)


def test_a_tie_breaks_upward_and_that_is_written_down():
    """A choice rather than a law. Fixed here so two engines cannot disagree."""
    assert quantize(Decimal("2.5"), Decimal("1"), Rounding.NEAREST, "q") == Decimal(3)
    assert quantize(Decimal("3.5"), Decimal("1"), Rounding.NEAREST, "q") == Decimal(4)


def test_normalizing_needs_the_caller_to_say_which_way():
    """No default, ever. Rounding a quantity up can spend money the account
    does not have; which way is correct is the caller's question."""
    instrument = Instrument(venue="v", symbol="S", base_asset="B", quote_asset="Q")
    spec = InstrumentSpec(instrument=instrument, tick_size=Decimal("0.01"),
                          step_size=Decimal("0.001"))

    with pytest.raises(TypeError):
        spec.normalize_price("1.005")            # type: ignore[call-arg]
    with pytest.raises(TypeError):
        spec.normalize_quantity("1.0005")        # type: ignore[call-arg]


def test_a_step_of_zero_is_refused():
    with pytest.raises(TradingValidationError, match="greater than zero"):
        quantize(Decimal(1), Decimal(0), Rounding.FLOOR, "price")


def test_normalization_keeps_the_venues_own_precision():
    """`43210.60`, not `43210.6`. Stripping the trailing zero would make a
    price stop looking like the quote it came from, and round-tripping it
    through a venue that echoes strings would change it."""
    instrument = Instrument(venue="v", symbol="S", base_asset="B", quote_asset="Q")
    spec = InstrumentSpec(instrument=instrument, tick_size=Decimal("0.01"),
                          step_size=Decimal("0.001"))

    assert str(spec.normalize_price("43210.601", Rounding.FLOOR)) == "43210.60"


# --------------------------------------------------------------------------- #
# live is off
# --------------------------------------------------------------------------- #


def test_the_default_mode_is_not_live():
    assert DEFAULT_TRADING_MODE is not TradingMode.LIVE
    assert DEFAULT_TRADING_MODE in SIMULATED_MODES


def test_live_is_not_among_the_modes_that_can_run():
    assert TradingMode.LIVE not in SIMULATED_MODES


@pytest.mark.parametrize("mode", sorted(SIMULATED_MODES, key=lambda m: m.value))
def test_a_simulated_mode_is_allowed_through(mode):
    assert require_simulated(mode) is mode


def test_asking_for_live_is_refused_and_says_why():
    with pytest.raises(LiveTradingDisabledError) as raised:
        require_simulated(TradingMode.LIVE)

    message = str(raised.value)
    assert "disabled" in message
    assert "no live execution gateway" in message


def test_the_gate_refuses_anything_that_is_not_a_mode():
    """Including the string `"LIVE"`, which would otherwise sail past an
    `is not TradingMode.LIVE` check written by hand somewhere else."""
    with pytest.raises(LiveTradingDisabledError):
        require_simulated("LIVE")                # type: ignore[arg-type]


def test_no_default_anywhere_in_the_package_is_live():
    """Belt and braces: a scan for a live default that a future edit might
    introduce somewhere this file does not name."""
    import comodor.trading as trading

    for name in trading.__all__:
        value = getattr(trading, name)
        assert value is not TradingMode.LIVE, f"{name} defaults to live trading"


# --------------------------------------------------------------------------- #
# the market type distinction
# --------------------------------------------------------------------------- #


def test_spot_and_futures_are_different_instruments():
    spot = Instrument(venue="v", symbol="BTC-USDT", base_asset="BTC",
                      quote_asset="USDT", market_type=MarketType.SPOT)
    futures = Instrument(venue="v", symbol="BTC-USDT", base_asset="BTC",
                         quote_asset="USDT", market_type=MarketType.FUTURES,
                         settlement_asset="USDT")

    assert spot != futures
    assert spot.is_spot and not spot.is_futures
    assert futures.is_futures and not futures.is_spot
