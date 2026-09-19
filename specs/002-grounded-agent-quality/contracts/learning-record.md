# Contract: Learning Record

**Feature**: 002-grounded-agent-quality

Governs what may enter durable memory, what it must carry, and when it stops
being applied. Extends `learning/store.py`; introduces no second store.

---

## L1. Admission gate

Every candidate passes one gate before it becomes durable. **No caller bypasses
it — including the model-driven passes in `reflect.py` and `review.py`.**

```text
candidate
   │
   ├─ provenance ∈ { user_correction, user_statement, settled_decision,
   │                 counted_convention, validated_outcome, tool_confirmed }
   │        │
   │        ├─ caps available? ──no──► REFUSE, list current contents (FR-065)
   │        └─ yes ──► ADMIT with provenance, source_ref, fingerprint, timestamp
   │
   └─ anything else (an unverified model assertion) ──────────► REFUSE (FR-056)
```

**Admissible sources, and who already produces them**

| Provenance | Existing producer | Model call? |
| --- | --- | --- |
| `user_correction` | `learning/signals.py` — detects rewrites, undos, refusals | No |
| `user_statement` | User message, `tools/memory.py` | No |
| `settled_decision` | A question answered through the form | No |
| `counted_convention` | `learning/rules.py` — counted with evidence | No |
| `validated_outcome` | Completion gate `VALIDATED` | No |
| `tool_confirmed` | Evidence ledger `VERIFIED` entry | No |

Every admissible class is produced deterministically. A model proposal is only
admissible if it is *corroborated* into one of these classes — the proposal alone
is not provenance.

---

## L2. Required fields on admission

| Field | Rule |
| --- | --- |
| `provenance` | One of the six above; no other value is storable |
| `scope` | Project or user. **Already exists** |
| `source_ref` | What it came from |
| `fingerprint` | Of the derivation source, for repository-derived items |
| `established_at` | Timestamp, for supersession ordering |
| `confidence` | Where meaningful |
| `status` | `active` on admission |

---

## L3. Invalidation and supersession

| Trigger | Result | Deterministic? |
| --- | --- | --- |
| A newer contradicting correction | Older → `superseded`, `superseded_by` set; newer governs | Yes — by `established_at` (FR-059) |
| Source fingerprint mismatch at recall | → `stale`, excluded from recall | Yes (FR-060, FR-114) |
| Decay below the confidence floor | → `stale` (existing curator behaviour) | Yes |
| User deletion | → `removed` | User-initiated |

**Nothing is hard-deleted that the user did not ask to delete.** This is the
curator's existing principle and it is preserved: `superseded` and `stale` items
remain inspectable through the existing timeline and memory views.

---

## L4. Retrieval policy

| Rule | Requirement |
| --- | --- |
| Relevance | Ranked against the work in hand, using the existing index |
| Scope | Project-scoped knowledge never applies in another project (FR-058) |
| Status | `stale`, `superseded` and `removed` are excluded |
| Budget | Bounded by the existing recall cap (FR-062) |
| Visibility | What was recalled is shown to the user and attributable afterwards (FR-061, FR-111) |
| Position | Recall rides the **user message**, never the system prompt — this is what keeps the cached prefix byte-identical |

---

## L5. Untrusted content

Text arriving from a file, a web page, a tool result or a channel message is
**not** admissible on its own authority (FR-066). It may become a
`tool_confirmed` fact about *what the file contains*, which is different from
becoming a belief about the world. Existing injection checks in
`learning/facts.py` are preserved.

---

## L6. Caps and reproducibility

| Rule | Value |
| --- | --- |
| Project facts | 8 — unchanged by this feature |
| User facts | 6 — unchanged |
| At cap | Explicit refusal listing current contents; never silent eviction |
| Benchmark runs | Learning disabled, as it already is — a measurement that learns measures the order its tasks ran in |
| Persistence boundary | Deterministic and testable; the async writer's batching is durability, not semantics (FR-063) |
