"""The trading core: what a backtest, a replay, a paper run and a live session
all have to agree on.

Nothing here trades. There is no exchange, no network call, no credential and
no order that can reach a venue — this is the vocabulary and the invariants
that the phases after it are built on, so that those four environments end up
being four ways of running one system rather than four systems.

Three rules the rest of the package exists to enforce:

* **Money is `Decimal`.** Floats are refused at construction, not converted.
* **Time is timezone-aware UTC.** Naive datetimes are refused, and nothing
  reads the system clock — the clock is injected.
* **Live is off.** `require_simulated` is the only door, and there is nothing
  behind it.

See `docs/trading.md` for the architecture these types encode.
"""

from __future__ import annotations

from .enums import (
    DEFAULT_TRADING_MODE,
    PRICED_TYPES,
    SIMULATED_MODES,
    TERMINAL_STATUSES,
    TRIGGERED_TYPES,
    ContractType,
    MarketType,
    OrderStatus,
    OrderType,
    PositionSide,
    Rounding,
    Side,
    TimeInForce,
    TradingMode,
)
from .errors import LiveTradingDisabledError, TradingError, TradingValidationError
from .instruments import Instrument, InstrumentSpec
from .market import Candle, MarketData, MarketEvent, Quote, TradeTick
from .orders import (
    ApprovedOrder,
    Fee,
    Fill,
    OrderIntent,
    OrderState,
    RejectedOrder,
)
from .portfolio import Balance, FuturesPosition, PortfolioSnapshot, SpotHolding
from .protocols import (
    Clock,
    ExecutionGateway,
    MarketDataSource,
    RiskPolicy,
    Strategy,
    require_simulated,
)

__all__ = [
    # modes and the live gate
    "TradingMode", "DEFAULT_TRADING_MODE", "SIMULATED_MODES", "require_simulated",
    # vocabulary
    "MarketType", "ContractType", "Side", "PositionSide", "OrderType",
    "TimeInForce",
    "OrderStatus", "Rounding",
    "PRICED_TYPES", "TRIGGERED_TYPES", "TERMINAL_STATUSES",
    # what is traded
    "Instrument", "InstrumentSpec",
    # the execution path
    "OrderIntent", "ApprovedOrder", "RejectedOrder", "OrderState", "Fill", "Fee",
    # what the market did
    "MarketEvent", "MarketData", "TradeTick", "Quote", "Candle",
    # what is held
    "Balance", "SpotHolding", "FuturesPosition", "PortfolioSnapshot",
    # the seams
    "Clock", "MarketDataSource", "ExecutionGateway", "RiskPolicy", "Strategy",
    # failures
    "TradingError", "TradingValidationError", "LiveTradingDisabledError",
]
