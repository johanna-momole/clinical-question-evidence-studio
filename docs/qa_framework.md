# Quality Assurance Framework

## Categories

### Data Quality (`data_quality`)
Checks applied to synthetic patient data and cohort outputs:
- Required columns and schemas present
- No impossible dates (birth after death, encounter before birth)
- No duplicate patient records
- Cohort attrition reconciles mathematically (`records_out == records_in - records_excluded`)
- Unexpected cohort-size changes flagged
- Invalid code-system values detected
- Missingness reported for key analytical variables

### Evidence Quality (`evidence_quality`)
Checks applied to retrieved external evidence:
- No duplicate publications (same PMID or NCT ID)
- All records have retrieval timestamps
- URL present for citation
- Evidence freshness (flagged if >5 years old by default)
- No unsupported source types
- Source references accessible
- Conflicting findings between sources flagged

### AI Quality (`ai_quality`)
Checks applied to LLM-generated content:
- Every factual claim has a supporting source ID
- No uncited clinical claim in the evidence brief
- No patient-specific recommendation
- No causal claim from observational or synthetic outputs
- Candidate terminology mappings are labeled
- Prompt and model version logged for every LLM call
- Generated text is visually distinguished from retrieved facts
- Deterministic fallback mode available and tested

## Phase 3 Implemented Checks

### FHIR ingestion checks (`src/qa/fhir_checks.py`, run by `run_fhir_checks()`)

| ID | Check | Severity | Trigger |
|----|-------|----------|---------|
| fhir-001 | Non-empty patient population | critical | Zero `Patient` resources ingested |
| fhir-002 | No fatal ingestion errors | major | One or more resources dropped due to a fatal parse error |
| fhir-003 | No orphaned Condition references | major | A `Condition.patient_id` does not match any ingested patient |
| fhir-004 | No orphaned Encounter references | major | An `Encounter.patient_id` does not match any ingested patient |
| fhir-005 | Valid encounter date order | major | `Encounter.end_date < Encounter.start_date` |
| fhir-006 | Birth dates present | minor | A patient has no `birth_date` (age cannot be calculated) |
| fhir-007 | Plausible birth dates | major | `birth_date` falls after the patient's earliest encounter |
| fhir-008 | Observations have values | minor | An observation has neither a numeric nor text value |
| fhir-009 | Valid medication date order | minor | `Medication.end_date < Medication.start_date` |
| fhir-010 | All patients have encounters | minor | A patient has zero encounter records |

### Cohort execution checks (`src/qa/cohort_checks.py`, run by `run_cohort_checks()`)

| ID | Check | Severity | Trigger |
|----|-------|----------|---------|
| coh-001 | Non-empty starting population | critical | `initial_count == 0` |
| coh-002 | Sequential step numbering | critical | Step numbers are not a continuous 1-based sequence |
| coh-003 | Non-negative exclusion counts | critical | Any step has `records_excluded < 0` |
| coh-004 | Attrition math reconciles | critical | `records_out != records_in - records_excluded` for any step |
| coh-005 | Step continuity | critical | A step's `records_out` does not equal the next step's `records_in` |
| coh-006 | Final cohort within bounds | critical | Final `records_out` exceeds the initial population |
| coh-007 | Non-empty intermediate steps | major (warning) | An intermediate step produces 0 patients before the final step |
| coh-008 | No duplicate patient IDs per step | critical, or `not_applicable` | Only evaluated when `patient_ids_at_steps` is supplied; currently `not_applicable` in `CohortService.run()` since per-step patient ID sets are not yet threaded through |

A cohort run with any `critical`-severity failure must not be exported or treated as a valid result; the API and Streamlit page surface `has_critical_failure` and block on it.

## Severity Levels

| Level | Meaning |
|-------|---------|
| `critical` | Blocks pipeline from proceeding; must be resolved before export |
| `major` | Serious issue; export should carry a warning |
| `minor` | Best-practice issue; noted but does not block |
| `info` | Informational; no action required |

## Check Status Values

| Status | Meaning |
|--------|---------|
| `passed` | Check succeeded |
| `warning` | Check detected a non-blocking issue |
| `failed` | Check failed; see severity for impact |
| `not_applicable` | Check does not apply to this run |
