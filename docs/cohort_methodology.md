# Synthetic Cohort Construction Methodology

## Purpose

Phase 3 turns an approved phenotype definition into a reproducible patient cohort drawn from the bundled synthetic FHIR dataset, with a fully auditable, step-by-step attrition trail. The implementation lives in `src/cohorts/` (`rules.py`, `engine.py`, `service.py`) and is exercised via `POST /cohorts/run` and Streamlit page 4 (`app/pages/4_Synthetic_Cohort.py`).

All patients, counts, and prevalence figures produced by this pipeline describe the **fictional synthetic dataset only**. See [synthetic_data_methodology.md](synthetic_data_methodology.md) for the data-source disclosure.

## Safety gates

The engine (`src/cohorts/engine.py::run_cohort`) enforces two structural safety gates before any patient is evaluated, so that an LLM can never silently define or approve the final phenotype:

### Gate 1 — Phenotype must be approved

`phenotype.review_status` must equal `"approved"`. If not, `run_cohort()` raises `UnapprovedPhenotypeError` immediately — no attrition steps are computed. In the Streamlit flow, approval is a manual human action ("Approve phenotype structure for synthetic demo" button on the Phenotype Builder page); the API requires either a pre-approved phenotype or an explicit `approve_for_demo: true` flag on the request, which still represents an explicit user action, not an automatic or LLM-driven approval.

### Gate 2 — LLM-suggested-only concepts never back a required step

A `PhenotypeRule.required=True` rule can be marked required in the phenotype JSON, but if **every** non-rejected terminology mapping for its concept is `is_llm_suggested=True` (the SGLT2 inhibitor RxNorm concept, `c-sglt2`, is the current example), the engine overrides that flag: the concept is excluded from the required inclusion-rule loop (engine.py, Step 4) and is only evaluated as an **optional, clearly-labeled exploratory step** (Step 6) when a user explicitly opts in via `CohortConfiguration.include_medication_exposure_filter=True`. A QA warning is always emitted in this case, both at gate-check time (`_assert_required_concepts_resolved`) and, if the optional filter is run, again with a "PROVISIONAL MEDICATION FILTER" message attached to the step. The attrition step label is prefixed `EXPLORATORY:` and explicitly states the codes are unverified.

This is a deliberate design choice, not a bug: the underlying RxNorm codes for `c-sglt2` were suggested by an LLM during phenotype drafting and have not been checked against the live RxNorm API (see `docs/llm_governance.md`). Promoting an unverified, LLM-suggested code set to a required inclusion criterion would let the LLM silently determine cohort membership — exactly what the project's governing constraints forbid.

A third failure mode, `UnresolvedConceptError`, is raised if a *required, non-LLM-suggested* concept has **zero** candidate codes at all (e.g., a malformed or incomplete phenotype) — this is a hard stop, since there is no way to evaluate the rule.

## Attrition pipeline

Each run produces a sequential `CohortAttrition` of `CohortStep` objects. The exact steps executed depend on the phenotype and `CohortConfiguration`, but for the bundled SGLT2/CKD/T2DM phenotype the sequence is:

| Step | Criterion | Type |
|------|-----------|------|
| 1 | All synthetic patients in the dataset | Baseline |
| 2 | Age ≥ `min_age_years` at `reference_date` (default 18); missing birth date excluded conservatively | Required (demographic, via `CohortConfiguration`) |
| 3 | ≥ `observation_lookback_days` of observation history (default 365d) before `reference_date`; patients with no encounters excluded | Required |
| 4 | Required inclusion rules with resolvable, non-fully-LLM-suggested codes (e.g., T2DM condition code, CKD condition code) | Required |
| 5 | Required exclusion rules (e.g., ESRD, dialysis dependence) | Required |
| 6 | **Optional** — SGLT2 candidate medication exposure (LLM-suggested, unverified RxNorm codes) | Opt-in, exploratory only |
| 7 | **Optional** — eGFR lab availability within lookback window | Opt-in |

Verified, deterministic run against the bundled dataset (seed=42, `reference_date=2025-06-01`, default configuration): **160 → 148 (age) → 143 (observation period) → 113 (T2DM) → 78 (CKD) → 78 (ESRD exclusion, 0 excluded) → 70 (dialysis exclusion, 8 excluded)**. Final cohort: 70 patients.

### Attrition invariant

Every `CohortStep` enforces `records_out == records_in - records_excluded` as a Pydantic model validator (`CohortStep.validate_attrition_math` in `src/schemas/cohort.py`) — a step that violates this cannot even be constructed. The engine additionally tracks the "before" count (`prev = len(current)`) explicitly before reassigning the working patient set, specifically to avoid a closure bug where `records_in` would be read from the *already-updated* variable (see the `_add_step()` helper signature, which takes `records_in` as an explicit argument rather than deriving it implicitly).

`CohortAttrition.reconciles` additionally checks step-to-step continuity: `step[n].records_out == step[n+1].records_in` across the whole sequence. Both the attrition-math invariant and step continuity are independently re-verified post-hoc by `src/qa/cohort_checks.py` (`coh-004` and `coh-005`), so a regression in the engine would be caught by QA even if the Pydantic validator were ever bypassed.

## Determinism

Given the same `PhenotypeDefinition`, `CohortConfiguration`, and `NormalizedDataset`, `run_cohort()` produces identical attrition step tuples (`records_in`, `records_excluded`, `records_out`) and an identical `final_cohort_count` on every invocation — there is no randomness, sampling, or LLM call inside the engine itself. This was verified by running the pipeline twice with identical inputs and diffing the full attrition sequence (see `tests/unit/test_cohorts.py::TestCohortAttrition::test_determinism_across_runs`).

`CohortProvenance.configuration_hash` is a SHA-256 hash (truncated to 16 hex characters) of the configuration parameters that affect attrition (excluding `dataset_id`), allowing two runs to be compared for parameter equivalence without diffing the full JSON.

## Outputs

A `CohortRun` bundles:
- `attrition` — the full step-by-step waterfall
- `summary` — demographic summary, condition prevalence, medication exposure, encounter summary, and a missingness report (currently eGFR baseline availability) for the **final cohort only**
- `provenance` — run ID, phenotype ID/version/review-status, dataset ID, FHIR ingestion run ID, configuration hash, and an `is_synthetic: Literal[True]` marker
- `warnings` — every QA warning generated during the run (LLM-suggested-mapping overrides, provisional medication-filter notices)

## Known limitations

- **Run persistence is in-memory only.** `CohortService` holds completed runs in a process-local dict (`self._runs`), not a durable DuckDB-backed repository. Runs do not survive an API/Streamlit process restart. This was a deliberate scope reduction for the portfolio demo; a production system would persist `CohortRun` records to durable storage.
- **`coh-008` (duplicate patient IDs per step) is not currently exercised.** `CohortService.run()` does not thread per-step patient ID sets through to `run_cohort_checks()`, so this check always reports `not_applicable` rather than a real pass/fail. The attrition-math and step-continuity checks (`coh-004`, `coh-005`) provide independent coverage of the most likely failure modes in practice.
