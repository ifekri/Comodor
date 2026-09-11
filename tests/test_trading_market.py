"""Market events, portfolios, and the seams between them.

The candle invariants are the ones worth having: a bar whose high sits below
its open is a parsing bug, and a backtest that accepts it silently produces
something that looks like a discovery. Refusing it at construction attributes
the fault to the feed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterator

import pytest

from comodor.trading import (
    Balance,
    Candle,
    Clock,
    ExecutionGateway,
    FuturesPosition,
    Instrument,
    MarketDataSource,
    MarketEvent,
    MarketType,
    PortfolioSnapshot,
    PositionSide,
    Quote,
    RiskPolicy,
    SpotHolding,
    Strategy,
    TradeTick,
    TradingValidationError,
)

UTC = timezone.utc
OPEN = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
CLOSE = OPEN + timedelta(minutes=1)


@pytest.fixture
def spot() -> Instrument:
    return Instrument(venue="kucoin", symbol="BTC-USDT",
                      base_asset="BTC", quote_asset="USDT")


@pytest.fixture
def perpetual() -> Instrument:
    return Instrument(venue="kucoin", symbol="XBTUSDTM", base_asset="BTC",
                      quote_asset="USDT", market_type=MarketType.FUTURES,
                      settlement_asset="USDT")


def a_candle(instrument: Instrument, **over) -> Candle:
    base = {"instrument": instrument, "open": Decimal("43000"),
            "high": Decimal("43500"), "low": Decimal("42800"),
            "close": Decimal("43200"), "volume": Decimal("12.5"),
            "open_time": OPEN, "close_time": CLOSE}
    base.update(over)
    return Candle(**base)


# --------------------------------------------------------------------------- #
# candles
# --------------------------------------------------------------------------- #


def test_a_well_formed_candle_keeps_its_decimals(spot):
    candle = a_candle(spot)

    assert candle.close == Decimal("43200")
    assert candle.volume == Decimal("12.5")
    assert isinstance(candle.open, Decimal)


def test_a_high_below_the_body_is_refused(spot):
    with pytest.raises(TradingValidationError, match="high"):
        a_candle(spot, high=Decimal("42900"))


def test_a_low_above_the_body_is_refused(spot):
    with pytest.raises(TradingValidationError, match="low"):
        a_candle(spot, low=Decimal("43100"))


def test_a_flat_candle_is_valid(spot):
    """Nothing traded, so every price is the same. Legal, and common on an
    illiquid pair — refusing it would make a real feed unreadable."""
    flat = a_candle(spot, open=Decimal(100), high=Decimal(100),
                    low=Decimal(100), close=Decimal(100), volume=Decimal(0))

    assert flat.high == flat.low


def test_negative_volume_is_refused(spot):
    with pytest.raises(TradingValidationError, match="volume"):
        a_candle(spot, volume=Decimal("-1"))


def test_a_candle_that_ends_before_it_starts_is_refused(spot):
    with pytest.raises(TradingValidationError, match="before"):
        a_candle(spot, close_time=OPEN)


def test_candle_times_must_be_aware(spot):
    with pytest.raises(TradingValidationError, match="timezone-aware"):
        a_candle(spot, open_time=datetime(2026, 3, 1, 12, 0))


def test_a_candle_is_timestamped_at_its_close(spot):
    """A bar is only known once its window has ended. A strategy acting on
    the open time of the bar it is inside is reading the future, which is the
    commonest way a backtest produces a return nobody can repeat."""
    assert a_candle(spot).timestamp == CLOSE


def test_a_candle_is_a_market_event(spot):
    assert isinstance(a_candle(spot), MarketEvent)


# --------------------------------------------------------------------------- #
# ticks and quotes
# --------------------------------------------------------------------------- #


def test_a_trade_tick_carries_what_printed(spot):
    tick = TradeTick(instrument=spot, price=Decimal("43210.5"),
                     quantity=Decimal("0.01"), timestamp=OPEN)

    assert tick.price == Decimal("43210.5")
    assert tick.aggressor is None, "an absent answer is not a guess"
    assert isinstance(tick, MarketEvent)


def test_a_tick_of_zero_size_is_refused(spot):
    with pytest.raises(TradingValidationError, match="quantity"):
        TradeTick(instrument=spot, price=Decimal(1), quantity=Decimal(0),
                  timestamp=OPEN)


def test_a_quote_reports_its_spread_and_mid_exactly(spot):
    quote = Quote(instrument=spot, bid_price=Decimal("43210.10"),
                  ask_price=Decimal("43210.30"), timestamp=OPEN)

    assert quote.spread == Decimal("0.20")
    assert quote.mid == Decimal("43210.20")


def test_a_crossed_quote_is_refused(spot):
    """Either a bad feed or a stale side, and a strategy trading on it is
    trading on nothing."""
    with pytest.raises(TradingValidationError, match="crossed"):
        Quote(instrument=spot, bid_price=Decimal(101), ask_price=Decimal(100),
              timestamp=OPEN)


def test_a_locked_quote_is_allowed(spot):
    """Bid equal to ask happens on a real book, briefly."""
    quote = Quote(instrument=spot, bid_price=Decimal(100),
                  ask_price=Decimal(100), timestamp=OPEN)

    assert quote.spread == 0


# --------------------------------------------------------------------------- #
# balances and inventory
# --------------------------------------------------------------------------- #


def test_a_balance_separates_what_is_free_from_what_is_held():
    balance = Balance(asset="USDT", total=Decimal(1000), available=Decimal(400))

    assert balance.reserved == Decimal(600)


def test_available_cannot_exceed_the_total():
    with pytest.raises(TradingValidationError, match="exceeds total"):
        Balance(asset="USDT", total=Decimal(100), available=Decimal(200))


def test_spot_inventory_is_keyed_by_asset_not_by_pair():
    """Buying BTC/USDT and BTC/EUR both leave you holding BTC. A model keyed
    on the pair would report two holdings of one coin."""
    holding = SpotHolding(asset="BTC", quantity=Decimal("1.5"),
                          average_cost=Decimal("41000"), cost_asset="USDT")

    assert holding.asset == "BTC"
    assert holding.average_cost == Decimal("41000")


def test_a_cost_without_a_currency_is_refused():
    with pytest.raises(TradingValidationError, match="cost_asset"):
        SpotHolding(asset="BTC", quantity=Decimal(1), average_cost=Decimal(41000))


def test_an_inventory_restored_from_an_exchange_may_have_no_cost():
    """It has no purchase history, and inventing one would make an unrealised
    profit out of nothing."""
    holding = SpotHolding(asset="BTC", quantity=Decimal("1.5"))

    assert holding.average_cost == 0
    assert holding.cost_asset == ""


# --------------------------------------------------------------------------- #
# futures exposure, which is not inventory
# --------------------------------------------------------------------------- #


def test_a_futures_position_signs_its_quantity_by_side(perpetual):
    long = FuturesPosition(instrument=perpetual, side=PositionSide.LONG,
                           quantity=Decimal(3), average_entry_price=Decimal(43000))
    short = FuturesPosition(instrument=perpetual, side=PositionSide.SHORT,
                            quantity=Decimal(3), average_entry_price=Decimal(43000))

    assert long.signed_quantity == Decimal(3)
    assert short.signed_quantity == Decimal(-3)
    assert long.is_open and short.is_open


def test_a_flat_position_holds_nothing_and_says_so(perpetual):
    flat = FuturesPosition(instrument=perpetual, side=PositionSide.FLAT,
                           quantity=Decimal(0), average_entry_price=Decimal(0))

    assert flat.signed_quantity == 0
    assert not flat.is_open


def test_a_flat_position_cannot_hold_a_quantity(perpetual):
    with pytest.raises(TradingValidationError, match="FLAT"):
        FuturesPosition(instrument=perpetual, side=PositionSide.FLAT,
                        quantity=Decimal(3), average_entry_price=Decimal(43000))


def test_an_open_position_of_zero_is_flat_and_must_say_so(perpetual):
    with pytest.raises(TradingValidationError, match="FLAT"):
        FuturesPosition(instrument=perpetual, side=PositionSide.LONG,
                        quantity=Decimal(0), average_entry_price=Decimal(43000))


def test_spot_ownership_cannot_be_expressed_as_a_position(spot):
    """The distinction this package refuses to blur. Holding a coin is
    ownership; being long a contract is exposure marked against margin."""
    with pytest.raises(TradingValidationError, match="SpotHolding"):
        FuturesPosition(instrument=spot, side=PositionSide.LONG,
                        quantity=Decimal(1), average_entry_price=Decimal(43000))


def test_a_positions_notional_needs_a_mark_price(perpetual):
    position = FuturesPosition(instrument=perpetual, side=PositionSide.LONG,
                               quantity=Decimal(2),
                               average_entry_price=Decimal(43000))

    assert position.notional(Decimal(44000)) == Decimal(88000)


# --------------------------------------------------------------------------- #
# snapshots
# --------------------------------------------------------------------------- #


def test_a_snapshot_finds_what_it_holds(spot, perpetual):
    snapshot = PortfolioSnapshot(
        taken_at=OPEN,
        balances=(Balance(asset="USDT", total=Decimal(1000), available=Decimal(1000)),),
        holdings=(SpotHolding(asset="BTC", quantity=Decimal("0.5")),),
        positions=(FuturesPosition(instrument=perpetual, side=PositionSide.SHORT,
                                   quantity=Decimal(1),
                                   average_entry_price=Decimal(43000)),))

    assert snapshot.balance("USDT").total == Decimal(1000)
    assert snapshot.holding("BTC").quantity == Decimal("0.5")
    assert snapshot.position(perpetual).side is PositionSide.SHORT
    assert snapshot.balance("ETH") is None
    assert snapshot.position(spot) is None


def test_a_snapshot_refuses_to_hold_one_thing_twice():
    """Two balances for one asset is not extra detail; it is a total that
    depends on which entry a reader finds first."""
    twice = (Balance(asset="USDT", total=Decimal(1), available=Decimal(1)),
             Balance(asset="USDT", total=Decimal(2), available=Decimal(2)))

    with pytest.raises(TradingValidationError, match="duplicate"):
        PortfolioSnapshot(taken_at=OPEN, balances=twice)


def test_two_identical_snapshots_compare_equal():
    """Which is what lets a backtest assert on the state it reached."""
    def build() -> PortfolioSnapshot:
        return PortfolioSnapshot(
            taken_at=OPEN,
            balances=(Balance(asset="USDT", total=Decimal(10),
                              available=Decimal(10)),))

    assert build() == build()


def test_an_empty_snapshot_is_valid():
    assert PortfolioSnapshot(taken_at=OPEN).balances == ()


# --------------------------------------------------------------------------- #
# the seams
# --------------------------------------------------------------------------- #


def test_a_frozen_clock_satisfies_the_protocol():
    """Nothing in the package reads the system clock, so a test can pin it."""
    class Frozen:
        def now(self) -> datetime:
            return OPEN

    assert isinstance(Frozen(), Clock)
    assert Frozen().now() == OPEN


def test_a_source_of_events_satisfies_the_protocol(spot):
    """A strategy consuming this cannot tell a CSV from a socket, which is
    the entire purpose of the envelope."""
    class Recorded:
        def stream(self, instruments: tuple[Instrument, ...]) -> Iterator[Candle]:
            yield a_candle(instruments[0])

    source = Recorded()
    assert isinstance(source, MarketDataSource)
    assert [event.instrument for event in source.stream((spot,))] == [spot]


@pytest.mark.parametrize("protocol,method", [
    (ExecutionGateway, "submit"),
    (ExecutionGateway, "cancel"),
    (RiskPolicy, "evaluate"),
    (Strategy, "on_event"),
    (Clock, "now"),
    (MarketDataSource, "stream"),
])
def test_the_seams_stay_small(protocol, method):
    """Named individually so that adding a speculative method to any of them
    is a visible change rather than a quiet one."""
    assert hasattr(protocol, method)


def test_no_gateway_is_implemented():
    """`ExecutionGateway` is a contract. Anything in this package claiming to
    implement it would be something that can send an order."""
    import comodor.trading as trading

    implementations = [
        name for name in trading.__all__
        if isinstance(getattr(trading, name), type)
        and not getattr(getattr(trading, name), "_is_protocol", False)
        and hasattr(getattr(trading, name), "submit")
    ]
    assert implementations == []


def test_a_strategy_is_given_nothing_to_execute_with():
    """It receives an event and a portfolio and returns intents. A strategy
    that could submit directly would be one that can bypass risk."""
    import inspect

    parameters = set(inspect.signature(Strategy.on_event).parameters)

    assert parameters == {"self", "event", "portfolio"}
