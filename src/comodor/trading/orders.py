"""What a strategy asks for, what risk allows, and what came back.

The three models here are the spine of the execution path, and the names are
chosen to keep it honest:

* `OrderIntent` is a **request**. A strategy produces it. It is not an order.
* `ApprovedOrder` is an intent that risk has passed, and it is the only thing
  an `ExecutionGateway` accepts. A strategy cannot make one accidentally,
  because making one means writing down which policy approved it and when.
* `Fill` is what actually happened, reported back.

That is the boundary from `docs/trading.md` expressed as types rather than as a
comment: `submit(order: ApprovedOrder)` cannot be handed an `OrderIntent`, so
the shortest path from a strategy to an exchange runs through risk whether the
author remembers to route it there or not.

Identity is split for the same reason. `client_order_id` is ours, assigned
before the order leaves; `venue_order_id` is the exchange's, and does not exist
until it answers. Reconciliation after a disconnect needs both, and a single
`order_id` field that means one before submission and the other afterwards is
how a duplicate order gets sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .enums import (
    PRICED_TYPES,
    TRIGGERED_TYPES,
    OrderStatus,
    OrderType,
    Side,
    TimeInForce,
)
from .errors import TradingValidationError
from .instruments import Instrument
from .validation import (
    DecimalLike,
    identifier,
    non_negative,
    positive,
    utc_of,
)


@dataclass(frozen=True, slots=True)
class Fee:
    """What the venue charged, as an amount of an actual asset.

    An amount and an asset, never a rate. A fee stored as `0.001` is a number
    whose meaning depends on remembering which side of the trade it applied to
    and what it was charged in — and fees are frequently charged in a third
    asset entirely, which a rate cannot express at all. The schedule that
    produced it belongs to the venue adapter; what reaches the portfolio is
    what was actually taken.
    """

    amount: Decimal
    asset: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", non_negative(self.amount, "fee amount"))
        object.__setattr__(self, "asset", identifier(self.asset, "fee asset"))

    def __str__(self) -> str:
        return f"{self.amount} {self.asset}"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """A request to trade, before anybody has agreed to it.

    Every invariant a well-formed order must satisfy is checked here, so that
    an intent which exists is an intent that describes something real. What is
    *not* checked here is anything requiring knowledge this object does not
    have — whether the size clears the venue's minimum notional needs the
    specification, and whether it clears the account's exposure limit needs
    risk.
    """

    instrument: Instrument
    side: Side
    order_type: OrderType
    quantity: Decimal
    #: Ours, assigned before submission, and never generated in here. A random
    #: id minted in a constructor makes two runs of the same backtest produce
    #: different objects, which is the one thing a deterministic core must not
    #: do. The caller decides, and can therefore make it reproducible.
    client_order_id: str
    created_at: datetime
    limit_price: Decimal | None = None
    trigger_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    #: An instruction, not a duration, which is why it is not a `TimeInForce`.
    #: A good-till-cancelled post-only order is ordinary, and one field cannot
    #: hold both facts.
    post_only: bool = False
    #: Free-form, for the caller's own bookkeeping — a strategy name, a signal
    #: id. Never interpreted here.
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TradingValidationError(
                f"instrument must be an Instrument, got {type(self.instrument).__name__}")
        for name, value, kind in (("side", self.side, Side),
                                  ("order_type", self.order_type, OrderType),
                                  ("time_in_force", self.time_in_force, TimeInForce)):
            if not isinstance(value, kind):
                raise TradingValidationError(
                    f"{name} must be a {kind.__name__}, got {type(value).__name__}")

        object.__setattr__(self, "quantity", positive(self.quantity, "quantity"))
        object.__setattr__(self, "client_order_id",
                           identifier(self.client_order_id, "client_order_id"))
        object.__setattr__(self, "created_at", utc_of(self.created_at, "created_at"))
        object.__setattr__(self, "tags", tuple(self.tags))

        self._check_limit_price()
        self._check_trigger_price()

        if self.post_only and self.time_in_force is not TimeInForce.GTC:
            # An order that must not take liquidity, and must fill immediately
            # or die, is a contradiction: the only way it fills immediately is
            # by taking. Venues reject it; saying so here is cheaper.
            raise TradingValidationError(
                f"post_only cannot be combined with {self.time_in_force.value}: "
                "an order that must not take liquidity cannot also demand an "
                "immediate fill")

    def _check_limit_price(self) -> None:
        needs_price = self.order_type in PRICED_TYPES
        if needs_price:
            if self.limit_price is None:
                raise TradingValidationError(
                    f"limit_price is required for {self.order_type.value} orders")
            object.__setattr__(self, "limit_price",
                               positive(self.limit_price, "limit_price"))
        elif self.limit_price is not None:
            raise TradingValidationError(
                f"limit_price must not be set on {self.order_type.value} orders: "
                "a market order takes the price the book gives it")

    def _check_trigger_price(self) -> None:
        needs_trigger = self.order_type in TRIGGERED_TYPES
        if needs_trigger:
            if self.trigger_price is None:
                raise TradingValidationError(
                    f"trigger_price is required for {self.order_type.value} orders")
            object.__setattr__(self, "trigger_price",
                               positive(self.trigger_price, "trigger_price"))
        elif self.trigger_price is not None:
            raise TradingValidationError(
                f"trigger_price must not be set on {self.order_type.value} orders")

    @property
    def is_buy(self) -> bool:
        return self.side is Side.BUY

    def notional(self, price: DecimalLike | None = None) -> Decimal:
        """Quantity times price times the contract multiplier.

        A market order has no price of its own, so one must be supplied — the
        expected fill price, which only the engine knows. Asking for the
        notional of a market order without one is a question with no answer,
        and it raises rather than guessing at the last trade.
        """
        if price is None:
            if self.limit_price is None:
                raise TradingValidationError(
                    f"{self.order_type.value} orders have no price of their own; "
                    "pass the expected fill price to compute a notional")
            reference = self.limit_price
        else:
            reference = positive(price, "price")
        return self.quantity * reference * self.instrument.contract_multiplier


@dataclass(frozen=True, slots=True)
class ApprovedOrder:
    """An intent that risk has passed, and the only thing execution accepts.

    It exists so that the boundary is a type rather than a convention. A
    strategy holding an `OrderIntent` cannot call `ExecutionGateway.submit`
    with it; producing one of these means recording which policy approved it,
    which is also the audit trail that reconciliation and post-mortems need.

    The risk engine that will produce these is a later phase. This is the
    contract it has to satisfy.
    """

    intent: OrderIntent
    #: What approved it. A name, not an object: this is written to an audit
    #: log, and a log entry that needs the original object to be understood is
    #: not a log entry.
    approved_by: str
    approved_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.intent, OrderIntent):
            raise TradingValidationError(
                f"intent must be an OrderIntent, got {type(self.intent).__name__}")
        object.__setattr__(self, "approved_by", identifier(self.approved_by, "approved_by"))
        object.__setattr__(self, "approved_at", utc_of(self.approved_at, "approved_at"))

    @property
    def client_order_id(self) -> str:
        return self.intent.client_order_id


@dataclass(frozen=True, slots=True)
class RejectedOrder:
    """An intent risk refused, and why.

    A rejection is a result, not an exception. It is produced in bulk during a
    backtest — a strategy that proposes more than the limits allow is normal —
    and the reasons are what a later report is built from.
    """

    intent: OrderIntent
    reason: str
    rejected_by: str
    rejected_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.intent, OrderIntent):
            raise TradingValidationError(
                f"intent must be an OrderIntent, got {type(self.intent).__name__}")
        object.__setattr__(self, "reason", identifier(self.reason, "reason", limit=512))
        object.__setattr__(self, "rejected_by", identifier(self.rejected_by, "rejected_by"))
        object.__setattr__(self, "rejected_at", utc_of(self.rejected_at, "rejected_at"))

    @property
    def client_order_id(self) -> str:
        return self.intent.client_order_id


@dataclass(frozen=True, slots=True)
class Fill:
    """One execution against an order, as the venue reported it.

    Immutable, because it is history. A partially filled order produces several
    of these and the order's remaining quantity is derived from them, rather
    than a single mutable record being edited — which is what makes a replay of
    the same fills reproduce the same position.
    """

    fill_id: str
    client_order_id: str
    instrument: Instrument
    side: Side
    price: Decimal
    quantity: Decimal
    fee: Fee
    filled_at: datetime
    #: Blank until the venue has told us its own id for the order.
    venue_order_id: str = ""
    #: True when this fill removed liquidity. Venues price the two differently,
    #: and a backtest that assumes one is modelling a different fee schedule.
    is_taker: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise TradingValidationError(
                f"instrument must be an Instrument, got {type(self.instrument).__name__}")
        if not isinstance(self.side, Side):
            raise TradingValidationError(
                f"side must be a Side, got {type(self.side).__name__}")
        if not isinstance(self.fee, Fee):
            raise TradingValidationError(
                f"fee must be a Fee, got {type(self.fee).__name__}")

        object.__setattr__(self, "fill_id", identifier(self.fill_id, "fill_id"))
        object.__setattr__(self, "client_order_id",
                           identifier(self.client_order_id, "client_order_id"))
        object.__setattr__(self, "price", positive(self.price, "price"))
        object.__setattr__(self, "quantity", positive(self.quantity, "quantity"))
        object.__setattr__(self, "filled_at", utc_of(self.filled_at, "filled_at"))
        if self.venue_order_id:
            object.__setattr__(self, "venue_order_id",
                               identifier(self.venue_order_id, "venue_order_id"))

    @property
    def notional(self) -> Decimal:
        return self.price * self.quantity * self.instrument.contract_multiplier


@dataclass(frozen=True, slots=True)
class OrderState:
    """Where an order stands, as a value rather than an object with methods.

    A snapshot: the status, how much has filled, and what the venue calls it.
    The transitions between statuses are the execution engine's business and
    are not modelled here — this stage fixes the vocabulary so that four
    engines cannot each invent their own.
    """

    client_order_id: str
    status: OrderStatus
    filled_quantity: Decimal = Decimal(0)
    venue_order_id: str = ""
    fills: tuple[Fill, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.status, OrderStatus):
            raise TradingValidationError(
                f"status must be an OrderStatus, got {type(self.status).__name__}")
        object.__setattr__(self, "client_order_id",
                           identifier(self.client_order_id, "client_order_id"))
        object.__setattr__(self, "filled_quantity",
                           non_negative(self.filled_quantity, "filled_quantity"))
        object.__setattr__(self, "fills", tuple(self.fills))
        if self.venue_order_id:
            object.__setattr__(self, "venue_order_id",
                               identifier(self.venue_order_id, "venue_order_id"))
