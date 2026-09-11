"""The seams. Five protocols, and nothing behind any of them yet.

Each one is the narrowest contract the next phase actually needs. An
`ExecutionGateway` with thirty speculative methods would be a guess about an
exchange nobody has integrated, and every guess becomes a method some adapter
has to implement by raising `NotImplementedError`.

**They are synchronous**, because Comodor is. There is not one `async def` in
the codebase: the agent runs on threads and the interface is drawn from a frame
loop. Making the trading core async would mean either an event loop nothing
else uses, or `asyncio.run` at every call site — and a websocket feed pushes
into a queue perfectly well from a thread. The choice was made by reading the
repository, not by defaulting to what a trading library usually looks like.

`Clock` deserves its own note. Nothing in this package calls `datetime.now()`.
A backtest's notion of now is the timestamp of the bar it is processing, and a
domain that reaches for the system clock cannot be replayed — the same input
would produce different output, which is the definition of a broken backtest.
So the clock is a dependency, and the one used in tests can be frozen.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterator, Protocol, runtime_checkable

from .enums import SIMULATED_MODES, TradingMode
from .errors import LiveTradingDisabledError
from .instruments import Instrument
from .market import MarketData
from .orders import ApprovedOrder, OrderIntent, OrderState, RejectedOrder
from .portfolio import PortfolioSnapshot


@runtime_checkable
class Clock(Protocol):
    """Where the domain gets the time from.

    Backtest and replay implement this over the data being replayed; paper and
    live implement it over the wall clock. Nothing else in this package is
    allowed to know which it got.
    """

    def now(self) -> datetime:
        """The current instant, timezone-aware and in UTC."""
        ...


@runtime_checkable
class MarketDataSource(Protocol):
    """Where events come from.

    One method, returning an iterator. That covers a CSV read end to end, a
    database replayed at its original pace, and a socket drained as frames
    arrive — a live source simply blocks between yields. A strategy consuming
    this cannot tell them apart, which is the entire purpose.
    """

    def stream(self, instruments: tuple[Instrument, ...]) -> Iterator[MarketData]:
        """Yield events for `instruments`, in time order."""
        ...


@runtime_checkable
class ExecutionGateway(Protocol):
    """Where orders go.

    Two methods. `replace` is absent because no venue adapter exists to need
    it, and a cancel followed by a submit is what most venues do internally
    anyway — adding it now would be designing an amend protocol against no
    requirement.

    It accepts `ApprovedOrder` and not `OrderIntent`. That is the risk boundary
    written as a signature: a strategy holding an intent cannot reach an
    exchange without something having approved it first.

    A signature is not a security boundary, and an implementation must not
    treat it as one. `ApprovedOrder` is constructible by anything that can
    import it, so a gateway **must revalidate against the risk policy** before
    sending. The type says where an order came from; it does not prove it.
    """

    def submit(self, order: ApprovedOrder) -> OrderState:
        """Send an approved order, and report where it stands."""
        ...

    def cancel(self, client_order_id: str) -> OrderState:
        """Ask for an order to be cancelled, and report where it stands."""
        ...


@runtime_checkable
class RiskPolicy(Protocol):
    """What decides whether an intent may become an order.

    Deterministic by contract: the same intent against the same portfolio must
    reach the same verdict every time. A policy that consults a model, a clock
    it was not given, or a random number cannot be replayed, and a risk rule
    that cannot be replayed cannot be audited after a loss.
    """

    def evaluate(self, intent: OrderIntent,
                 portfolio: PortfolioSnapshot) -> ApprovedOrder | RejectedOrder:
        """Approve or refuse `intent`, and say who decided."""
        ...


@runtime_checkable
class Strategy(Protocol):
    """What turns market events into requests.

    Events in, intents out, and nothing else — no gateway, no portfolio writes,
    no network. A strategy that could submit an order directly would be a
    strategy that can bypass risk, so it is not given anything to submit with.

    The portfolio is passed in rather than held, so that the same strategy
    object can be run against a backtest and a paper session without carrying
    state between them.
    """

    def on_event(self, event: MarketData,
                 portfolio: PortfolioSnapshot) -> tuple[OrderIntent, ...]:
        """Zero or more requests, in response to one event."""
        ...


def require_simulated(mode: TradingMode) -> TradingMode:
    """Let a run proceed only in a mode that exists, and say so if not.

    The whole of the live gate, and deliberately the whole of it. An arming
    protocol with states and timeouts would be machinery guarding a door that
    opens onto nothing: there is no live execution gateway in this package, and
    there will not be one until the phase that builds it. What this does is
    make the refusal explicit and testable now, so that the phase which adds
    live execution has to change this function on purpose rather than discover
    that nothing was ever stopping it.
    """
    if not isinstance(mode, TradingMode):
        raise LiveTradingDisabledError(
            f"trading mode must be a TradingMode, got {type(mode).__name__}")
    if mode in SIMULATED_MODES:
        return mode
    raise LiveTradingDisabledError(
        f"{mode.value} trading is disabled: this build has no live execution "
        f"gateway. Available modes: "
        f"{', '.join(sorted(item.value for item in SIMULATED_MODES))}.")
