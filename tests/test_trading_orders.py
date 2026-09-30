"""Instruments, and the orders written against them.

The invariants tested here are the ones an exchange would otherwise teach us,
slowly and by rejection: a limit order with no price, a market order carrying
one, a size below the venue's minimum. Finding them at construction turns a
round trip into a stack trace with a line number.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from comodor.trading import (
    ApprovedOrder,
    ContractType,
    Fee,
    Fill,
    Instrument,
    InstrumentSpec,
    MarketType,
    OrderIntent,
    OrderState,
    OrderStatus,
    OrderType,
    RejectedOrder,
    Rounding,
    Side,
    TimeInForce,
    TradingValidationError,
)

UTC = timezone.utc
WHEN = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def spot() -> Instrument:
    return Instrument(venue="kucoin", symbol="BTC-USDT",
                      base_asset="BTC", quote_asset="USDT")


@pytest.fixture
def perpetual() -> Instrument:
    return Instrument(venue="kucoin", symbol="XBTUSDTM", base_asset="BTC",
                      quote_asset="USDT", market_type=MarketType.FUTURES,
                      settlement_asset="USDT", contract_multiplier=Decimal("0.001"))


@pytest.fixture
def spec(spot: Instrument) -> InstrumentSpec:
    return InstrumentSpec(instrument=spot, tick_size=Decimal("0.01"),
                          step_size=Decimal("0.0001"),
                          minimum_quantity=Decimal("0.0001"),
                          minimum_notional=Decimal("10"))


def an_intent(instrument: Instrument, **over) -> OrderIntent:
    base = {"instrument": instrument, "side": Side.BUY,
            "order_type": OrderType.LIMIT, "quantity": Decimal("0.5"),
            "limit_price": Decimal("43210.50"), "client_order_id": "c-1",
            "created_at": WHEN}
    base.update(over)
    return OrderIntent(**base)


# --------------------------------------------------------------------------- #
# instrument identity
# --------------------------------------------------------------------------- #


def test_two_instruments_describing_one_market_are_equal(spot):
    twin = Instrument(venue="kucoin", symbol="BTC-USDT",
                      base_asset="BTC", quote_asset="USDT")

    assert spot == twin
    assert hash(spot) == hash(twin)


def test_an_instrument_can_key_a_dictionary(spot, perpetual):
    """Which is what a portfolio needs it to do."""
    book = {spot: "inventory", perpetual: "exposure"}

    assert book[spot] == "inventory"
    assert len(book) == 2


def test_an_instrument_cannot_be_edited(spot):
    """Frozen: a dictionary keyed on it cannot have its keys mutated out from
    under it, which is what makes a portfolio safe to hold one."""
    with pytest.raises(FrozenInstanceError):
        spot.symbol = "ETH-USDT"                 # type: ignore[misc]


@pytest.mark.parametrize("field", ["venue", "symbol", "base_asset", "quote_asset"])
def test_an_empty_identity_field_is_refused(field):
    parts = {"venue": "v", "symbol": "S", "base_asset": "B", "quote_asset": "Q"}
    parts[field] = "   "

    with pytest.raises(TradingValidationError, match=field):
        Instrument(**parts)


def test_a_futures_instrument_must_say_what_it_settles_in():
    """Defaulting to the quote asset is right for a linear contract and
    silently wrong for an inverse one, which is the expensive half."""
    with pytest.raises(TradingValidationError, match="settlement_asset"):
        Instrument(venue="v", symbol="S", base_asset="B", quote_asset="Q",
                   market_type=MarketType.FUTURES)


def test_spot_does_not_carry_a_settlement_asset():
    with pytest.raises(TradingValidationError, match="settlement_asset"):
        Instrument(venue="v", symbol="S", base_asset="B", quote_asset="Q",
                   market_type=MarketType.SPOT, settlement_asset="USDT")


def test_the_multiplier_must_be_a_real_size():
    with pytest.raises(TradingValidationError, match="contract_multiplier"):
        Instrument(venue="v", symbol="S", base_asset="B", quote_asset="Q",
                   contract_multiplier=Decimal(0))


# --------------------------------------------------------------------------- #
# instrument specification
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("field", ["tick_size", "step_size"])
def test_a_grid_of_zero_is_refused(spot, field):
    sizes = {"tick_size": Decimal("0.01"), "step_size": Decimal("0.001")}
    sizes[field] = Decimal(0)

    with pytest.raises(TradingValidationError, match=field):
        InstrumentSpec(instrument=spot, **sizes)


def test_a_maximum_below_the_minimum_is_refused(spot):
    with pytest.raises(TradingValidationError, match="maximum_quantity"):
        InstrumentSpec(instrument=spot, tick_size=Decimal("0.01"),
                       step_size=Decimal("0.001"),
                       minimum_quantity=Decimal(5), maximum_quantity=Decimal(1))


def test_the_spec_names_the_rule_that_failed(spec):
    with pytest.raises(TradingValidationError, match="step_size"):
        spec.check(Decimal("43210.50"), Decimal("0.00005"))
    with pytest.raises(TradingValidationError, match="tick_size"):
        spec.check(Decimal("43210.505"), Decimal("0.5"))
    with pytest.raises(TradingValidationError, match="minimum_notional"):
        spec.check(Decimal("1.00"), Decimal("0.0001"))


def test_a_market_order_can_be_checked_without_a_price(spec):
    """It has none, so the notional rule cannot apply here — the engine that
    knows the expected fill price is the one that can check it."""
    spec.check(None, Decimal("0.5"))


def test_rounding_a_quantity_to_nothing_returns_nothing(spot):
    """Rather than raising. Whether an order that rounds away is an error or
    a no-op is the caller's question, and `check` is where it becomes one."""
    spec = InstrumentSpec(instrument=spot, tick_size=Decimal("0.01"),
                          step_size=Decimal(1))

    assert spec.normalize_quantity("0.4", Rounding.FLOOR) == 0
    with pytest.raises(TradingValidationError, match="greater than zero"):
        spec.check(None, Decimal(0))


# --------------------------------------------------------------------------- #
# order intents
# --------------------------------------------------------------------------- #


def test_a_market_order_is_valid_without_a_price(spot):
    order = an_intent(spot, order_type=OrderType.MARKET, limit_price=None)

    assert order.order_type is OrderType.MARKET
    assert order.limit_price is None


def test_a_market_order_carrying_a_limit_price_is_refused(spot):
    with pytest.raises(TradingValidationError) as raised:
        an_intent(spot, order_type=OrderType.MARKET)

    assert "limit_price must not be set" in str(raised.value)


def test_a_limit_order_without_a_price_is_refused(spot):
    with pytest.raises(TradingValidationError) as raised:
        an_intent(spot, limit_price=None)

    assert str(raised.value) == "limit_price is required for LIMIT orders"


def test_a_stop_order_needs_a_trigger(spot):
    with pytest.raises(TradingValidationError, match="trigger_price is required"):
        an_intent(spot, order_type=OrderType.STOP, limit_price=None)

    order = an_intent(spot, order_type=OrderType.STOP, limit_price=None,
                      trigger_price=Decimal("40000"))
    assert order.trigger_price == Decimal("40000")


def test_a_plain_limit_order_must_not_carry_a_trigger(spot):
    with pytest.raises(TradingValidationError, match="trigger_price must not be set"):
        an_intent(spot, trigger_price=Decimal("40000"))


@pytest.mark.parametrize("quantity", [Decimal(0), Decimal("-1"), "0", "-0.5"])
def test_an_order_for_nothing_or_less_is_refused(spot, quantity):
    with pytest.raises(TradingValidationError, match="quantity"):
        an_intent(spot, quantity=quantity)


def test_a_float_quantity_is_refused(spot):
    with pytest.raises(TradingValidationError, match="float"):
        an_intent(spot, quantity=0.5)


def test_a_naive_timestamp_is_refused(spot):
    with pytest.raises(TradingValidationError, match="timezone-aware"):
        an_intent(spot, created_at=datetime(2026, 3, 1, 12, 0))


def test_the_client_id_is_carried_exactly(spot):
    """Ours, and never regenerated. A random id minted in a constructor makes
    two runs of one backtest produce different objects."""
    order = an_intent(spot, client_order_id="strategy-a:7")

    assert order.client_order_id == "strategy-a:7"


def test_an_order_with_no_client_id_is_refused(spot):
    with pytest.raises(TradingValidationError, match="client_order_id"):
        an_intent(spot, client_order_id="")


def test_post_only_cannot_demand_an_immediate_fill(spot):
    """The only way it fills immediately is by taking, which is what
    post-only forbids. Venues reject it; saying so here is cheaper."""
    with pytest.raises(TradingValidationError, match="post_only"):
        an_intent(spot, post_only=True, time_in_force=TimeInForce.IOC)

    assert an_intent(spot, post_only=True).post_only is True


def test_the_notional_uses_the_contract_multiplier(perpetual):
    order = an_intent(perpetual, quantity=Decimal(10),
                      limit_price=Decimal("43000"))

    # 10 contracts * 43000 * 0.001 per contract
    assert order.notional() == Decimal("430.000")


def test_a_market_order_cannot_state_its_own_notional(spot):
    order = an_intent(spot, order_type=OrderType.MARKET, limit_price=None)

    with pytest.raises(TradingValidationError, match="no price of their own"):
        order.notional()
    assert order.notional(Decimal("43000")) == Decimal("21500.0")


def test_two_identical_intents_compare_equal(spot):
    """Determinism: the same inputs produce the same object, every run."""
    assert an_intent(spot) == an_intent(spot)


# --------------------------------------------------------------------------- #
# the risk boundary, as a type
# --------------------------------------------------------------------------- #


def test_an_approved_order_records_who_approved_it(spot):
    approved = ApprovedOrder(intent=an_intent(spot), approved_by="exposure-limit",
                             approved_at=WHEN)

    assert approved.client_order_id == "c-1"
    assert approved.approved_by == "exposure-limit"


def test_an_approval_cannot_be_anonymous(spot):
    with pytest.raises(TradingValidationError, match="approved_by"):
        ApprovedOrder(intent=an_intent(spot), approved_by="", approved_at=WHEN)


def test_a_rejection_carries_its_reason(spot):
    rejected = RejectedOrder(intent=an_intent(spot),
                             reason="notional above the per-order limit",
                             rejected_by="exposure-limit", rejected_at=WHEN)

    assert "per-order limit" in rejected.reason
    assert rejected.client_order_id == "c-1"


def test_execution_accepts_an_approved_order_and_not_an_intent(spot):
    """The boundary written as a signature rather than as a comment: what
    `submit` takes is what risk produces."""
    import inspect

    from comodor.trading import ExecutionGateway

    signature = inspect.signature(ExecutionGateway.submit)
    assert signature.parameters["order"].annotation == "ApprovedOrder"


# --------------------------------------------------------------------------- #
# fills
# --------------------------------------------------------------------------- #


def a_fill(instrument: Instrument, **over) -> Fill:
    base = {"fill_id": "f-1", "client_order_id": "c-1", "instrument": instrument,
            "side": Side.BUY, "price": Decimal("43210.50"),
            "quantity": Decimal("0.5"),
            "fee": Fee(amount=Decimal("0.021605"), asset="USDT"),
            "filled_at": WHEN}
    base.update(over)
    return Fill(**base)


def test_a_fill_keeps_its_fee_exactly(spot):
    """Not a rate, and not rounded. What reaches the portfolio is what the
    venue actually took."""
    fill = a_fill(spot)

    assert fill.fee.amount == Decimal("0.021605")
    assert fill.fee.asset == "USDT"
    assert str(fill.fee) == "0.021605 USDT"


def test_a_fee_may_be_zero_but_not_negative(spot):
    assert a_fill(spot, fee=Fee(amount=Decimal(0), asset="USDT")).fee.amount == 0

    with pytest.raises(TradingValidationError, match="fee amount"):
        Fee(amount=Decimal("-1"), asset="USDT")


def test_a_fee_needs_the_asset_it_was_charged_in(spot):
    """Frequently a third asset entirely, which a bare number cannot say."""
    with pytest.raises(TradingValidationError, match="fee asset"):
        Fee(amount=Decimal("0.1"), asset="")


@pytest.mark.parametrize("field", ["price", "quantity"])
def test_a_fill_of_nothing_is_refused(spot, field):
    with pytest.raises(TradingValidationError, match=field):
        a_fill(spot, **{field: Decimal(0)})


def test_a_fill_cannot_be_edited(spot):
    """It is history. A partially filled order produces several of these and
    the position is derived from them, rather than one record being edited."""
    fill = a_fill(spot)
    with pytest.raises(FrozenInstanceError):
        fill.quantity = Decimal(1)               # type: ignore[misc]


def test_a_fill_needs_an_aware_timestamp(spot):
    with pytest.raises(TradingValidationError, match="timezone-aware"):
        a_fill(spot, filled_at=datetime(2026, 3, 1))


def test_two_identical_fills_compare_equal(spot):
    assert a_fill(spot) == a_fill(spot)


def test_the_venue_id_is_separate_and_starts_empty(spot):
    """It does not exist until the exchange answers. One field meaning our id
    before submission and theirs afterwards is how a duplicate gets sent."""
    assert a_fill(spot).venue_order_id == ""
    assert a_fill(spot, venue_order_id="v-99").venue_order_id == "v-99"


def test_a_fills_notional_uses_the_multiplier(perpetual):
    fill = a_fill(perpetual, quantity=Decimal(10), price=Decimal("43000"))

    assert fill.notional == Decimal("430.000")


# --------------------------------------------------------------------------- #
# order state
# --------------------------------------------------------------------------- #


def test_an_order_state_names_a_status_from_the_vocabulary():
    state = OrderState(client_order_id="c-1", status=OrderStatus.PARTIALLY_FILLED,
                       filled_quantity=Decimal("0.25"))

    assert state.status is OrderStatus.PARTIALLY_FILLED
    assert state.filled_quantity == Decimal("0.25")


def test_a_status_outside_the_vocabulary_is_refused():
    with pytest.raises(TradingValidationError, match="OrderStatus"):
        OrderState(client_order_id="c-1", status="open")   # type: ignore[arg-type]


def test_reconciliation_has_somewhere_to_put_an_unknown_answer():
    """After a disconnect the venue has an order and we do not yet know its
    state. A model with nowhere to say that invites guessing."""
    state = OrderState(client_order_id="c-1", status=OrderStatus.UNKNOWN)

    assert state.status is OrderStatus.UNKNOWN


# --------------------------------------------------------------------------- #
# inverse contracts, whose arithmetic is not the linear one
# --------------------------------------------------------------------------- #


@pytest.fixture
def inverse() -> Instrument:
    """A coin-margined contract worth $1, settled in Bitcoin."""
    return Instrument(venue="v", symbol="XBTUSD", base_asset="BTC",
                      quote_asset="USD", market_type=MarketType.FUTURES,
                      settlement_asset="BTC", contract_multiplier=Decimal(1),
                      contract_type=ContractType.INVERSE)


def test_an_inverse_notional_does_not_multiply_by_the_price(inverse):
    """A hundred $1 contracts are worth $100 whether Bitcoin is at 20 000 or
    80 000. The linear formula overstates that by the price — here fifty
    thousand times — and the answer would pass every notional check and every
    exposure limit written against it."""
    order = an_intent(inverse, quantity=Decimal(100), limit_price=Decimal(50000))

    assert order.notional() == Decimal(100)


def test_the_same_size_is_linear_when_the_contract_is(spot):
    order = an_intent(spot, quantity=Decimal(100), limit_price=Decimal(50000))

    assert order.notional() == Decimal(5000000)


def test_an_inverse_notional_is_the_same_at_any_price(inverse):
    order = an_intent(inverse, quantity=Decimal(100), limit_price=Decimal(50000))

    assert order.notional(Decimal(20000)) == order.notional(Decimal(80000))


def test_fills_and_positions_use_the_same_formula(inverse):
    """One place, asked by everything. Four copies is four places for the
    inverse case to be forgotten, and it was, in all four."""
    from comodor.trading import FuturesPosition, PositionSide

    fill = a_fill(inverse, quantity=Decimal(100), price=Decimal(50000))
    position = FuturesPosition(instrument=inverse, side=PositionSide.LONG,
                               quantity=Decimal(100),
                               average_entry_price=Decimal(50000))

    assert fill.notional == Decimal(100)
    assert position.notional(Decimal(50000)) == Decimal(100)


def test_a_minimum_notional_check_uses_it_too(inverse):
    """Otherwise a hundred $1 contracts would clear a $1 000 000 minimum."""
    spec = InstrumentSpec(instrument=inverse, tick_size=Decimal("0.5"),
                          step_size=Decimal(1), minimum_notional=Decimal(1000))

    with pytest.raises(TradingValidationError, match="minimum_notional"):
        spec.check(Decimal(50000), Decimal(100))


def test_spot_cannot_be_inverse():
    """One unit of the base asset is one unit."""
    with pytest.raises(TradingValidationError, match="LINEAR"):
        Instrument(venue="v", symbol="S", base_asset="B", quote_asset="Q",
                   contract_type=ContractType.INVERSE)


def test_a_contract_is_linear_unless_it_says_otherwise(spot, perpetual):
    assert spot.contract_type is ContractType.LINEAR
    assert perpetual.contract_type is ContractType.LINEAR
    assert not spot.is_inverse


# --------------------------------------------------------------------------- #
# what the price checks accept
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("price", [Decimal(0), Decimal("-5.00")])
def test_a_price_of_zero_or_less_is_refused_by_the_spec(spot, price):
    """Zero sits exactly on every grid there is — `0 % 0.01` is `0` — so with
    no minimum notional configured it passed every check below."""
    spec = InstrumentSpec(instrument=spot, tick_size=Decimal("0.01"),
                          step_size=Decimal("0.1"))

    with pytest.raises(TradingValidationError, match="price"):
        spec.check(price, Decimal("1.0"))


# --------------------------------------------------------------------------- #
# post-only needs somewhere to rest
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("order_type,extra", [
    (OrderType.MARKET, {"limit_price": None}),
    (OrderType.STOP, {"limit_price": None, "trigger_price": Decimal(40000)}),
])
def test_post_only_needs_a_limit_price_to_rest_at(spot, order_type, extra):
    """It says "rest on the book, and cancel me rather than cross it". Both
    halves need a price to rest at, which these order types do not have."""
    with pytest.raises(TradingValidationError, match="post_only requires a limit price"):
        an_intent(spot, order_type=order_type, post_only=True, **extra)


def test_post_only_is_fine_on_a_limit_order(spot):
    assert an_intent(spot, post_only=True).post_only is True


# --------------------------------------------------------------------------- #
# an approval is not a security boundary, and says so
# --------------------------------------------------------------------------- #


def test_an_approval_cannot_predate_the_request_it_approves(spot):
    """The one lie about ordering the type can catch. It cannot stop a caller
    minting an approval — Python has no unforgeable capability — which is why
    the gateway contract requires revalidation instead of pretending."""
    earlier = datetime(2020, 1, 1, tzinfo=UTC)

    with pytest.raises(TradingValidationError, match="cannot predate"):
        ApprovedOrder(intent=an_intent(spot), approved_by="policy",
                      approved_at=earlier)


def test_a_rejection_cannot_predate_it_either(spot):
    with pytest.raises(TradingValidationError, match="before the intent"):
        RejectedOrder(intent=an_intent(spot), reason="too large",
                      rejected_by="policy",
                      rejected_at=datetime(2020, 1, 1, tzinfo=UTC))


def test_the_gateway_contract_requires_revalidation():
    """Written down rather than assumed, because the next phase will build on
    whichever answer this gives."""
    from comodor.trading import ExecutionGateway

    assert "revalidate" in ExecutionGateway.__doc__
