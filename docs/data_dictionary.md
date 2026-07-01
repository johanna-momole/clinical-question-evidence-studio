# Data Dictionary

## Core Schema Entities

### ClinicalQuestion
| Field | Type | Description |
|-------|------|-------------|
| id | str | Unique identifier (e.g., `q-sglt2-ckd-t2dm-001`) |
| raw_question | str | Original natural-language question text |
| pico | PICOFramework | Structured PICO representation |
| ambiguity_flags | list[AmbiguityFlag] | Identified ambiguities requiring resolution |
| clarifying_questions | list[str] | Open questions before study design |
| status | Literal | draft → approved → archived |
| source | Literal | user_input / predefined / llm_generated |

### PhenotypeDefinition
| Field | Type | Description |
|-------|------|-------------|
| id | str | Unique phenotype identifier |
| version | str | Semantic version (e.g., `0.1.0`) |
| concepts | list[ClinicalConcept] | Clinical concepts with terminology mappings |
| inclusion_rules | list[PhenotypeRule] | Qualifying criteria |
| exclusion_rules | list[PhenotypeRule] | Disqualifying criteria |
| fhir_mappings | list[FHIRResourceMapping] | FHIR R4 implementation details |
| lookback_period_days | int | Minimum lookback window |
| review_status | Literal | draft → under_review → approved |

### TerminologyMapping
| Field | Type | Description |
|-------|------|-------------|
| terminology_system | Literal | ICD-10-CM / RxNorm / LOINC / SNOMED-CT / CPT |
| code | str | Standard code |
| review_status | Literal | candidate / approved / rejected |
| is_llm_suggested | bool | Requires human review if True |
| confidence | Literal | high / medium / low |

### NormalizedPatient / NormalizedCondition / NormalizedEncounter / NormalizedObservation / NormalizedMedication / NormalizedProcedure
| Field | Type | Description |
|-------|------|-------------|
| patient_id | str | Synthetic patient identifier (FHIR `Patient.id`) |
| source_resource_id | str | Original FHIR resource `id`, preserved for traceability |
| code / code_system | str | Coded value and its terminology system (ICD-10-CM, LOINC, RxNorm) |
| *(dates vary by resource)* | date | `onset_date`, `start_date`/`end_date`, `effective_date`, etc. |

All six normalized types are produced by `src/fhir/normalizer.py` from raw bundled synthetic FHIR R4 resources and held in-memory as a `NormalizedDataset` (lists per resource type plus a `patient_ids` frozenset and `resource_type_counts()` helper). No real patient data is ever parsed — only bundled synthetic fixtures under `data/fixtures/fhir/`.

### CohortStep
| Field | Type | Description |
|-------|------|-------------|
| step_number | int | Sequential 1-based index in the attrition waterfall |
| label / description | str | Short label and full criteria description |
| records_in | int | Patient count entering this step |
| records_excluded | int | Patients excluded by this criterion |
| records_out | int | Patient count passing this step |
| exclusion_reason | str \| None | Reason text for exclusion steps |

`records_out == records_in - records_excluded` is enforced by a Pydantic model validator — a `CohortStep` that violates the invariant cannot be constructed.

### CohortAttrition
| Field | Type | Description |
|-------|------|-------------|
| steps | list[CohortStep] | Full sequential waterfall for one run |
| reconciles | bool (property) | True if every step's `records_out` equals the next step's `records_in` |
| final_count | int (property) | `records_out` of the last step, or 0 if empty |

### CohortConfiguration
| Field | Type | Description |
|-------|------|-------------|
| reference_date | date | Fixed index date for all age/temporal calculations |
| min_age_years | int | Minimum age at reference date (default 18) |
| observation_lookback_days | int | Required prior observation history (default 365) |
| include_medication_exposure_filter | bool | Opt-in OPTIONAL exploratory SGLT2 filter using LLM-suggested, unverified RxNorm codes — never a required step |
| require_lab_availability | bool | Opt-in OPTIONAL filter requiring ≥1 qualifying lab result in window |
| dataset_id | str | Synthetic FHIR dataset identifier to run against |

### CohortSummary
| Field | Type | Description |
|-------|------|-------------|
| initial_population | int | All records in source dataset |
| final_cohort_count | int | Records after all inclusion/exclusion criteria |
| demographic_summary | DemographicSummary \| None | Age stats and sex/race distribution of the final cohort |
| condition_prevalence | dict[str, float] | ICD-10-CM code → prevalence (0.0–1.0) in the final cohort |
| missingness_report | list[MissingnessReport] | Completeness metrics for key analytical variables |
| data_source | str | Description of synthetic data source (always discloses synthetic origin) |
| is_synthetic | Literal[True] | Always True — synthetic data only |
| data_quality_status | Literal | passed / warning / failed |
| qa_warnings | list[str] | Non-critical data quality warnings from this run |

### CohortProvenance
| Field | Type | Description |
|-------|------|-------------|
| run_id | str | Unique cohort execution identifier |
| phenotype_id / phenotype_version | str | Phenotype applied and its version |
| phenotype_review_status | Literal | draft / under_review / approved — must be `approved` for the run to have executed |
| fhir_ingestion_run_id | str | Links back to the FHIR ingestion run that produced the analytical dataset |
| configuration_hash | str | SHA-256 hash of `CohortConfiguration` (excluding `dataset_id`), for reproducibility verification |
| is_synthetic | Literal[True] | Always True |

### CohortRun
| Field | Type | Description |
|-------|------|-------------|
| run_id | str | Unique run identifier |
| configuration | CohortConfiguration | Parameters used for this run |
| attrition | CohortAttrition | Full step-by-step waterfall |
| summary | CohortSummary | Aggregated cohort statistics |
| provenance | CohortProvenance | Reproducibility metadata |
| warnings | list[str] | e.g., LLM-suggested-mapping warnings, optional-filter provisional-result warnings |

### EvidenceRecord (Phase 4)
| Field | Type | Description |
|-------|------|-------------|
| id | str | `ev-{source}-{identifier}-{content_hash}` — stable, idempotent |
| source_type | Literal | `publication` / `clinical_trial` / `cms_coverage` |
| source_name | EvidenceSourceName | `pubmed` / `clinical_trials_gov` / `cms_coverage` |
| title | str | Record title (required) |
| identifier | str | Source-native ID (PMID, NCT ID, LCD doc ID) |
| url | str \| None | Link to source record |
| publication_or_update_date | date \| None | Best available date |
| date_precision | DatePrecision | `day` / `month` / `year` / `unknown` |
| study_design | str \| None | Rule-based design label (e.g., `Meta-analysis`, `RCT`) |
| status | str \| None | Trial overall status or CMS document status |
| relevance_score | float \| None | Weighted tag overlap score ∈ [0.0, 1.0] |
| review_status | Literal | `pending` / `included` / `excluded` |
| content_hash | str \| None | SHA-256 of raw payload JSON (16 hex chars) |
| is_fixture_data | bool | True if from offline fixture |
| duplicate_of | str \| None | ID of the canonical record if this is a within-source duplicate |
| tags | list[str] | Flat tag list, e.g. `["population:t2dm", "intervention:sglt2_class"]` |
| structured_tags | list[EvidenceTag] | Typed tags with `dimension` and `rule_id` |
| retrieval_run_id | str | Links to `RetrievalRun.run_id` |
| raw_record_id | str | Links to `RawEvidenceRecord.id` |

Subclasses add source-specific fields:
- `PublicationRecord`: `pmid`, `abstract`, `authors_or_sponsor`, `mesh_terms`, `journal`, `doi`, `publication_types`
- `ClinicalTrialRecord`: `nct_id`, `phase`, `enrollment`, `trial_status`, `primary_completion_date`, `sponsor`, `conditions`, `interventions`, `has_results_posted`
- `CoverageRecord`: `lcd_or_ncd_id`, `document_type`, `jurisdiction`, `effective_date`, `retirement_date`, `contractor`, `coverage_determination`, `applicable_codes`

### RawEvidenceRecord (Phase 4)
| Field | Type | Description |
|-------|------|-------------|
| id | str | `raw-{source}-{identifier}-{content_hash}` |
| source_name | EvidenceSourceName | Source adapter that produced this record |
| source_identifier | str | PMID, NCT ID, etc. |
| content_hash | str | SHA-256 of `raw_payload` JSON with `sort_keys=True`, 16 hex chars |
| fetched_at | datetime | UTC timestamp of retrieval |
| is_fixture_data | bool | True if from offline fixture |
| fixture_manifest_version | str \| None | Fixture version string when `is_fixture_data=True` |
| raw_payload | dict[str, Any] | Verbatim source payload, never modified |

### RetrievalRun (Phase 4)
| Field | Type | Description |
|-------|------|-------------|
| run_id | str | UUID |
| query | EvidenceQuery | Deterministic query with `query_hash` |
| request | EvidenceRetrievalRequest | Original request parameters |
| source_statuses | list[EvidenceSourceStatus] | Per-source record counts, cache hit, errors |
| provenance | RetrievalProvenance | Fixture versions, retrieval mode, authenticity note |
| started_at / completed_at | datetime | Run timing |
| total_records_retrieved | int | Sum across all sources |
| total_records_after_dedup | int | After within-source deduplication |

### TerminologyVerificationResult (Phase 4)
| Field | Type | Description |
|-------|------|-------------|
| rxcui | str | RxCUI being verified |
| found | bool | Whether the RxCUI exists in the source |
| verified_name | str \| None | Official concept name from RxNorm |
| term_type | str \| None | RxNorm term type (IN, BN, SCD, etc.) |
| is_active | bool \| None | Whether the concept is active |
| matches_expected_name | bool \| None | Name comparison result (None if no expected name given) |
| source | Literal | `rxnorm_fixture` / `rxnorm_api` |
| verified_at | datetime | UTC timestamp |
| is_fixture_data | bool | True if from offline fixture |
| notes | list[str] | Human-readable notes (name mismatches, inactive status warnings) |

**Important:** Verification results NEVER auto-update a `TerminologyMapping.review_status`. Human reviewer action is always required.

### EvidenceBrief (Phase 5 — planned)
| Field | Type | Description |
|-------|------|-------------|
| key_findings | list[GeneratedClaim] | Claims with provenance type |
| is_deterministic_mode | bool | True when no live LLM was used |
| human_review_status | Literal | not_reviewed / in_review / approved |
| disclaimer | str | Required display text (always pre-populated) |
