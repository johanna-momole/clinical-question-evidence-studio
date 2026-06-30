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

### EvidenceRecord
| Field | Type | Description |
|-------|------|-------------|
| source_type | Literal | publication / clinical_trial / cms_coverage / guideline |
| identifier | str | PMID, NCT ID, LCD number, etc. |
| retrieval_timestamp | datetime | UTC retrieval time (required for provenance) |
| review_status | Literal | pending / included / excluded |
| raw_response | dict | Preserved raw API response |

### EvidenceBrief
| Field | Type | Description |
|-------|------|-------------|
| key_findings | list[GeneratedClaim] | Claims with provenance type |
| is_deterministic_mode | bool | True when no live LLM was used |
| human_review_status | Literal | not_reviewed / in_review / approved |
| disclaimer | str | Required display text (always pre-populated) |
