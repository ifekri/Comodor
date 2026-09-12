# Surface Parity Contract

Comodor is a multi-surface product. Web UI and TUI are first-class interfaces;
neither owns shared product semantics. Parity means deliberate, documented and
testable behavioral coverage, not identical screens or controls. A surface may
legitimately not expose a capability, but that decision must be explicit.

This document is the normative Surface Impact contract. The
[PR template](../.github/PULL_REQUEST_TEMPLATE.md) instantiates it;
[the validator](../tools/validate-surface-impact.py) enforces its mechanical rules;
[contract tests](../tests/test_surface_impact_contract.py) keep these representations
in sync. Architectural ownership is defined in [architecture.md](architecture.md).

## Canonical surfaces

Every PR, including documentation and CI changes, evaluates exactly these rows in
this order. The last three rows are cross-cutting concerns, not additional UIs.
Do not add, remove, rename, duplicate or reorder rows.

| Surface | Meaning |
| --- | --- |
| TUI | Terminal presentation, input and interaction |
| Web UI | Browser interface and its server/session adapters |
| CLI / Headless | Commands and non-interactive execution |
| API / Protocols | HTTP API, ACP and other protocol contracts |
| Desktop | Native controls, desktop automation and platform adapters |
| Channels / Integrations | Messaging, GitHub and other external integrations |
| Docker / Packaged Runtime | Container startup, distribution, assets and runtime configuration |
| Persistence / Shared State | State ownership, storage formats, reload and concurrent access |
| Security / Authorization | Credentials, trust boundaries, approvals and permissions |
| Tests / Documentation | Automated verification and user/developer guidance |

Shared application ownership belongs in the PR's Architecture / Shared-Core Impact
section and relevant rows; it is not an eleventh surface. The inventory of concrete
capabilities is separate from this list of review concerns.

## Allowed statuses

Use exactly one of these case-sensitive values, without Markdown decoration in
the status cell:

- `REQUIRED`: the surface is affected and implementation and/or testing is needed.
  Describe what was implemented or tested, with specific evidence and outcomes.
  Merely promising future work does not make a PR ready.
- `UNCHANGED BUT VERIFIED`: no code change was needed, but the relevant path was
  actually inspected or tested. Name that path or test and the observed result;
  being absent from the diff is not verification of behavior.
- `NOT APPLICABLE`: the surface genuinely does not participate. Explain the
  technical boundary, rather than saying it was not touched.

Every row needs an Evidence / Notes cell. `REQUIRED` and `UNCHANGED BUT VERIFIED`
need a concrete file path, command, or backticked symbol/route identifier and an
explanation of the change or verification. `NOT APPLICABLE` needs a specific
technical reason. A path alone, or a one-word claim, is insufficient.

Illustrative evidence (use only after performing the described work):

- `REQUIRED`: "Added responsive wrapping in `src/comodor/web/ui.css`; checked the
  settings panel at narrow and wide viewports in an actual browser."
- `UNCHANGED BUT VERIFIED`: "Ran `pytest -n 0 -q tests/test_docker.py`; container
  entrypoint and loopback port-publication assertions passed. No container build
  was performed."
- `NOT APPLICABLE`: "This change only decodes terminal escape sequences; browser
  keyboard events do not use that decoder and no shared commands change."

Non-answers such as `N/A`, `NA`, `none`, `tbd`, `todo`, `not touched`, `should work`,
`unknown`, `tests pass` and untouched placeholders fail validation. Adding punctuation
or Markdown emphasis to a non-answer does not make it evidence.

## Table format

Use exactly one visible, top-level `## Surface Impact` section and one contiguous
three-column Markdown table inside it, before the next level-one or level-two
heading. Top-level means top-level in Markdown container structure: the section
must not be nested in a blockquote, a list item, a code fence or block, an HTML
comment, raw HTML that stops Markdown from being parsed, or a `<details>` widget
that folds it away. A visible HTML wrapper that hides nothing, such as `<div>`,
is allowed — the requirement is that a reader sees the contract, not that it is a
child of the document root once GitHub has rendered it.

The header is `| Surface | Status | Evidence / Notes |`, followed by
`| --- | --- | --- |` (alignment colons are allowed), then the ten canonical rows.
Use leading/trailing pipes on every row. Keep evidence on one line per row and
escape literal pipes as `\|`.

Raw HTML blocks, including processing instructions, declarations, CDATA and
comments, cannot supply the section or table. Their closing line is still raw
HTML; put the visible contract on a following line. The guard follows GitHub's
rendering boundaries, including uppercase-initial declarations and literal
comment openers inside raw HTML, rather than treating HTML as Markdown prose.

The template deliberately contains `REPLACE WITH STATUS` and
`REPLACE WITH evidence or technical reason`. Its structure is valid, but submitting
it without completing the cells fails validation. There is no default
`NOT APPLICABLE` classification.

## Deciding impact

Start with the capability and its shared semantic owner, then trace the adapters
that expose it. Do not infer Web correctness from a TUI test, or TUI correctness
from a Web test. For the same logical session or operation, evaluate state,
progress, results, errors, cancellation, approvals, permissions, settings and
reload/reconnect semantics. Shared rules should have one application owner;
UI-local state such as a scroll position need not be synchronized.

Browser automation in `src/comodor/browser/` is an agent capability, not the
browser-based product UI in `src/comodor/web/`. Implementing or testing one does
not automatically implement or verify the other; assess their shared consumers
and presentation adapters separately.

A terminal key-decoding or ANSI-rendering correction may require only TUI and
Tests / Documentation work. A browser layout correction may require only Web UI
and Tests / Documentation work. Still evaluate the other rows and explain why
they are outside the change. Do not force meaningless adapter edits for parity.

A shared provider setting, permission rule or state-format change requires
tracing every consumer, even if first observed in one interface. It may require
adapter tests without adapter code changes. Document intentional capability gaps
rather than implying that all surfaces support everything.

For shared state, assess read/write paths, ownership, ordering, migration,
restart, refresh and persistent container mounts. For security, assess every
entry point that can trigger the protected action. Hiding a button is not an
authorization boundary. Keep server-side credentials out of browser code and
responses. Future financial capabilities must follow the shared deterministic
risk, execution and credential boundaries in [architecture.md](architecture.md#future-trading).

## Verification

Select tests by affected layer: shared behavior, adapter behavior, server/session
integration and actual browser interaction where rendering or browser state
matters. Current Web coverage includes [test_web.py](../tests/test_web.py) and
[test_real_web_ui.py](../tests/test_real_web_ui.py); container file contracts are
covered in [test_docker.py](../tests/test_docker.py). A file-contract test is not
a container build, and a skipped browser test is not browser verification.
Report the exact commands, outcomes, skips and limitations.

Run the local contract checks with:

```sh
python tools/validate-surface-impact.py --body-file pr-body.md
python tools/validate-surface-impact.py --event-file event.json
python tools/validate-surface-impact.py < pr-body.md
pytest -n 0 -q tests/test_surface_impact_contract.py
```

The event mode reads `pull_request.body` from a JSON object. Null or absent body
is an empty, contract-invalid body. Malformed JSON, non-object event/PR values,
non-string non-null bodies and unreadable inputs are input errors. Explicit
input flags are mutually exclusive; without one, stdin is used, regardless of
`GITHUB_EVENT_PATH`. Files use UTF-8.

Exit codes: **0** valid contract, **1** invalid/incomplete contract, **2** invalid
or unreadable input (including invalid CLI arguments).

The validator checks heading, table shape, exact rows/order/statuses, minimum
explanation and known non-answers. For implementation/verification it also checks
for a concrete reference. These are deterministic syntax/heuristic checks, not
proof of semantic correctness, truthful evidence or actual test execution.
Reviewers must compare classifications and evidence against the diff and results.

## Capability inventory and CI

The **capability map** answers what capabilities exist; the **surface contract**
answers which surfaces a change affects. Preserve the code-derived inventory in
[tools/capability-map.py](../tools/capability-map.py) and its
[tests](../tests/test_capability_map.py). Extend discovery when necessary instead
of creating a manually maintained `.github/capabilities.yml`. Generated
`CAPABILITIES.md` is a local snapshot, not a committed source of truth.

```sh
python tools/capability-map.py --check
```

[Surface Contract](../.github/workflows/surface-contract.yml) runs on PR open,
body edit, synchronization, reopen and ready-for-review events. The metadata job
runs the stdlib validator without installing the project. A separate job runs
the code-derived capability check with runtime dependencies; the existing
[CI](../.github/workflows/ci.yml) continues to run the tests, including drift
checks. Both new jobs use `pull_request`, read-only repository permissions,
no secrets and no persisted checkout credentials. PR text is read as data from
the event file, never interpolated into shell code.

This is an omission/drift guard, not a tamper-proof security boundary: a PR can
also propose changes to the validator or workflow. Review those changes. Branch
protection/rulesets must require the desired checks to make them merge gates;
adding this workflow does not configure repository protection. Changes to PR
metadata may require rerunning checks if edited during a run.

## Review and merge

Review the table alongside code, exact test results and architectural ownership.
Track CI and automated review against the current HEAD, not just an earlier
commit. No response from an automated reviewer is not a clean review. Resolve
valid findings and account for remaining limitations before requesting merge.

Creating or updating this PR does not authorize merge.

Agents must not merge or enable auto-merge unless the user separately and explicitly authorizes this exact PR.

## The terminal interface migration, complete

The terminal was rewritten across F1–F8: a Python core behind a versioned
protocol, renderer-independent client semantics in TypeScript, and an OpenTUI
presentation — with the previous Rich interface kept running beside it until
the new one had reached parity, made the default (F7), and then removed (F8).
There is one terminal interface now. This section records what the migration
decided, because the decisions still shape what the TUI row means.

What the interface has, all renderer-verified: normal conversation, modes,
questions, permissions, the tool timeline, tasks, background agents,
scrolling with a truthful new-output marker, model display and switching,
session history and reopening (against the shared store, so a chat begun in
the terminal opens in the browser and the reverse), usage and context
reporting where the provider measures it, terminal floor behaviour, and a
core that stops answering. The mouse table in [tui-v2](tui-v2.md) says which
mouse paths are renderer-verified.

Deliberately not carried over from the previous interface, and why:

- **Learning and memory views** (what were `/memory`, `/rules`, `/progress`,
  `/teach`, `/good`, `/bad`, `/skills`, `/mcp`, `/prompt`, `/plugins`) —
  presentation of Core-side subsystems the protocol does not expose. The
  commands that remain are `comodor journey`, `comodor insights`, `comodor
  curator`, `comodor skills` and `comodor mcp`.
- **Progressive enrichment** (what were `/undo`, `/settings`, `/save`,
  `/approve`, `/theme`, `/copy`, `/mouse`, `/computer`, `/export`, `/attach`,
  `/clear`, `/loop`, `/gateway`) — configuration and utility commands the
  session is usable without. Screen use is granted when the tool asks, with a
  length, rather than by a command; approvals are proposed by `comodor
  approvals`; `--theme` and `--ascii` set how the commands print.
- **Costs across every session** (what were `/cost` and `/insights`) — the
  live usage corner shows this session; `comodor insights` shows the rest.
- **Config complaints at startup** — the previous interface toasted them;
  `comodor run` and `comodor doctor` print them; the interface does not yet.

Known, explicitly non-blocking: no transcript-side scroll search (the store
lists every session by title; scrollback has a truthful new-output marker and
no find-in-page).
