# Comodor Architecture

Comodor is a multi-surface software engineering agent, not a terminal application
with a secondary web page. **TUI and Web UI are first-class product surfaces**.
CLI/headless execution, APIs/protocols, desktop capabilities and external channels
are adapters around shared behavior, not independent implementations of that behavior.

This document describes engineering boundaries and intended ownership. It is not
an assertion that every existing module already satisfies them, or that every
surface exposes every capability. Inspect current executable code and tests when
changing behavior; document intentional gaps and existing limitations. The
[Surface Parity Contract](surface-parity.md) requires impact assessment for every
PR without requiring meaningless edits to every interface.

## Layers and dependency direction

The arrows below mean **depends on / invokes**, not event-delivery direction:

```text
Presentation / Transport
        |
        v
Adapter / Controller
        |
        v
Application Service
        |
        v
Domain / Infrastructure
```

- **Presentation / transport** renders state, collects input, or encodes messages.
  Terminal geometry, browser DOM and desktop widgets belong here.
- **Adapters / controllers** translate input into shared operations and translate
  results/events into surface-specific output. Transport authentication and
  serialization belong at the boundary; shared authorization policy does not.
- **Application services** own use cases, state transitions, lifecycle coordination,
  permission/approval decisions and shared configuration semantics.
- **Domain / infrastructure** supplies state models, persistence, provider/tool
  interfaces and integrations. Application policy coordinates these dependencies;
  adapters must not bypass it to perform privileged actions directly.

These are conceptual boundaries, not a demand to rename directories or introduce
a framework. Shared services should be usable without a terminal renderer, a
browser DOM, terminal dimensions or a desktop widget. Event consumers may receive updates
in the reverse direction without making the shared layer depend on a concrete UI.

## Current source map

Use this map to find implementation, not as proof of runtime parity:

| Area | Starting points |
| --- | --- |
| Shared agent behavior | [agent/](../src/comodor/agent/), [events.py](../src/comodor/events.py) |
| Configuration | [config.py](../src/comodor/config.py) |
| Tool and provider boundaries | [tools/](../src/comodor/tools/), [providers/](../src/comodor/providers/) |
| Terminal interface | [tui/](../src/comodor/tui/) (the packaged renderer and its launcher), [apps/tui/](../apps/tui/) and [packages/](../packages/) (the OpenTUI client and its shared semantics); what the commands print through is [terminal/](../src/comodor/terminal/) |
| Web interface and server/session adapters | [web/](../src/comodor/web/) |
| CLI and headless entry points | [cli.py](../src/comodor/cli.py) |
| API and protocols | [api/](../src/comodor/api/), [acp/](../src/comodor/acp/) |
| Desktop capabilities | [desktop/](../src/comodor/desktop/) |
| Channels and integrations | [channels/](../src/comodor/channels/), [discord/](../src/comodor/discord/), [github/](../src/comodor/github/) |
| Scheduled work | [cron/](../src/comodor/cron/) |
| Agent browser automation | [browser/](../src/comodor/browser/) |

**Browser automation is not the Web UI.** `src/comodor/browser/` provides agent
browser capabilities; `src/comodor/web/` is the browser-based product interface.
Changes to one do not automatically implement or verify the other. Likewise,
Desktop includes desktop-specific capabilities/adapters; it does not imply a
separate fully featured native client for every agent operation.

## Shared semantics and surface-local state

State transitions, authorization, approval rules, persistence semantics, task
lifecycle, cancellation, provider/model selection, tool policies, safety rules
and integration permissions must have shared semantic owners. Do not implement
one approval rule in TUI and a subtly different rule in browser JavaScript.
An adapter can collect a decision; the shared application operation must enforce it.

Keep presentation-local state local: scroll position, terminal completion cursor,
a selected browser panel, or an unsubmitted form draft need not be synchronized.
But once an operation is accepted, its status, result, error and permission state
must not acquire incompatible meanings across interfaces.

Prefer a shared operation with surface-specific adapters over copied business
logic. If duplication is unavoidable, record the architectural reason, owner,
known differences and parity tests. Similar-looking screens alone are not evidence
of shared semantics. Avoid a broad refactor unless the actual change requires it.

## State, lifecycle and persistence

For changes involving shared state, identify its owner, writer, readers and
persistence boundary before editing an adapter. Assess:

- Whether two entry points invoke the same operation and observe the same state.
- Ordering of updates, concurrent writes and failure/retry behavior.
- Cancellation and terminal-state semantics across callers.
- Schema/version compatibility and reload after process restart.
- Browser refresh/reconnect and reconstruction from authoritative state.
- Container mounts and packaged runtime paths, not only a developer's checkout.

Use deterministic tests for ordering, reload and concurrent access when affected.
A browser connection or terminal renderer should not become the only owner of
shared durable state. These are review criteria, not an instruction to redesign
unrelated lifecycle or persistence code in a governance-only change.

## Security and authorization

Treat shell input, files, remote content, protocol messages and integration events
as boundary inputs, not trusted instructions. Validate and authorize privileged
operations on the server/shared application path regardless of which surface
initiated them. Hiding UI controls cannot replace permission checks.

Keep provider keys, GitHub installation tokens, privileged access tokens, exchange
credentials and signing material server-side. Never move server-side secrets into
browser JavaScript, serialized UI state, client storage or browser-visible logs.
Return only the data needed for the interaction; redact sensitive diagnostics.
Do not place credentials in source, tests, documentation, PRs, screenshots or CI
logs. Test security boundaries with deterministic fakes, not live credentials.

For workflow changes, use minimal permissions and treat PR bodies as untrusted
data. Do not interpolate them into executable shell fragments or expose secrets
to untrusted PR code. Review the workflow itself as well as its validator.

## Adding or changing a capability

1. Define the behavior, shared semantic owner and affected state/permission boundaries.
2. Trace existing entry points before selecting an implementation layer.
3. Implement shared logic once and adapt presentation/transport where necessary.
4. Evaluate every canonical row in [surface-parity.md](surface-parity.md), including
   packaging, shared state, security, tests and documentation.
5. Verify shared behavior and affected adapters independently; use an actual
   browser for changes to rendering, interaction or browser state.
6. Document intentional surface gaps, evidence, skips and remaining limitations.

Code-derived discovery answers **what exists**; the Surface Impact table answers
**what this change affects**. Preserve [tools/capability-map.py](../tools/capability-map.py)
and [its tests](../tests/test_capability_map.py) rather than adding a manually
maintained parallel capability registry. Run:

```sh
python tools/capability-map.py --check
```

`CAPABILITIES.md` is a generated local snapshot, not a committed source of truth.

## Future Trading

This section is **future architectural guidance**, not an implemented trading
feature or authorization to add one. Any future trading functionality must be a
shared subsystem, not a TUI trading bot followed by an independent Web rewrite.

Potential service boundaries include market data, indicators, strategies,
backtesting, market replay, paper trading, portfolio/accounting, deterministic
risk evaluation, execution, exchange adapters and auditing. Choose concrete
classes only when implementation requires them; names here are not claims that
such services already exist.

### Intent is not execution authority

```text
LLM / Strategy Agent
        |
        v
Trading Intent
        |
        v
Deterministic Risk Engine
        |
        v
Execution Policy
        |
        v
Execution Gateway
        |
        v
Exchange Adapter
```

A model or strategy may propose an intent. It may not authorize its own execution,
weaken risk limits or bypass approval. The deterministic risk engine and execution
policy are the authority. TUI, Web, API and automation must invoke these same gates;
none may route directly to live exchange execution as a shortcut.

Risk policy should evaluate applicable position/exposure, leverage, order-size,
loss/drawdown, liquidity, data-freshness and rate constraints, plus market/account
availability and emergency-stop state. Rejection reasons and execution outcomes
must be inspectable. Validate order identity and duplicate/retry handling at the
execution boundary rather than relying on a model to remember prior requests.

### Modes and live activation

```text
Research -> Backtest -> Market Replay -> Paper Trading -> Shadow / Dry Run -> Live Trading
```

Keep simulated and live state, credentials and results distinguishable. Backtests
and replay must state their assumptions, fees, slippage and data limitations;
profitable historical results are not authorization for live execution.

**Live trading is DISABLED BY DEFAULT.** Enabling it requires separate explicit
user authorization, validated configuration, risk limits, credential permissions
and appropriate safeguards. A model response, UI selection, successful simulation
or automated test must not silently enable live trading. Shared kill-switch and
cancellation semantics must apply across every initiating surface.

### Presentation, credentials and audit

Web and TUI should display shared order, portfolio, risk and execution state with
clear mode labels, timestamps, rejection reasons and data-freshness indicators.
PnL, accounting, portfolio/order state and risk rules must not be independently
redefined in browser JavaScript. Presentation may format authoritative values;
it does not become their accounting engine.

Exchange credentials remain server-side with minimum permissions; use isolated
simulation credentials where appropriate. Audit intent, risk decisions, approvals,
execution attempts and outcomes without storing secrets in audit output.

Ordinary deterministic CI must never execute live exchange actions. Use fake
adapters, deterministic market fixtures, replay and paper simulations to test
risk rejection, authorization, stale data, duplicate execution, reconciliation,
cancellation and adapter parity. Any separately authorized live integration test
belongs outside ordinary CI with an explicitly controlled environment.
