# Trading architecture

Comodor's trading capability is being built as one system with four execution
environments, not four systems that resemble each other. This document is the
contract that makes that possible. It describes boundaries and invariants, not a
schedule, and it is normative: a change that breaks a rule here is a change to
the architecture, and should be argued for rather than slipped in.

Nothing described here places an order. The current implementation is the domain
core in [`src/comodor/trading/`](../src/comodor/trading/) — types, invariants
and protocols. There is no exchange adapter, no network call, no credential, and
no live execution.

## Modes

```text
BACKTEST        historical data, replayed as fast as it can be read
MARKET_REPLAY   historical data, replayed at its original pace
PAPER           live data, simulated fills, no money
LIVE            real orders — not implemented, disabled by default
```

The same strategy, the same risk rules and the same portfolio accounting run in
all four. A mode changes where the events come from and where the fills go; it
does not change what a position means. That is the whole reason for a shared
core: if backtest and live were separate implementations, the backtest would be
measuring a program that is not the one trading.

`DEFAULT_TRADING_MODE` is `BACKTEST`. Paper needs a live feed, and a default
that quietly opens a connection is not a default.

## The shared core

```text
Presentation / Transport        TUI, Web, CLI — none of this exists yet
        |
        v
Adapter / Controller            exchange adapters, data readers
        |
        v
Application Service             engines: backtest, replay, paper
        |
        v
Domain                          src/comodor/trading/ — this layer
```

The domain depends on nothing above it. `comodor.trading` imports only the
standard library and itself; it does not import `comodor.ui`, `comodor.web` or
`comodor.channels`, and it never will. Presentation may read the domain. The
reverse is a circular dependency and an invitation to put a formatting decision
where an accounting rule belongs.

Exchange names are data, never types. `Instrument(venue="kucoin", …)` is a
value; `KuCoinInstrument` would be a decision the core is not allowed to make.
`UTA`, `Classic` and every other venue-specific concept belongs to the adapter
that speaks to that venue.

## Two invariants

**Money is `Decimal`.** Not float, anywhere, for price, quantity, fee, balance,
PnL, notional, leverage, margin or funding. `0.1 + 0.2` is not `0.3` in binary
floating point, and a fee schedule applied ten thousand times across a backtest
turns that into a balance that does not reconcile against the exchange's.

Floats are **refused**, not converted. `Decimal(0.1)` is
`0.1000000000000000055511151231257827021181583404541015625` — passing a float
through the constructor imports the error rather than avoiding it. Values enter
the domain as `Decimal`, `int` or `str`.

**Time is timezone-aware UTC.** A naive datetime is a timestamp whose meaning
depends on the machine reading it, and an hour of ambiguity twice a year is not
a rounding error. Naive values are refused; aware values in other zones are
converted, because the caller has said which instant they mean.

Nothing in the domain reads the system clock. A backtest's notion of *now* is
the timestamp of the event it is processing, so the clock is injected through
the `Clock` protocol. A domain that reaches for `datetime.now()` cannot be
replayed, and a backtest that cannot be replayed is not evidence of anything.

## Determinism

The same input sequence must produce the same output, every run, on every
machine. The domain therefore does not use randomness, the system clock, the
network, the filesystem, environment variables or global mutable state. Value
objects are frozen; identifiers are supplied by the caller rather than generated
in a constructor, so that two runs of one backtest produce equal objects.

## Spot is not futures

Holding one Bitcoin is **ownership**: an asset, no counterparty, worth at worst
nothing. Being long one Bitcoin contract is **exposure**: a claim marked against
margin, with a counterparty, which at worst takes the margin with it.

A single `Position(quantity=1)` cannot say which. Systems that try grow an
`is_spot` flag, then two branches wherever it is read, then a bug where a spot
balance is liquidated. So there are two types — `SpotHolding`, keyed by asset,
and `FuturesPosition`, keyed by instrument — and constructing the wrong one
raises rather than compiling.

## Identity and specification

An instrument's **identity** — venue, symbol, base and quote asset, market type
— never changes, and is frozen and hashable so a portfolio can key on it. Its
**specification** — tick size, step size, minimum quantity and notional — is
what the venue currently allows, and does change. Keeping them apart means an
order, a fill and a position can share one identity without any of them
carrying trading rules that may be stale.

Normalising a price or a quantity onto its grid requires the caller to say which
way to round. There is no default and there will not be one: rounding a quantity
up can spend money the account does not have, and which direction is correct
depends on what the caller is doing. Silent rounding is how a position stops
matching the exchange's.

## Strategy, risk, execution

```text
Market data
    |
    v
Strategy            events in, OrderIntents out
    |
    v
OrderIntent         a request; not an order
    |
    v
Risk                deterministic, auditable
    |
    v
ApprovedOrder  |  RejectedOrder
    |
    v
Execution           the only thing that talks to a venue
```

**A strategy never calls an execution gateway.** That is enforced by the types
rather than by convention: `ExecutionGateway.submit` accepts an `ApprovedOrder`,
which records which policy approved it and when, and a strategy is handed
nothing capable of producing one. The shortest path from a signal to an exchange
runs through risk whether or not the author remembers to route it there.

Risk decisions are deterministic by contract. A policy that consults a model, an
un-injected clock or a random number cannot be replayed, and a risk rule that
cannot be replayed cannot be audited after a loss.

**No AI in the execution path.** No language model participates in a trading
decision. A model may later propose or explain; it may not authorise, size,
approve or route an order, and it may not weaken a risk limit.

## Live is disabled

`require_simulated` is the only door, and there is nothing behind it: this build
has no live execution gateway. No default anywhere is `LIVE`, and asking for it
raises `LiveTradingDisabledError`.

The gate is deliberately small. An arming protocol with states and timeouts
would be machinery guarding a door that opens onto nothing. What exists now
makes the refusal explicit and tested, so that the phase which adds live
execution has to change it on purpose rather than discover that nothing was
stopping it. Enabling live trading will require separate, explicit
authorisation, validated configuration and real risk limits — a green backtest
is not authorisation to trade.

## Synchronous, because Comodor is

There is not one `async def` in this repository. The agent runs on threads and
the interface is drawn from a frame loop. The trading protocols are therefore
synchronous: a `MarketDataSource` returns an iterator, which covers a file read
end to end, a database replayed at its original pace, and a socket drained as
frames arrive — a live source simply blocks between yields.

This was decided by reading the codebase, not by copying what a trading library
usually looks like. Imposing an event loop nothing else uses would mean
`asyncio.run` at every call site for no gain.

## Dependencies

The domain uses the standard library only: `dataclasses`, `datetime`, `decimal`,
`enum` and `typing`. No `pydantic`, `attrs`, `numpy`, `pandas`, `ccxt` or
exchange SDK. Dataclasses with `Decimal` and `Protocol` are sufficient for
domain models, and every dependency added at this layer is one every later phase
inherits.

## Planned implementation sequence

A roadmap, not a commitment, and nothing below is implemented.

```text
T1   Trading Core Foundation                    ← this
T2   Historical Market Data + Deterministic Backtest
T3   Strategy Runtime / AST
T4   Risk Engine
T5   Paper Execution + Portfolio Accounting
T6   KuCoin Market Data Adapter
T7   KuCoin Execution Adapter
T8   Reconciliation / Recovery / Idempotency
T9   Multi-surface Trading Presentation
T10  Live Arming Gate
```

The next phase is historical data and a deterministic backtest — not live
trading, and not a user interface. Presentation comes after there is something
true to present, and live comes last because it is the only step that cannot be
undone.

## See also

- [architecture.md](architecture.md) — the repository's layering, and the
  future-trading guidance this document implements.
- [surface-parity.md](surface-parity.md) — how a change to a shared capability
  is assessed across surfaces.
