"""What is owned, what is exposed, and what that was worth at a moment.

**Spot inventory and a futures position are not the same thing**, and this
package refuses to model them with one class. Holding one Bitcoin is ownership:
it is an asset, it has no counterparty, and its worst case is that it becomes
worthless. Being long one Bitcoin contract is exposure: it is a claim marked
against margin, it has a counterparty, and its worst case is that it takes the
margin with it.

A single `Position(quantity=1)` cannot say which of those it is. Systems that
try end up with a `is_spot` flag, then two branches everywhere the flag is
read, then a bug where a spot balance is liquidated. Two types cost one import
and make the wrong code fail to compile rather than fail at three in the
morning.

Margin, funding and liquidation are not modelled here. They belong to the
engine that will maintain positions from fills, and inventing their fields now
would be inventing their semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .enums import PositionSide
from .errors import TradingValidationError
from .instruments import Instrument
from .validation import identifier, non_negative, positive, utc_of


@dataclass(frozen=True, slots=True)
class Balance:
    """How much of one asset an account holds, and how much of it is free.

    `available` is what a new order can spend. The difference between it and
    `total` is what existing orders and margin have already claimed, which is
    why a balance that reports only one number cannot answer "can I place this
    order" without asking somewhere else.
    """

    asset: str
    total: Decimal
    available: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", identifier(self.asset, "asset"))
        object.__setattr__(self, "total", non_negative(self.total, "total"))
        object.__setattr__(self, "available", non_negative(self.available, "available"))
        if self.available > self.total:
            raise TradingValidationError(
                f"available {self.available} exceeds total {self.total} for {self.asset}")

    @property
    def reserved(self) -> Decimal:
        """Held against open orders or margin, and not spendable."""
        return self.total - self.available


@dataclass(frozen=True, slots=True)
class SpotHolding:
    """An amount of an asset that is owned.

    Keyed by asset rather than by instrument, because that is what ownership
    is: buying BTC/USDT and buying BTC/EUR both leave you holding BTC, and a
    model keyed on the pair would report two holdings of the same coin.
    """

    asset: str
    quantity: Decimal
    #: What it cost on average, per unit, in `cost_asset`. Zero means unknown —
    #: an inventory restored from an exchange balance has no purchase history,
    #: and inventing one would make an unrealised profit out of nothing.
    average_cost: Decimal = Decimal(0)
    cost_asset: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", identifier(self.asset, "asset"))
        object.__setattr__(self, "quantity", non_negative(self.quantity, "quantity"))
        object.__setattr__(self, "average_cost",
                           non_negative(self.average_cost, "average_cost"))
        if self.average_cost and not self.cost_asset:
            raise TradingValidationError(
                "cost_asset is required when average_cost is set: a cost without "
                "a currency is a number, not a price")
        if self.cost_asset:
            object.__setattr__(self, "cost_asset",
                               identifier(self.cost_asset, "cost_asset"))


@dataclass(frozen=True, slots=True)
class FuturesPosition:
    """Exposure to an instrument, in one direction.

    `quantity` is unsigned and `side` carries the direction. The alternative —
    a signed quantity — makes `FLAT` unrepresentable except as zero, and then
    every comparison has to remember whether zero is long or short. Here a flat
    position says so.
    """

    instrument: Instrument
    side: PositionSide
    quantity: Decimal
    average_entry_price: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TradingValidationError(
                f"instrument must be an Instrument, got {type(self.instrument).__name__}")
        if not self.instrument.is_futures:
            raise TradingValidationError(
                f"{self.instrument} is a spot instrument; spot ownership is a "
                "SpotHolding, not a position")
        if not isinstance(self.side, PositionSide):
            raise TradingValidationError(
                f"side must be a PositionSide, got {type(self.side).__name__}")

        object.__setattr__(self, "quantity", non_negative(self.quantity, "quantity"))
        object.__setattr__(self, "average_entry_price",
                           non_negative(self.average_entry_price, "average_entry_price"))

        if self.side is PositionSide.FLAT:
            if self.quantity:
                raise TradingValidationError(
                    f"a FLAT position cannot hold {self.quantity}")
            return
        if not self.quantity:
            raise TradingValidationError(
                f"a {self.side.value} position of zero is FLAT; say so")
        if not self.average_entry_price:
            raise TradingValidationError(
                "average_entry_price is required for an open position")

    @property
    def signed_quantity(self) -> Decimal:
        """Positive when long, negative when short, zero when flat.

        Offered for arithmetic, not for storage. Netting two positions is
        easier with a sign; knowing which way one points is clearer without.
        """
        if self.side is PositionSide.LONG:
            return self.quantity
        if self.side is PositionSide.SHORT:
            return -self.quantity
        return Decimal(0)

    @property
    def is_open(self) -> bool:
        return self.side is not PositionSide.FLAT

    def notional(self, price: Decimal) -> Decimal:
        """What the exposure is worth at `price`."""
        mark = positive(price, "price")
        return self.quantity * mark * self.instrument.contract_multiplier


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """Everything the account held at one instant.

    A snapshot rather than a mutable ledger. Two of them can be compared, one
    can be written to disk and read back, and a backtest can keep every one it
    produced without any of them changing underneath it. The engine that
    advances the state from fills is a later phase; what it produces is these.
    """

    taken_at: datetime
    balances: tuple[Balance, ...] = field(default_factory=tuple)
    holdings: tuple[SpotHolding, ...] = field(default_factory=tuple)
    positions: tuple[FuturesPosition, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "taken_at", utc_of(self.taken_at, "taken_at"))
        object.__setattr__(self, "balances", tuple(self.balances))
        object.__setattr__(self, "holdings", tuple(self.holdings))
        object.__setattr__(self, "positions", tuple(self.positions))

        _no_duplicates([balance.asset for balance in self.balances], "balance")
        _no_duplicates([holding.asset for holding in self.holdings], "holding")
        _no_duplicates([str(position.instrument) for position in self.positions],
                       "position")

    def balance(self, asset: str) -> Balance | None:
        """The balance for `asset`, or nothing if the account holds none."""
        wanted = identifier(asset, "asset")
        return next((item for item in self.balances if item.asset == wanted), None)

    def holding(self, asset: str) -> SpotHolding | None:
        wanted = identifier(asset, "asset")
        return next((item for item in self.holdings if item.asset == wanted), None)

    def position(self, instrument: Instrument) -> FuturesPosition | None:
        return next((item for item in self.positions
                     if item.instrument == instrument), None)


def _no_duplicates(keys: list[str], what: str) -> None:
    """One entry per thing.

    Two balances for the same asset is not a portfolio with extra detail; it is
    a portfolio whose total depends on which one a reader happens to find
    first.
    """
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            raise TradingValidationError(f"duplicate {what} for {key}")
        seen.add(key)
