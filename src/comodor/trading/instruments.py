"""What is being traded, and the rules for trading it.

Two models, deliberately not one. **Identity** is what an instrument *is* —
which venue, which symbol, which pair, spot or futures — and it never changes.
**Specification** is what the venue currently allows: the tick, the lot, the
minimum order. Those change; a venue can halve a tick size on a Tuesday.

Keeping them apart means a position, a fill and an order can all hold the same
identity and compare equal, without any of them carrying a snapshot of rules
that may be stale. It also means the identity can be a dictionary key, which is
what a portfolio needs it to be.

Venue names live here as plain strings. `Instrument(venue="kucoin", ...)` is
data; `KuCoinInstrument` would be a type, and a type is a decision the core is
not allowed to make — the whole point of this layer is that an adapter can be
added without the domain learning its name.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .enums import ContractType, MarketType, Rounding
from .errors import TradingValidationError
from .validation import DecimalLike, identifier, non_negative, positive, quantize


@dataclass(frozen=True, slots=True)
class Instrument:
    """One tradable thing, identified.

    Frozen and hashable so it can key a portfolio, and so that two objects
    describing the same market compare equal without anybody writing an
    `is_same_instrument` helper that drifts from `__eq__`.
    """

    venue: str
    symbol: str
    base_asset: str
    quote_asset: str
    market_type: MarketType = MarketType.SPOT
    #: What a futures contract pays out in. Often the quote asset, but not for
    #: an inverse contract, where the two differ and confusing them inverts
    #: the sign of the profit.
    settlement_asset: str = ""
    #: How much one contract represents — of the base asset when linear, of
    #: the quote asset when inverse. One, for spot.
    contract_multiplier: Decimal = Decimal(1)
    #: Which way round the contract is denominated. Spot is always linear.
    contract_type: ContractType = ContractType.LINEAR

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", identifier(self.venue, "venue"))
        object.__setattr__(self, "symbol", identifier(self.symbol, "symbol"))
        object.__setattr__(self, "base_asset", identifier(self.base_asset, "base_asset"))
        object.__setattr__(self, "quote_asset", identifier(self.quote_asset, "quote_asset"))
        if not isinstance(self.market_type, MarketType):
            raise TradingValidationError(
                f"market_type must be a MarketType, got {type(self.market_type).__name__}")

        multiplier = positive(self.contract_multiplier, "contract_multiplier")
        object.__setattr__(self, "contract_multiplier", multiplier)

        if not isinstance(self.contract_type, ContractType):
            raise TradingValidationError(
                f"contract_type must be a ContractType, "
                f"got {type(self.contract_type).__name__}")

        if self.market_type is MarketType.SPOT:
            if self.settlement_asset:
                raise TradingValidationError(
                    "settlement_asset applies to futures; spot settles in its own assets")
            if self.contract_type is not ContractType.LINEAR:
                raise TradingValidationError(
                    "spot is always LINEAR: one unit of the base asset is one unit")
            return

        # A futures contract has to say what it pays out in. Defaulting to the
        # quote asset would be right for the common linear case and silently
        # wrong for an inverse one, which is the expensive half.
        settlement = identifier(self.settlement_asset, "settlement_asset")
        object.__setattr__(self, "settlement_asset", settlement)

    @property
    def is_spot(self) -> bool:
        return self.market_type is MarketType.SPOT

    @property
    def is_futures(self) -> bool:
        return self.market_type is MarketType.FUTURES

    @property
    def is_inverse(self) -> bool:
        return self.contract_type is ContractType.INVERSE

    def notional(self, price: Decimal, quantity: Decimal) -> Decimal:
        """What `quantity` at `price` is worth, in the quote asset.

        The one place this arithmetic lives. An order, a fill, a position and
        a minimum-notional check all ask the instrument rather than each
        multiplying it out, because four copies of a formula is four places
        for the inverse case to be forgotten — and it was, in all four, until
        `ContractType` existed to make the difference sayable.

        Inverse contracts are denominated in the quote asset, so their quote
        notional is independent of price: a hundred $1 contracts are worth
        $100 whether Bitcoin is at 20 000 or 80 000.
        """
        if self.is_inverse:
            return quantity * self.contract_multiplier
        return quantity * price * self.contract_multiplier

    def __str__(self) -> str:
        return f"{self.venue}:{self.symbol}"


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    """What the venue will accept for an instrument.

    Every field is a constraint an order can fail, which is why they are
    together: a size that passes the step and fails the minimum notional is
    rejected by the exchange, and finding that out from the exchange is the
    slow way to learn it.
    """

    instrument: Instrument
    #: The price grid. `0.01` means prices are whole cents.
    tick_size: Decimal
    #: The quantity grid, called lot size on some venues.
    step_size: Decimal
    minimum_quantity: Decimal = Decimal(0)
    #: Price times quantity must reach this. Denominated in the quote asset.
    minimum_notional: Decimal = Decimal(0)
    #: Zero means the venue publishes no ceiling, not that nothing is allowed.
    maximum_quantity: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TradingValidationError(
                f"instrument must be an Instrument, got {type(self.instrument).__name__}")
        object.__setattr__(self, "tick_size", positive(self.tick_size, "tick_size"))
        object.__setattr__(self, "step_size", positive(self.step_size, "step_size"))
        object.__setattr__(self, "minimum_quantity",
                           non_negative(self.minimum_quantity, "minimum_quantity"))
        object.__setattr__(self, "minimum_notional",
                           non_negative(self.minimum_notional, "minimum_notional"))
        object.__setattr__(self, "maximum_quantity",
                           non_negative(self.maximum_quantity, "maximum_quantity"))

        if self.maximum_quantity and self.maximum_quantity < self.minimum_quantity:
            raise TradingValidationError(
                f"maximum_quantity {self.maximum_quantity} is below "
                f"minimum_quantity {self.minimum_quantity}")

    # -- normalisation ------------------------------------------------------ #

    def normalize_price(self, price: DecimalLike, rounding: Rounding) -> Decimal:
        """`price` moved onto the tick grid.

        `rounding` has no default and never will. Which direction is correct
        depends on the side and the intent — a buyer protecting a limit rounds
        down, a seller rounds up — and a package that picked one would be
        making that decision on the caller's behalf, silently, in the one place
        it costs money.
        """
        return quantize(positive(price, "price"), self.tick_size, rounding, "price")

    def normalize_quantity(self, quantity: DecimalLike, rounding: Rounding) -> Decimal:
        """`quantity` moved onto the step grid.

        The result can be zero — rounding `0.4` lots down to a step of `1`
        leaves nothing — and that is returned rather than raised on. Whether
        an order that rounds away to nothing is an error or a no-op is the
        caller's question; `validate_order` is where it becomes one.
        """
        return quantize(non_negative(quantity, "quantity"), self.step_size,
                        rounding, "quantity")

    # -- the venue's own limits --------------------------------------------- #

    def check(self, price: Decimal | None, quantity: Decimal) -> None:
        """Raise if the venue would reject this size, and say which rule.

        Price is optional because a market order has none, and the notional
        rule cannot then be checked here — the engine that knows the expected
        fill price is the one that can check it.
        """
        if quantity <= 0:
            raise TradingValidationError(f"quantity must be greater than zero, got {quantity}")
        if quantity % self.step_size != 0:
            raise TradingValidationError(
                f"quantity {quantity} is not a multiple of step_size {self.step_size}")
        if self.minimum_quantity and quantity < self.minimum_quantity:
            raise TradingValidationError(
                f"quantity {quantity} is below minimum_quantity {self.minimum_quantity}")
        if self.maximum_quantity and quantity > self.maximum_quantity:
            raise TradingValidationError(
                f"quantity {quantity} is above maximum_quantity {self.maximum_quantity}")

        if price is None:
            return
        # Before the grid, because zero sits exactly on every grid there is:
        # `0 % 0.01` is `0`, and with no minimum notional configured a price
        # of zero — or a negative one — would pass every check below.
        price = positive(price, "price")
        if price % self.tick_size != 0:
            raise TradingValidationError(
                f"price {price} is not a multiple of tick_size {self.tick_size}")
        notional = self.instrument.notional(price, quantity)
        if self.minimum_notional and notional < self.minimum_notional:
            raise TradingValidationError(
                f"notional {notional} is below minimum_notional {self.minimum_notional}")
