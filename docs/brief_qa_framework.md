# Brief QA Framework (Phase 5)

All BQ checks run automatically after claim generation and before persistence. A brief with any `critical` failure is rejected.

## Check Registry

| Check ID | Name | Severity | When triggered |
|----------|------|----------|----------------|
| BQ-001 | Required citations | Critical | Any `supported` or `exploratory` claim has zero `source_ids` |
| BQ-002 | Citation existence | Critical | A `source_id` is not in the immutable evidence snapshot |
| BQ-003 | Disclaimer integrity | Critical | Disclaimer is missing the required safety fragment |
| BQ-004 | Source-to-claim compatibility | Critical | CMS or unresulted trial as sole support for effectiveness |
| BQ-005 | Patient-specific recommendation | Critical | Claim text contains prescriptive language |
| BQ-006 | Causal-language detection | Major | Causal language with observational or CMS sources |
| BQ-007 | Generation provenance | Critical | Missing provenance metadata for the generation mode |
| BQ-008 | Generation-mode accuracy | Major | Inconsistency between `generation_mode` and `model_name` |
| BQ-009 | Evidence-run integrity | Critical | Missing `evidence_run_id`, `snapshot_id`, or `snapshot_hash` |
| BQ-010 | Partial-source disclosure | Major | Failed sources not mentioned in `limitations` |
| BQ-011 | Claim citation coverage | Critical | Citation coverage < 100% for factual claims |
| BQ-012 | Data-origin accuracy | Critical | `data_notice` text inconsistent with `data_origin` classification |
| BQ-013 | Trial-status accuracy | Major | Outcome claim cites trial with no posted results |
| BQ-014 | Coverage-jurisdiction accuracy | Major | Local CMS LCD described as nationally applicable |
| BQ-015 | Unsupported numeric claim | Critical (warn) | Numeric values in LLM-generated claims (requires human review) |
| BQ-016 | Review and audit integrity | N/A | Status tracker for approved briefs |

## Severity Levels

| Severity | Effect |
|----------|--------|
| `critical` + `failed` | Brief generation is blocked (`CriticalQABlockError` raised) |
| `major` + `warning` | Brief is generated with warnings in `qa_summary` |
| `info` | Informational only |
| `not_applicable` | Check does not apply to this brief |

## Status Values

- `passed` — check condition met
- `failed` — check condition not met
- `warning` — potential issue flagged; not blocking
- `not_applicable` — check skipped (e.g., deterministic mode for BQ-015)

## Implementation

Checks run in `src/qa/brief_checks.py:run_brief_checks()`. All checks operate on the completed `EvidenceBrief` and the immutable `EvidenceSnapshot`. Results are stored in the `brief_qa_results` DuckDB table.
