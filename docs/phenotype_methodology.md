# Phenotype Methodology

## Overview

A computable phenotype is a machine-executable set of rules that identifies a patient population from structured clinical data. In this prototype, phenotypes are defined as versioned JSON documents (`PhenotypeDefinition`) and applied to synthetic FHIR R4 data.

## Phenotype Structure

Each phenotype includes:

1. **Clinical concepts** — named clinical ideas (e.g., "Type 2 Diabetes Diagnosis") with candidate terminology mappings
2. **Terminology mappings** — candidate codes from ICD-10-CM, RxNorm, LOINC, or SNOMED-CT
3. **Inclusion rules** — criteria that qualify a patient for the cohort
4. **Exclusion rules** — criteria that remove a patient from the cohort
5. **FHIR resource mappings** — how each concept maps to FHIR R4 elements
6. **Index date definition** — the anchor event that defines time-zero

## Mapping Governance

All terminology mappings in this prototype are labeled as **candidate mappings requiring clinical expert review** before production use. This is enforced at the data model level (`review_status: "candidate"`).

LLM-suggested mappings are additionally flagged with `is_llm_suggested: true` and must never be promoted to `approved` status without human review.

This governance is enforced structurally, not just by labeling: the Phase 3 cohort engine refuses to treat a `required` inclusion rule as a hard gate if every mapping backing its concept is LLM-suggested (e.g., the SGLT2 RxNorm concept). Such rules are instead demoted to an explicit, opt-in exploratory filter. See [cohort_methodology.md](cohort_methodology.md#gate-2--llm-suggested-only-concepts-never-back-a-required-step) for the mechanism.

## Version Control

Every change to phenotype logic increments the version field (semantic versioning). The `changelog` array records each change with date and description. Cohort runs reference the phenotype version so results are reproducible.

## Limitations

- Diagnosis codes alone are insufficient to stage CKD — eGFR laboratory values provide greater specificity.
- Administrative codes have known limitations including upcoding, undercoding, and lag between clinical diagnosis and documentation.
- This prototype uses synthetic data patterns that may not reflect real-world code distributions.
- All mappings should be reviewed against current terminology versions before any research application.
