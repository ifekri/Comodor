"""The closed sets the domain is built from.

Every one of these is a vocabulary that a backtest, a replay, a paper run and a
live session must agree on. An exchange calls a good-till-cancelled order
`GTC`, `gtc`, `GoodTillCancel` or `1` depending on which exchange and which
version of its API; the adapter translates, and everything above the adapter
sees one spelling.

They are `str` enums so that a value survives being written to a log, a file or
a message and read back as itself. `TimeInForce.GTC.value == "GTC"`, and
`TimeInForce("GTC")` returns it — which is what makes serialisation a
round-trip rather than a lossy export.
"""

from __future__ import annotations

from enum import Enum


class TradingMode(str, Enum):
    """Where a run's fills come from.

    The same strategy, risk rules and portfolio accounting run in all four.
    That is the point of the shared core: these are four environments for one
    system, not four systems.

    * `BACKTEST` — historical data, replayed as fast as it can be read.
    * `MARKET_REPLAY` — historical data, replayed at its original pace.
    * `PAPER` — live data, simulated fills, no money.
    * `LIVE` — real orders. Not implemented, and off by default.
    """

    BACKTEST = "BACKTEST"
    MARKET_REPLAY = "MARKET_REPLAY"
    PAPER = "PAPER"
    LIVE = "LIVE"


#: What a run is when nobody has chosen.
#:
#: Backtest rather than paper: paper needs a live market feed, and a default
#: that quietly opens a connection is not a default. Nothing in this package
#: defaults to `LIVE`, and `require_simulated` is what enforces that.
DEFAULT_TRADING_MODE = TradingMode.BACKTEST

#: The modes that can actually run. `LIVE` is absent because there is no
#: execution gateway behind it — see `require_simulated`.
SIMULATED_MODES = frozenset({
    TradingMode.BACKTEST, TradingMode.MARKET_REPLAY, TradingMode.PAPER,
})


class MarketType(str, Enum):
    """What kind of thing is being traded.

    The distinction earns its place at the domain level because the two settle
    differently: spot moves an asset you then own, futures moves an exposure
    that is marked against a margin balance. Confusing them is how a position
    size ends up meaning two things.
    """

    SPOT = "SPOT"
    FUTURES = "FUTURES"


class ContractType(str, Enum):
    """Which way round a futures contract is denominated.

    The distinction changes the arithmetic, not just the labelling, which is
    why it is a field rather than a note.

    * `LINEAR` — one contract is `contract_multiplier` units of the **base**
      asset, and its value is `quantity x price x multiplier`. A USDT-margined
      perpetual is linear.
    * `INVERSE` — one contract is `contract_multiplier` units of the **quote**
      asset, and its value in quote terms is `quantity x multiplier`: it does
      not depend on the price at all. What varies with price is how much of
      the settlement asset that is worth. A coin-margined contract of $1 is
      inverse.

    Applying the linear formula to an inverse contract overstates a hundred
    $1 contracts at 50 000 by a factor of fifty thousand, which would pass
    every minimum-notional check and every exposure limit ever written.

    Spot is always `LINEAR`: one unit is one unit.
    """

    LINEAR = "LINEAR"
    INVERSE = "INVERSE"


class Side(str, Enum):
    """Which way an order goes."""

    BUY = "BUY"
    SELL = "SELL"


class PositionSide(str, Enum):
    """Which way an exposure points.

    Not the same as `Side`, and kept separate from the first commit for that
    reason. A `SELL` closes a `LONG` and opens a `SHORT`, and a codebase that
    stores one field for both eventually asks "is this order a sell, or is
    this position short" and cannot tell.
    """

    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class OrderType(str, Enum):
    """How the order wants to be filled.

    `MARKET` and `LIMIT` are the two this stage models the rules for. `STOP`
    and `STOP_LIMIT` are named because leaving them out would mean changing
    this vocabulary later and migrating anything that stored it — but nothing
    in this package implements trigger behaviour, and the validation rules
    treat them as their underlying type.
    """

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


#: Types that carry a limit price, and require one.
PRICED_TYPES = frozenset({OrderType.LIMIT, OrderType.STOP_LIMIT})
#: Types that carry a trigger price, and require one.
TRIGGERED_TYPES = frozenset({OrderType.STOP, OrderType.STOP_LIMIT})


class TimeInForce(str, Enum):
    """How long the order stands.

    `POST_ONLY` is deliberately not here. It is not a duration — it is an
    instruction about what to do if the order would take liquidity — and a
    good-till-cancelled post-only order is a real and common thing that a
    single field cannot express. It belongs on `OrderIntent` as its own flag,
    which is where it is.
    """

    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class OrderStatus(str, Enum):
    """Where an order has got to.

    A vocabulary, not a state machine: this stage names the states so that
    every later stage agrees on them, and leaves the transitions to the
    execution engine that will own them.

    `UNKNOWN` is here on purpose. Reconciliation after a disconnect has to be
    able to say "the venue has an order and I do not yet know its state",
    and a model with nowhere to put that answer invites guessing instead.
    """

    PENDING_SUBMIT = "PENDING_SUBMIT"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


#: Statuses after which nothing further happens to the order.
TERMINAL_STATUSES = frozenset({
    OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED,
})


class Rounding(str, Enum):
    """Which way a value moves when it does not sit on the grid.

    There is no default anywhere in this package, and that is the whole
    design. Rounding a quantity up can spend money the caller does not have;
    rounding a price the wrong way can cross the spread. Which one is correct
    depends on what the caller is doing, so the caller says.
    """

    FLOOR = "FLOOR"
    CEIL = "CEIL"
    NEAREST = "NEAREST"
