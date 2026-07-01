# Evidence Brief Generation (Phase 5)

## Overview

Phase 5 implements a full evidence brief generation pipeline that converts retrieved evidence records into a structured, human-reviewable brief with claim-level citations, provenance tracking, and 16 automated QA checks.

The system produces two types of briefs:

| Mode | Description | LLM required? |
|------|-------------|---------------|
| `deterministic` | Pre-validated claim templates resolved at runtime | No |
| `live_llm` | LLM-drafted claims validated against strict rules | Yes |

All briefs carry an immutable disclaimer and are gated by the QA system before being persisted.

---

## 8-Step Pipeline

```
Evidence Run (Phase 4)
       │
  Step 1: Validate evidence run (run_id, records, query_hash required)
       │
  Step 2: Build immutable EvidenceSnapshot (content-addressed SHA-256 hash)
       │
  Step 3: Gate — snapshot must have ≥ 1 record; warn on failed sources
       │
  Step 4: Generate claims (deterministic templates OR live LLM)
       │
  Step 5: Resolve citations — stable [N] numbers, alphabetical claim order
       │
  Step 6: Generate limitations (deterministic from structured metadata)
       │
  Step 7: Run BQ-001 through BQ-016; block on critical failures
       │
  Step 8: Persist brief, snapshot, QA, audit entry to DuckDB
       │
  BriefGenerationResult
```

---

## Evidence Snapshot

Before generation begins, an immutable `EvidenceSnapshot` is built from the Phase 4 retrieval run. The snapshot:

- Contains one `EvidenceSnapshotRecord` per evidence record
- Is content-addressed: `snapshot_hash = SHA-256(sorted record IDs + content hashes)[:16]`
- Is linked to the brief by `evidence_snapshot_id` and `evidence_snapshot_hash`
- Cannot change after the brief is generated — a new retrieval run requires a new brief version

The brief's own `content_hash` covers the snapshot hash, all claim texts, and the disclaimer.

---

## Deterministic Generation

Claims are defined by stable PICO-keyed templates in `deterministic_generator.py`. Each template maps `(source_type, source_specific_id)` pairs to the actual `evidence_id` values in the current snapshot at runtime.

**Critical rules:**
- Never hard-code run-specific `ev-*` IDs in templates
- `MissingExpectedSourceError` is raised if a required template source is absent
- Claim IDs are stable (`cl-population-t2dm-ckd` etc.) so content hash is reproducible

Templates in Phase 5:

| Claim ID | Dimension | Type |
|----------|-----------|------|
| `cl-population-t2dm-ckd` | population | supported |
| `cl-intervention-sglt2-rct` | intervention | supported |
| `cl-outcome-cv-renal` | outcome | supported |
| `cl-design-rct-evidence` | design | supported |
| `cl-observational-association` | outcome | exploratory |
| `cl-coverage-cms` | coverage | supported |

A `safety` evidence gap is always generated (no safety-specific records in the Phase 4 fixture set).

---

## Live LLM Generation

`llm_generator.py` builds a structured prompt containing only safe metadata fields and validates the LLM response strictly:

**Blocked outputs:**
- Unknown source IDs (not in snapshot)
- Causal language on observational or CMS sources
- Patient-specific recommendation language
- CMS-only outcome/effectiveness claims
- Trial-without-results outcome claims
- Empty source_ids on supported/exploratory claims

At most one structural retry is attempted. Any retry is logged in the audit trail.

---

## Citation Numbering

Citations are numbered by stable [N] references:
1. Claims are sorted alphabetically by `claim_id`
2. Each unique `source_id` gets exactly one number, assigned on first appearance
3. Subsequent references to the same source reuse the same number
4. The bibliography lists all unique citations in number order

---

## Disclaimer

Every brief contains an immutable disclaimer derived from `_REQUIRED_DISCLAIMER_FRAGMENT`:

> This brief was generated with automated methods. It is not a clinical recommendation, has not been clinically validated, and must not be used for patient care decisions.

For `live_llm` mode, the disclaimer appends: *Generative AI was used to draft the narrative content.*

The `EvidenceBrief.model_validator` enforces this fragment is present. The Streamlit page also displays the disclaimer as a persistent error banner before any content.

---

## Data-Origin Classification

Each evidence record is classified at snapshot build time:

| `DataOriginClass` | Meaning |
|-------------------|---------|
| `live_api` | Fetched from live public API at retrieval time |
| `captured_source_fixture` | Captured from a public source, versioned in fixtures |
| `manually_constructed_fixture` | Hand-authored for testing |
| `mixed` | Multiple origins in the same snapshot |

The `data_notice` field is dynamically generated from the aggregate classification — never a blanket claim that all records are live.

---

## What This System Does NOT Do

- No PDF or PPTX export
- No auto-approval of review actions
- No cross-merging of records from different sources by title similarity
- No LLM generation in default (demo) mode
- No patient-specific treatment recommendations
- No claims that observational findings establish causation
- No claims that CMS coverage documents establish clinical effectiveness
