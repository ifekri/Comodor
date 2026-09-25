# Specification Quality Checklist: Grounded High-Quality Agent with Token-Efficient Context and Progressive Learning

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-14
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs) — *with one documented exception, see Notes*
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain — **21/21 recorded clarification decisions resolved through 2026-09-25** (see Notes)
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification — *scoped to Appendix A, see Notes*

## Constitution Alignment

Checked against `.specify/memory/constitution.md` v1.1.0.

- [x] I — Backward compatibility: FR-079 to FR-082; the single intended behaviour
      change is named explicitly rather than shipped silently
- [x] II — Three platforms: FR-078, SC-022
- [x] IV — Deterministic regression tests: SC-025 requires a mutation check per
      guard and forbids sleep-based correctness
- [x] VI — Architectural boundaries: FR-080 makes any protocol surface additive
      and negotiated
- [x] VIII — Security not weakened: Assumptions section preserves mode
      capabilities, fail-closed unknown modes, and the no-frontend-authorization
      rule; FR-074 forbids credentials in measurements
- [x] XIII to XV — Quality-first, evidence before assumption, clarification as a
      product invariant: User Stories 1 and 2, FR-001 to FR-035
- [x] XVI / XXI — Token efficiency measured jointly with quality: FR-044,
      FR-076, FR-077, SC-011, SC-012
- [x] XVII — Progressive learning with provenance and staleness: FR-056 to FR-067
- [x] XVIII — Extend, do not duplicate: Appendix A names the existing owner of
      every behaviour; no parallel subsystem is proposed
- [x] XIX — Grounded tool use: FR-004, FR-005, FR-068 to FR-070
- [x] XX — User control over consequential actions: FR-083 to FR-085
- [x] XI — Surfaces named: Compatibility requirements cover TUI, Web, CLI and
      headless, protocol, persistence, security, packaging and the three
      platforms

## Coverage Audit (second pass, 2026-09-14)

The feature request was re-issued and the specification was audited item by item
against every list it enumerates. The audit found real gaps, which have been
closed; the spec grew from 85 requirements and 26 criteria to **120 requirements
and 35 criteria**. All identifiers are unique, the sequence FR-001 to FR-120 is
complete with no gaps, and no criterion identifier repeats.

Gaps found and closed:

| Enumerated in request | Was | Now |
| --- | --- | --- |
| Build and test logs as a context class | absent | FR-090, SC-027 — failing runs must keep the failure itself, not a pass/fail flag |
| Project instructions as a context class | absent | FR-091 |
| Diffs as the carried representation of change | implied only | FR-088 |
| Deduplication | absent | FR-099, SC-028 |
| Delta context | absent | FR-100 |
| Unchanged-content references | absent | FR-101 |
| Canonical summaries | absent | FR-086, FR-102, SC-030 |
| Evidence references | absent | FR-103 |
| Incremental repository understanding | absent | FR-104 |
| Avoiding re-verification of stable facts | absent | FR-105, SC-029 |
| Context budgeting / relevance / selective retrieval | partial | FR-096 to FR-098 |
| Project-specific terminology | absent | FR-106 |
| Stable architectural decisions | absent | FR-107 |
| Recurring instructions | absent | FR-108, SC-031 |
| Accepted decisions and validated fixes | partial | FR-109 |
| Retrieval policy | partial | FR-110, FR-111 |
| Storage lifecycle | partial | FR-112 |
| Insufficient information | partial | FR-113 |
| Stale learned knowledge as a failure state | partial | FR-114, SC-032 |
| Model uncertainty | absent | FR-115, SC-033 |
| Validation failure | partial | FR-116 |
| Capability discovery | absent | FR-117 to FR-120, SC-034, SC-035 |

New requirements are appended with continuing identifiers rather than
renumbered, so every reference already written — in this checklist and in the
spec's own cross-references — remains valid.

## Notes

**Clarifications resolved (21 of 21), through 2026-09-25.** The clarification record now contains the original three decisions, six 2026-09-14 remediation/outcome-encoding decisions, D1–D6 from the specification review, D7–D9 from the post-gate amendment, and D10–D12 from the 2026-09-25 SC-012 comparability session. Every decision names the FR/SC/Constitution rule it binds. The specification carries no unresolved clarification markers.

- **Q1 — token threshold** (SC-011): *set the target after a baseline run.* The
  threshold is derived from the baseline measurement now required by SC-036, and
  no efficiency work is accepted against a target chosen before that baseline
  exists. This honours the request's instruction that no arbitrary percentage be
  invented.
- **Remediation session 2026-09-14** (C1/A1): a mandatory clarification may never
  be resolved by the agent. Cancellation, decline, expiry and absence are
  lifecycle outcomes, not information outcomes; only a real answer resolves the
  decision and resumes dependent work. Agent-selected assumptions are confined to
  non-material decisions. Encoded in FR-003, FR-018, FR-019, FR-022, FR-035,
  FR-082, FR-129, FR-130 and SC-037 to SC-044. This supersedes the earlier
  "declined proceeds with stated assumptions" wording throughout.
- **Q2 — blocking scope** (FR-035, FR-121 to FR-123): *all non-interactive
  surfaces block.* This is the reading Constitution XV already mandates — the
  audit surfaced that the principle ratified earlier the same day settles this
  question rather than leaving it open. Blocking is confined to decisions passing
  the FR-007 materiality test, and a clarification-required run ends in a distinct
  machine-readable outcome so callers route it for an answer rather than retrying
  it as an error. This remains the initiative's one intended user-visible
  behaviour change (FR-082).
- **Q3 — gate authority** (FR-124 to FR-127): *annotate by default; block only a
  contradicted completion claim.* An honest partial answer is never withheld; an
  explicit claim of completion contradicted by evidence is corrected before
  delivery, at a cost of at most one additional turn, with a fallback to
  annotation where the gate cannot reach a verdict.

**Integrity check.** 130 functional requirements and 44 success criteria (174 in total); no
duplicate identifiers, no dangling cross-references, no placeholder text
remaining.

**Documented exception to "no implementation details".** Appendix A and the
*Context* section name existing modules and protocol messages by path. This is
deliberate and quarantined:

- The feature request requires inspecting the existing implementation and
  extending it rather than building a parallel architecture, and the constitution
  makes that a principle (XVIII). A brownfield "extend, do not duplicate"
  constraint is uncheckable without naming what already exists.
- Every numbered requirement (FR-001 to FR-085) and every success criterion
  (SC-001 to SC-026) is written as observable behaviour with no module, path or
  API named. The implementation references live only in the Context section,
  Appendix A and the Dependencies notes, all clearly labelled as evidence rather
  than design.

**Evidence base.** The inventory in Appendix A was taken by reading the
repository during specification, not from memory or prior reports. Three findings
changed the shape of the specification: the clarification transport already
exists end to end; the current no-answer behaviour is itself the gap-filling the
initiative forbids; and question capability is not the same as tool capability,
so the evidence-before-asking rule must be mode-aware.

**PR #39.** Inspected for overlap only. Thirteen paths, all trading-specific
except `docs/README.md`. No architectural conflict; recorded as a non-blocking
note rather than a blocking integration decision. Not merged, closed, rebased or
depended upon.


## Alignment update — 2026-09-24

- Current specification inventory: **130 FR / 44 SC**; identifier ranges are FR-001…FR-130 and SC-001…SC-044.
- Clarification record: **21/21 resolved**, including D1–D12. No active `[NEEDS CLARIFICATION]` marker remains in `spec.md`.
- Constitution XI: `spec.md` itself owns the normative ten-surface classification; `plan.md` may add implementation evidence but cannot override it.
- FR-082 now enumerates three intended user-visible changes. Only the removal of self-resolving mandatory non-answers is the backward-incompatible regression-by-design; the completion annotation/correction and same-decision re-raise suppression are additive.
- SC-011 is measurable at **>=10% lower mean total tokens than naive in the same paired run plus zero task-level outcome-rate regression**. The historical paired runs do not satisfy it; specification clarity is not acceptance evidence.
