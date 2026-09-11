"""What the market did, in the shapes a strategy is allowed to see.

Three event types and one envelope. The envelope is the point: a strategy
receives `MarketEvent`s and cannot tell whether they were read from a CSV,
replayed from a database at their original pace, or pushed down a live socket
seconds ago. That is what makes a backtest and a paper run the same program.

Order books are absent, deliberately. A full book with per-level maintenance is
the expensive part of a market data engine, the first backtest does not need
it, and building it now would mean designing it against no requirements. When a
strategy needs depth, `Quote` is the natural place for it to grow.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, Union, runtime_checkable

from .enums import Side
from .errors import TradingValidationError
from .instruments import Instrument
from .validation import identifier, non_negative, positive, utc_of


@runtime_checkable
class MarketEvent(Protocol):
    """Anything that happened in a market, at a time, to an instrument.

    The two fields every consumer needs to order and route an event, and
    nothing else. A strategy that only wants candles matches on the concrete
    type; a recorder that writes everything to disk needs only this.
    """

    @property
    def instrument(self) -> Instrument: ...

    @property
    def timestamp(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class TradeTick:
    """One trade that printed on the tape."""

    instrument: Instrument
    price: Decimal
    quantity: Decimal
    timestamp: datetime
    #: Which side took liquidity, when the venue says. Not every feed does,
    #: and an absent answer is `None` rather than a guess — inferring the
    #: aggressor from the price is a model, not an observation.
    aggressor: Side | None = None
    trade_id: str = ""

    def __post_init__(self) -> None:
        _require_instrument(self.instrument)
        object.__setattr__(self, "price", positive(self.price, "price"))
        object.__setattr__(self, "quantity", positive(self.quantity, "quantity"))
        object.__setattr__(self, "timestamp", utc_of(self.timestamp, "timestamp"))
        if self.aggressor is not None and not isinstance(self.aggressor, Side):
            raise TradingValidationError(
                f"aggressor must be a Side or None, got {type(self.aggressor).__name__}")
        if self.trade_id:
            object.__setattr__(self, "trade_id", identifier(self.trade_id, "trade_id"))


@dataclass(frozen=True, slots=True)
class Quote:
    """The best bid and ask, and how much is showing at each."""

    instrument: Instrument
    bid_price: Decimal
    ask_price: Decimal
    timestamp: datetime
    bid_size: Decimal = Decimal(0)
    ask_size: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        _require_instrument(self.instrument)
        object.__setattr__(self, "bid_price", positive(self.bid_price, "bid_price"))
        object.__setattr__(self, "ask_price", positive(self.ask_price, "ask_price"))
        object.__setattr__(self, "bid_size", non_negative(self.bid_size, "bid_size"))
        object.__setattr__(self, "ask_size", non_negative(self.ask_size, "ask_size"))
        object.__setattr__(self, "timestamp", utc_of(self.timestamp, "timestamp"))

        # A crossed quote is either a bad feed or a stale side, and either way
        # a strategy that trades on it is trading on nothing. Refused here so
        # the fault is attributed to the feed rather than to the strategy.
        if self.bid_price > self.ask_price:
            raise TradingValidationError(
                f"crossed quote: bid {self.bid_price} is above ask {self.ask_price}")

    @property
    def spread(self) -> Decimal:
        return self.ask_price - self.bid_price

    @property
    def mid(self) -> Decimal:
        """Halfway between the two.

        Exact, because both sides are `Decimal` and the divisor is `2` — this
        is the arithmetic that a float would round, thousands of times, into a
        backtest result nobody can reproduce.
        """
        return (self.bid_price + self.ask_price) / 2


@dataclass(frozen=True, slots=True)
class Candle:
    """One bar: open, high, low, close and volume over a window.

    The invariants are checked rather than assumed. A bar whose high is below
    its open is a data error, and the cheapest place to find it is the moment
    it is read — a backtest that silently accepts it produces a result that
    looks like a strategy discovery and is a parsing bug.
    """

    instrument: Instrument
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    open_time: datetime
    close_time: datetime

    def __post_init__(self) -> None:
        _require_instrument(self.instrument)
        for name in ("open", "high", "low", "close"):
            object.__setattr__(self, name, positive(getattr(self, name), name))
        object.__setattr__(self, "volume", non_negative(self.volume, "volume"))
        object.__setattr__(self, "open_time", utc_of(self.open_time, "open_time"))
        object.__setattr__(self, "close_time", utc_of(self.close_time, "close_time"))

        if self.open_time >= self.close_time:
            raise TradingValidationError(
                f"open_time {self.open_time.isoformat()} must be before "
                f"close_time {self.close_time.isoformat()}")

        highest = max(self.open, self.close, self.low)
        if self.high < highest:
            raise TradingValidationError(
                f"high {self.high} is below open/close/low (highest of those is {highest})")
        lowest = min(self.open, self.close, self.high)
        if self.low > lowest:
            raise TradingValidationError(
                f"low {self.low} is above open/close/high (lowest of those is {lowest})")

    @property
    def timestamp(self) -> datetime:
        """When this bar is known.

        Its close, not its open. A bar is only complete once the window has
        ended, and a strategy that acts on the open time of the bar it is
        inside is reading the future — which is the single most common way a
        backtest produces a return nobody can repeat with real money.
        """
        return self.close_time


#: Every concrete thing a market data source may yield.
#:
#: A union rather than a base class: these have nothing to share beyond the two
#: fields `MarketEvent` already names, and an inheritance hierarchy would exist
#: only to hold that.
MarketData = Union[TradeTick, Quote, Candle]


def _require_instrument(value: object) -> None:
    if not isinstance(value, Instrument):
        raise TradingValidationError(
            f"instrument must be an Instrument, got {type(value).__name__}")
