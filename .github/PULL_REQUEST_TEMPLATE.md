## Summary

<!-- What changed, why, and what problem does it solve? -->

## Scope

<!-- Name the affected subsystems and explicit non-goals. Keep unrelated work separate. -->

## Architecture / Shared-Core Impact

<!-- Identify the shared semantic owner and affected adapters. Explain any duplicated logic
and its parity tests, or why this change is presentation-only. See docs/architecture.md. -->

## Surface Impact

Do not delete or rename rows; keep their order and all three columns.
Replace REPLACE WITH STATUS with exactly one allowed status:

- `REQUIRED`: affected; describe the implementation and/or tests performed.
- `UNCHANGED BUT VERIFIED`: no code change needed; name the path/test inspected and its result.
- `NOT APPLICABLE`: genuinely outside this change; give a concrete technical reason.

Every row requires evidence or a technical reason. For implementation or verification,
include a file path, command, or backticked identifier plus the action/outcome.
See [the contract](../docs/surface-parity.md); placeholders and generic answers fail CI.

| Surface | Status | Evidence / Notes |
| --- | --- | --- |
| TUI | REPLACE WITH STATUS | REPLACE WITH evidence or technical reason |
| Web UI | REPLACE WITH STATUS | REPLACE WITH evidence or technical reason |
| CLI / Headless | REPLACE WITH STATUS | REPLACE WITH evidence or technical reason |
| API / Protocols | REPLACE WITH STATUS | REPLACE WITH evidence or technical reason |
| Desktop | REPLACE WITH STATUS | REPLACE WITH evidence or technical reason |
| Channels / Integrations | REPLACE WITH STATUS | REPLACE WITH evidence or technical reason |
| Docker / Packaged Runtime | REPLACE WITH STATUS | REPLACE WITH evidence or technical reason |
| Persistence / Shared State | REPLACE WITH STATUS | REPLACE WITH evidence or technical reason |
| Security / Authorization | REPLACE WITH STATUS | REPLACE WITH evidence or technical reason |
| Tests / Documentation | REPLACE WITH STATUS | REPLACE WITH evidence or technical reason |

## Testing

<!-- List exact commands, outcomes, regression coverage, and skips/limitations.
Include targeted tests, lint, full suite and isolated performance tests as relevant.
Do not report an unexecuted test as passed. -->

## Capability Map

<!-- Result of `python tools/capability-map.py --check`, or a technical reason it is inapplicable.
The inventory is code-derived; do not commit CAPABILITIES.md or introduce a parallel registry. -->

## Security / Secrets

<!-- Address authorization/approval boundaries and untrusted inputs. No credentials in code,
logs, PRs or screenshots; server-side secrets must never reach browser JavaScript. -->

## Persistence / Concurrency

<!-- Describe state ownership, format/migration, reload, ordering and cancellation changes,
with deterministic evidence, or state why shared state is unaffected. -->

## Web Verification

<!-- Web is first-class. Name server/session and actual browser checks when relevant.
For UI changes cover interaction, rendering, errors and reload/reconnect. A browser-test skip
is not proof of correctness. For NOT APPLICABLE, explain the boundary or reference its row. -->

## Documentation

<!-- Name documentation updated, including intentional surface gaps, or explain why none is needed. -->

## Risks / Rollback

<!-- Describe remaining limitations, compatibility concerns and a safe rollback path. -->

## Review / CI

<!-- State current HEAD, check results, reviewed SHA, findings and unresolved threads.
No review response yet is not a clean review; a review of an earlier SHA does not cover HEAD. -->

## Merge Authorization

Creating or updating this PR does not authorize merge.

Agents must not merge or enable auto-merge unless the user separately and explicitly authorizes this exact PR.

- [ ] The PR remains unmerged and auto-merge is disabled.
