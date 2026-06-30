"""Cohort execution engine: applies a PhenotypeDefinition to a NormalizedDataset.

Gate rules:
1. phenotype.review_status must be "approved" before execution.
2. Required inclusion concepts must have at least one candidate mapping with a code
   that is NOT is_llm_suggested=True to back a required attrition step.
3. Concepts where ALL mappings are is_llm_suggested=True (specifically c-sglt2/RxNorm)
   are restricted to the optional exploratory medication filter; they NEVER back a
   required step regardless of PhenotypeRule.required flag.
4. This design is explicitly documented — it is a deliberate safety override for the
   synthetic portfolio demo, not a bug. See docs/cohort_methodology.md.

All results are labeled as synthetic. No real patient data is processed.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date

from src.cohorts import rules as R
from src.fhir.normalizer import NormalizedDataset
from src.schemas.cohort import (
    CohortAttrition,
    CohortConfiguration,
    CohortProvenance,
    CohortRun,
    CohortStep,
    CohortSummary,
    DemographicSummary,
    MissingnessReport,
)
from src.schemas.phenotype import ClinicalConcept, PhenotypeDefinition
from src.utils.exceptions import UnapprovedPhenotypeError, UnresolvedConceptError

# ---------------------------------------------------------------------------
# Concept code extraction helpers
# ---------------------------------------------------------------------------


def _codes_for_concept(concept: ClinicalConcept, exclude_llm_suggested: bool) -> frozenset[str]:
    """Extract all non-rejected codes from a concept's mappings.

    If exclude_llm_suggested=True, skip LLM-suggested mappings (used for required steps).
    """
    return frozenset(
        m.code
        for m in concept.mappings
        if m.review_status != "rejected" and (not exclude_llm_suggested or not m.is_llm_suggested)
    )


def _all_llm_suggested(concept: ClinicalConcept) -> bool:
    """Return True if every non-rejected mapping in this concept is LLM-suggested."""
    non_rejected = [m for m in concept.mappings if m.review_status != "rejected"]
    if not non_rejected:
        return True
    return all(m.is_llm_suggested for m in non_rejected)


def _concept_by_id(phenotype: PhenotypeDefinition, concept_id: str) -> ClinicalConcept | None:
    for c in phenotype.concepts:
        if c.concept_id == concept_id:
            return c
    return None


# ---------------------------------------------------------------------------
# Gate checks
# ---------------------------------------------------------------------------


def _assert_approved(phenotype: PhenotypeDefinition) -> None:
    if phenotype.review_status != "approved":
        raise UnapprovedPhenotypeError(
            f"Cohort execution requires phenotype.review_status == 'approved'; "
            f"got '{phenotype.review_status}' for phenotype '{phenotype.id}'. "
            "Approve the phenotype structure via the Phenotype Builder before running."
        )


def _assert_required_concepts_resolved(
    phenotype: PhenotypeDefinition,
) -> list[str]:
    """Check that each required inclusion rule has resolvable non-LLM codes.

    Returns a list of QA warning strings for concepts that are fully LLM-suggested
    (will be skipped as required steps).
    Raises UnresolvedConceptError for concepts that have NO codes at all.
    """
    _CODED_RESOURCES = {
        "Condition",
        "Observation",
        "MedicationRequest",
        "MedicationStatement",
        "Procedure",
    }
    warnings: list[str] = []
    for rule in phenotype.inclusion_rules:
        if not rule.required:
            continue
        concept = _concept_by_id(phenotype, rule.concept_id)
        if concept is None:
            raise UnresolvedConceptError(
                f"Inclusion rule '{rule.rule_id}' references unknown concept '{rule.concept_id}'"
            )
        if concept.fhir_resource not in _CODED_RESOURCES:
            # Demographic concepts (Patient, etc.) are handled via CohortConfiguration params
            continue
        all_codes = _codes_for_concept(concept, exclude_llm_suggested=False)
        if not all_codes:
            raise UnresolvedConceptError(
                f"Concept '{rule.concept_id}' has no candidate mappings -- "
                f"cannot evaluate required inclusion rule '{rule.rule_id}'"
            )
        if _all_llm_suggested(concept):
            warnings.append(
                f"Inclusion rule '{rule.rule_id}' (concept '{rule.concept_id}') has only "
                "LLM-suggested unverified mappings; it will be treated as an optional exploratory "
                "filter, not a required attrition step."
            )
    return warnings


# ---------------------------------------------------------------------------
# Demographic helpers
# ---------------------------------------------------------------------------


def _build_demographic_summary(
    patient_ids: frozenset[str],
    dataset: NormalizedDataset,
    reference_date: date,
) -> DemographicSummary:
    import statistics as stats

    pts = [p for p in dataset.patients if p.patient_id in patient_ids]
    raw_ages = [R.age_on(p.birth_date, reference_date) for p in pts if p.birth_date is not None]
    ages = [a for a in raw_ages if a is not None]
    sex_dist: dict[str, int] = {}
    for p in pts:
        sex_dist[p.sex] = sex_dist.get(p.sex, 0) + 1

    return DemographicSummary(
        total_patients=len(pts),
        age_mean=round(stats.mean(ages), 1) if ages else None,
        age_std=round(stats.stdev(ages), 1) if len(ages) > 1 else None,
        age_median=round(stats.median(ages), 1) if ages else None,
        age_min=round(min(ages), 1) if ages else None,
        age_max=round(max(ages), 1) if ages else None,
        sex_distribution=sex_dist,
    )


def _build_missingness_report(
    patient_ids: frozenset[str],
    dataset: NormalizedDataset,
    egfr_codes: frozenset[str],
) -> list[MissingnessReport]:
    total = len(patient_ids)
    if total == 0:
        return []

    pts_with_egfr = {obs.patient_id for obs in dataset.observations if obs.code in egfr_codes}
    pts_with_egfr &= patient_ids

    available = len(pts_with_egfr)
    missing = total - available
    pct = round(100.0 * available / total, 1)

    return [
        MissingnessReport(
            variable="eGFR (baseline)",
            available_count=available,
            missing_count=missing,
            total_count=total,
            availability_pct=pct,
        )
    ]


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


def _config_hash(config: CohortConfiguration) -> str:
    """Deterministic SHA-256 hash of the configuration, excluding dataset_id."""
    payload = json.dumps(
        {
            "reference_date": config.reference_date.isoformat(),
            "min_age_years": config.min_age_years,
            "observation_lookback_days": config.observation_lookback_days,
            "include_medication_exposure_filter": config.include_medication_exposure_filter,
            "medication_lookback_days": config.medication_lookback_days,
            "require_lab_availability": config.require_lab_availability,
            "lab_lookback_days": config.lab_lookback_days,
        },
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def run_cohort(
    phenotype: PhenotypeDefinition,
    config: CohortConfiguration,
    dataset: NormalizedDataset,
    fhir_run_id: str,
) -> CohortRun:
    """Execute the cohort pipeline and return a CohortRun.

    Gates:
    - Raises UnapprovedPhenotypeError if phenotype is not approved.
    - Raises UnresolvedConceptError if any required concept has no codes.
    - LLM-suggested-only concepts (c-sglt2) are executed only as optional exploratory steps.
    """
    _assert_approved(phenotype)
    llm_warnings = _assert_required_concepts_resolved(phenotype)

    run_id = str(uuid.uuid4())
    ref_date = config.reference_date
    steps: list[CohortStep] = []
    patient_sets: list[set[str]] = []

    # Build concept code lookup
    concept_map: dict[str, ClinicalConcept] = {c.concept_id: c for c in phenotype.concepts}

    # ------------------------------------------------------------------
    # Step 0 initializer (not a real attrition step; just sets current population)
    # ------------------------------------------------------------------
    all_ids = R.all_patient_ids(dataset)
    current = all_ids.ids
    step_n = 0

    def _add_step(
        label: str,
        description: str,
        records_in: int,
        new_current: frozenset[str],
        exclusion_reason: str | None = None,
    ) -> None:
        nonlocal step_n
        step_n += 1
        excluded_count = records_in - len(new_current)
        steps.append(
            CohortStep(
                step_number=step_n,
                label=label,
                description=description,
                records_in=records_in,
                records_excluded=excluded_count,
                records_out=len(new_current),
                exclusion_reason=exclusion_reason,
            )
        )
        patient_sets.append(set(new_current))

    # ------------------------------------------------------------------
    # Step 1: All synthetic patients
    # ------------------------------------------------------------------
    total = len(current)
    _add_step(
        "All synthetic patients",
        f"Starting population: all {total} patients in dataset '{config.dataset_id}'",
        total,
        current,
    )

    # ------------------------------------------------------------------
    # Step 2: Age >= min_age_years at reference date
    # ------------------------------------------------------------------
    prev = len(current)
    age_passing = R.patients_meeting_age(current, dataset, config.min_age_years, ref_date)
    current = age_passing.ids
    _add_step(
        f"Age >= {config.min_age_years} at reference date",
        f"Patients {config.min_age_years}+ years old at {ref_date}. "
        "Patients with missing birth date are excluded (conservative).",
        prev,
        current,
        exclusion_reason=f"Age < {config.min_age_years} or missing birth date",
    )

    # ------------------------------------------------------------------
    # Step 3: Sufficient observation history
    # ------------------------------------------------------------------
    prev = len(current)
    obs_passing = R.patients_with_observation_period(
        current, dataset, config.observation_lookback_days, ref_date
    )
    current = obs_passing.ids
    _add_step(
        f">= {config.observation_lookback_days}d observation history",
        f"Patients with earliest encounter >= {config.observation_lookback_days} days "
        f"before {ref_date}. Patients with no encounter dates are excluded.",
        prev,
        current,
        exclusion_reason=f"Insufficient observation history (< {config.observation_lookback_days} days)",
    )

    # ------------------------------------------------------------------
    # Step 4: Required inclusion rules (non-LLM-suggested, non-demographic concepts only)
    # Concepts with fhir_resource="Patient" (like c-age) are skipped here;
    # the age gate is already applied in step 2 via config.min_age_years.
    # Concepts where ALL mappings are LLM-suggested are also skipped (handled in step 6).
    # ------------------------------------------------------------------
    for rule in phenotype.inclusion_rules:
        if not rule.required:
            continue
        concept = concept_map.get(rule.concept_id)
        if concept is None or _all_llm_suggested(concept):
            continue
        if concept.fhir_resource not in ("Condition", "Observation"):
            continue  # Patient-demographic rules handled by config params; medication handled below

        codes = _codes_for_concept(concept, exclude_llm_suggested=False)
        if not codes:
            continue

        prev = len(current)
        if concept.fhir_resource == "Condition":
            passing = R.patients_with_condition(
                current, dataset, codes, ref_date, rule.lookback_days
            )
        else:
            passing = R.patients_with_observation(
                current, dataset, codes, rule.lookback_days, ref_date
            )

        current = passing.ids
        _add_step(
            rule.label,
            f"{rule.logic} [rule: {rule.rule_id}, concept: {rule.concept_id}]",
            prev,
            current,
            exclusion_reason=f"Does not meet inclusion criterion: {rule.label}",
        )

    # ------------------------------------------------------------------
    # Step 5: Required exclusion rules
    # ------------------------------------------------------------------
    for rule in phenotype.exclusion_rules:
        concept = concept_map.get(rule.concept_id)
        if concept is None:
            continue
        codes = _codes_for_concept(concept, exclude_llm_suggested=False)
        if not codes:
            continue
        if concept.fhir_resource != "Condition":
            continue

        excluded_group = R.patients_with_condition(current, dataset, codes, ref_date, None)
        prev = len(current)
        new_current = frozenset(current) - excluded_group.ids
        _add_step(
            f"Exclude: {rule.label}",
            f"Patients excluded by: {rule.logic} [rule: {rule.rule_id}]",
            prev,
            new_current,
            exclusion_reason=rule.label,
        )
        current = new_current

    # ------------------------------------------------------------------
    # Step 6 (optional): SGLT2 exploratory medication exposure filter.
    # Only when config.include_medication_exposure_filter=True.
    # Uses LLM-suggested, unverified RxNorm codes — classified "candidate exposure."
    # ------------------------------------------------------------------
    med_warning: str | None = None
    if config.include_medication_exposure_filter:
        sglt2_concept = concept_map.get("c-sglt2")
        if sglt2_concept:
            sglt2_codes = _codes_for_concept(sglt2_concept, exclude_llm_suggested=False)
            if sglt2_codes:
                med_warning = (
                    "PROVISIONAL MEDICATION FILTER: The SGLT2 exposure filter uses RxNorm "
                    "codes that are LLM-suggested and UNVERIFIED against the live RxNorm API. "
                    "Patients passing this step are classified as 'candidate exposure' -- "
                    "NOT confirmed SGLT2 users. Do not use for clinical decisions."
                )
                prev = len(current)
                med_passing = R.patients_with_medication(
                    current, dataset, sglt2_codes, config.medication_lookback_days, ref_date
                )
                current = med_passing.ids
                _add_step(
                    "EXPLORATORY: SGLT2 candidate exposure (UNVERIFIED CODES)",
                    "Optional exploratory filter: patients with >=1 MedicationRequest for an "
                    "LLM-suggested, unverified RxNorm SGLT2 inhibitor code. "
                    "NOT a confirmed inclusion criterion. Requires manual medication mapping review.",
                    prev,
                    current,
                    exclusion_reason="No SGLT2 candidate exposure found (provisional/unverified filter)",
                )

    # ------------------------------------------------------------------
    # Step 7 (optional): Lab availability
    # ------------------------------------------------------------------
    if config.require_lab_availability:
        egfr_concept = concept_map.get("c-egfr")
        if egfr_concept:
            egfr_codes = _codes_for_concept(egfr_concept, exclude_llm_suggested=False)
            if egfr_codes:
                prev = len(current)
                obs_passing = R.patients_with_observation(
                    current, dataset, egfr_codes, config.lab_lookback_days, ref_date
                )
                current = obs_passing.ids
                _add_step(
                    f"Lab availability: eGFR within {config.lab_lookback_days}d",
                    f"Patients with >=1 qualifying eGFR observation "
                    f"in the {config.lab_lookback_days}-day window before {ref_date}",
                    prev,
                    current,
                    exclusion_reason="No qualifying eGFR observation in lookback window",
                )

    # ------------------------------------------------------------------
    # Build outputs
    # ------------------------------------------------------------------
    attrition = CohortAttrition(steps=steps)

    final_ids = frozenset(current)
    egfr_codes_for_report: frozenset[str] = frozenset()
    egfr_c = concept_map.get("c-egfr")
    if egfr_c:
        egfr_codes_for_report = _codes_for_concept(egfr_c, exclude_llm_suggested=False)

    demographics = _build_demographic_summary(final_ids, dataset, ref_date)
    missingness = _build_missingness_report(final_ids, dataset, egfr_codes_for_report)

    qa_warnings = llm_warnings[:]
    if med_warning:
        qa_warnings.append(med_warning)

    # Count active medications and conditions in final cohort
    final_condition_codes: dict[str, int] = {}
    for cond in dataset.conditions:
        if cond.patient_id in final_ids:
            final_condition_codes[cond.code] = final_condition_codes.get(cond.code, 0) + 1

    final_med_codes: dict[str, int] = {}
    for med in dataset.medications:
        if med.patient_id in final_ids:
            final_med_codes[med.display or med.code] = (
                final_med_codes.get(med.display or med.code, 0) + 1
            )

    final_enc_types: dict[str, int] = {}
    for enc in dataset.encounters:
        if enc.patient_id in final_ids:
            k = enc.encounter_class or "unknown"
            final_enc_types[k] = final_enc_types.get(k, 0) + 1

    summary = CohortSummary(
        id=run_id,
        phenotype_id=phenotype.id,
        phenotype_version=phenotype.version,
        initial_population=len(all_ids),
        final_cohort_count=len(final_ids),
        attrition_steps=steps,
        demographic_summary=demographics,
        missingness_report=missingness,
        condition_prevalence={
            k: round(v / max(len(final_ids), 1), 4) for k, v in final_condition_codes.items()
        },
        medication_exposure=final_med_codes,
        encounter_summary=final_enc_types,
        data_source=(
            f"Bundled deterministic synthetic FHIR dataset '{config.dataset_id}' "
            "(seed=42, reference_date=2025-06-01). All patients are fictional."
        ),
        qa_warnings=qa_warnings,
        data_quality_status="warning" if qa_warnings else "passed",
    )

    provenance = CohortProvenance(
        run_id=run_id,
        phenotype_id=phenotype.id,
        phenotype_version=phenotype.version,
        phenotype_review_status=phenotype.review_status,
        dataset_id=config.dataset_id,
        fhir_ingestion_run_id=fhir_run_id,
        configuration_hash=_config_hash(config),
    )

    return CohortRun(
        run_id=run_id,
        configuration=config,
        attrition=attrition,
        summary=summary,
        provenance=provenance,
        qa_status="warning" if qa_warnings else "passed",
        warnings=qa_warnings,
    )
