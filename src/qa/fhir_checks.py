"""FHIR ingestion quality assurance checks.

Run after normalization to detect structural issues in the ingested dataset.
Returns a list of QAResult objects; does NOT raise on check failures.
Critical failures (severity="critical") indicate the dataset should not be used for analysis.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from src.fhir.normalizer import NormalizedDataset
from src.schemas.fhir import FHIRIngestionError
from src.schemas.qa import QAResult, QASummary


def _qa(
    check_id: str,
    check_name: str,
    status: Literal["passed", "warning", "failed", "not_applicable"],
    description: str,
    severity: Literal["critical", "major", "minor", "info"],
    details: str | None = None,
    affected: list[str] | None = None,
) -> QAResult:
    return QAResult(
        check_id=check_id,
        check_name=check_name,
        category="data_quality",
        status=status,
        description=description,
        severity=severity,
        details=details,
        affected_records=affected or [],
    )


def run_fhir_checks(
    dataset: NormalizedDataset,
    errors: list[FHIRIngestionError],
    run_id: str,
) -> QASummary:
    """Run all FHIR QA checks and return a QASummary."""
    results: list[QAResult] = []
    patient_ids = dataset.patient_ids

    # ------------------------------------------------------------------
    # Check 1: zero starting population
    # ------------------------------------------------------------------
    if not dataset.patients:
        results.append(
            _qa(
                "fhir-001",
                "Non-empty patient population",
                "failed",
                "At least one Patient resource must be present",
                "critical",
                details="No Patient resources found after ingestion",
            )
        )
    else:
        results.append(
            _qa(
                "fhir-001",
                "Non-empty patient population",
                "passed",
                "At least one Patient resource must be present",
                "info",
                details=f"{len(dataset.patients)} patients ingested",
            )
        )

    # ------------------------------------------------------------------
    # Check 2: fatal ingestion errors
    # ------------------------------------------------------------------
    fatal_errors = [e for e in errors if e.is_fatal]
    if fatal_errors:
        results.append(
            _qa(
                "fhir-002",
                "No fatal ingestion errors",
                "warning",
                "FHIR resources with fatal ingestion errors were dropped",
                "major",
                details=f"{len(fatal_errors)} resources dropped due to fatal errors",
                affected=[e.resource_id or e.file_name or "" for e in fatal_errors],
            )
        )
    else:
        results.append(
            _qa(
                "fhir-002",
                "No fatal ingestion errors",
                "passed",
                "FHIR resources with fatal ingestion errors were dropped",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # Check 3: orphaned condition references
    # ------------------------------------------------------------------
    orphaned_conditions = [
        c.condition_id for c in dataset.conditions if c.patient_id not in patient_ids
    ]
    if orphaned_conditions:
        results.append(
            _qa(
                "fhir-003",
                "No orphaned Condition references",
                "warning",
                "Conditions must reference a Patient present in the dataset",
                "major",
                details=f"{len(orphaned_conditions)} conditions reference unknown patients",
                affected=orphaned_conditions,
            )
        )
    else:
        results.append(
            _qa(
                "fhir-003",
                "No orphaned Condition references",
                "passed",
                "Conditions must reference a Patient present in the dataset",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # Check 4: orphaned encounter references
    # ------------------------------------------------------------------
    orphaned_encs = [e.encounter_id for e in dataset.encounters if e.patient_id not in patient_ids]
    if orphaned_encs:
        results.append(
            _qa(
                "fhir-004",
                "No orphaned Encounter references",
                "warning",
                "Encounters must reference a Patient present in the dataset",
                "major",
                affected=orphaned_encs,
            )
        )
    else:
        results.append(
            _qa(
                "fhir-004",
                "No orphaned Encounter references",
                "passed",
                "Encounters must reference a Patient present in the dataset",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # Check 5: impossible encounter dates (end before start)
    # ------------------------------------------------------------------
    bad_enc_dates = [
        e.encounter_id
        for e in dataset.encounters
        if e.start_date and e.end_date and e.end_date < e.start_date
    ]
    if bad_enc_dates:
        results.append(
            _qa(
                "fhir-005",
                "Valid encounter date order",
                "warning",
                "Encounter end date must not precede start date",
                "major",
                details=f"{len(bad_enc_dates)} encounters have end < start",
                affected=bad_enc_dates,
            )
        )
    else:
        results.append(
            _qa(
                "fhir-005",
                "Valid encounter date order",
                "passed",
                "Encounter end date must not precede start date",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # Check 6: missing birth dates
    # ------------------------------------------------------------------
    missing_birth = [p.patient_id for p in dataset.patients if p.birth_date is None]
    if missing_birth:
        results.append(
            _qa(
                "fhir-006",
                "Birth dates present",
                "warning",
                "Patients without birth dates cannot have age calculated",
                "minor",
                details=f"{len(missing_birth)} patients have no birthDate",
                affected=missing_birth,
            )
        )
    else:
        results.append(
            _qa(
                "fhir-006",
                "Birth dates present",
                "passed",
                "Patients without birth dates cannot have age calculated",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # Check 7: impossible birth dates (birth date after earliest encounter)
    # ------------------------------------------------------------------
    earliest_enc: dict[str, date] = {}
    for enc in dataset.encounters:
        if enc.start_date:
            prev = earliest_enc.get(enc.patient_id)
            if prev is None or enc.start_date < prev:
                earliest_enc[enc.patient_id] = enc.start_date

    impossible_birth = [
        p.patient_id
        for p in dataset.patients
        if p.birth_date
        and p.patient_id in earliest_enc
        and p.birth_date > earliest_enc[p.patient_id]
    ]
    if impossible_birth:
        results.append(
            _qa(
                "fhir-007",
                "Plausible birth dates",
                "warning",
                "Birth date must not be after the earliest encounter date",
                "major",
                details=f"{len(impossible_birth)} patients have birth date after first encounter",
                affected=impossible_birth,
            )
        )
    else:
        results.append(
            _qa(
                "fhir-007",
                "Plausible birth dates",
                "passed",
                "Birth date must not be after the earliest encounter date",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # Check 8: observations missing value and unit
    # ------------------------------------------------------------------
    missing_value_obs = [
        o.observation_id
        for o in dataset.observations
        if o.value_numeric is None and o.value_text is None
    ]
    if missing_value_obs:
        results.append(
            _qa(
                "fhir-008",
                "Observations have values",
                "warning",
                "Observations should have either a numeric or text value",
                "minor",
                details=f"{len(missing_value_obs)} observations have no value",
                affected=missing_value_obs,
            )
        )
    else:
        results.append(
            _qa(
                "fhir-008",
                "Observations have values",
                "passed",
                "Observations should have either a numeric or text value",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # Check 9: medication end before start
    # ------------------------------------------------------------------
    bad_med_dates = [
        m.medication_record_id
        for m in dataset.medications
        if m.start_date and m.end_date and m.end_date < m.start_date
    ]
    if bad_med_dates:
        results.append(
            _qa(
                "fhir-009",
                "Valid medication date order",
                "warning",
                "Medication end date must not precede start date",
                "minor",
                details=f"{len(bad_med_dates)} medications have end < start",
                affected=bad_med_dates,
            )
        )
    else:
        results.append(
            _qa(
                "fhir-009",
                "Valid medication date order",
                "passed",
                "Medication end date must not precede start date",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # Check 10: patients with no encounters (incomplete history)
    # ------------------------------------------------------------------
    patients_with_enc = {e.patient_id for e in dataset.encounters}
    no_encounter = [p.patient_id for p in dataset.patients if p.patient_id not in patients_with_enc]
    if no_encounter:
        results.append(
            _qa(
                "fhir-010",
                "All patients have encounters",
                "warning",
                "Patients with no encounters cannot satisfy observation-period requirements",
                "minor",
                details=f"{len(no_encounter)} patients have zero encounter records",
                affected=no_encounter,
            )
        )
    else:
        results.append(
            _qa(
                "fhir-010",
                "All patients have encounters",
                "passed",
                "Patients with no encounters cannot satisfy observation-period requirements",
                "info",
            )
        )

    return QASummary(run_id=run_id, results=results)
