"""Phase 3 FHIR QA check tests."""

from __future__ import annotations

from datetime import date

from src.fhir.normalizer import NormalizedDataset
from src.qa.fhir_checks import run_fhir_checks
from src.schemas.fhir import (
    NormalizedCondition,
    NormalizedEncounter,
    NormalizedPatient,
)


def _empty_dataset() -> NormalizedDataset:
    return NormalizedDataset()


class TestFHIRChecks:
    def test_empty_population_fails_critical(self) -> None:
        qa = run_fhir_checks(_empty_dataset(), errors=[], run_id="r1")
        check = next(r for r in qa.results if r.check_id == "fhir-001")
        assert check.status == "failed"
        assert check.severity == "critical"
        assert qa.has_critical_failure is True

    def test_non_empty_population_passes(self) -> None:
        dataset = _empty_dataset()
        dataset.patients.append(
            NormalizedPatient(
                patient_id="p1", birth_date=date(1960, 1, 1), sex="male", source_resource_id="p1"
            )
        )
        qa = run_fhir_checks(dataset, errors=[], run_id="r1")
        check = next(r for r in qa.results if r.check_id == "fhir-001")
        assert check.status == "passed"

    def test_orphaned_condition_detected(self) -> None:
        dataset = _empty_dataset()
        dataset.patients.append(
            NormalizedPatient(patient_id="p1", sex="male", source_resource_id="p1")
        )
        dataset.conditions.append(
            NormalizedCondition(
                patient_id="p-unknown",
                condition_id="c1",
                code="E11.9",
                code_system="icd10",
                source_resource_id="c1",
            )
        )
        qa = run_fhir_checks(dataset, errors=[], run_id="r1")
        check = next(r for r in qa.results if r.check_id == "fhir-003")
        assert check.status == "warning"
        assert "c1" in check.affected_records

    def test_no_orphaned_condition_passes(self) -> None:
        dataset = _empty_dataset()
        dataset.patients.append(
            NormalizedPatient(patient_id="p1", sex="male", source_resource_id="p1")
        )
        dataset.conditions.append(
            NormalizedCondition(
                patient_id="p1",
                condition_id="c1",
                code="E11.9",
                code_system="icd10",
                source_resource_id="c1",
            )
        )
        qa = run_fhir_checks(dataset, errors=[], run_id="r1")
        check = next(r for r in qa.results if r.check_id == "fhir-003")
        assert check.status == "passed"

    def test_invalid_encounter_dates_detected(self) -> None:
        dataset = _empty_dataset()
        dataset.patients.append(
            NormalizedPatient(patient_id="p1", sex="male", source_resource_id="p1")
        )
        dataset.encounters.append(
            NormalizedEncounter(
                patient_id="p1",
                encounter_id="e1",
                start_date=date(2024, 6, 1),
                end_date=date(2024, 1, 1),
                source_resource_id="e1",
            )
        )
        qa = run_fhir_checks(dataset, errors=[], run_id="r1")
        check = next(r for r in qa.results if r.check_id == "fhir-005")
        assert check.status == "warning"

    def test_missing_birth_dates_flagged_minor(self) -> None:
        dataset = _empty_dataset()
        dataset.patients.append(
            NormalizedPatient(patient_id="p1", sex="male", source_resource_id="p1")
        )
        qa = run_fhir_checks(dataset, errors=[], run_id="r1")
        check = next(r for r in qa.results if r.check_id == "fhir-006")
        assert check.status == "warning"
        assert check.severity == "minor"

    def test_implausible_birth_date_detected(self) -> None:
        dataset = _empty_dataset()
        dataset.patients.append(
            NormalizedPatient(
                patient_id="p1", birth_date=date(2025, 1, 1), sex="male", source_resource_id="p1"
            )
        )
        dataset.encounters.append(
            NormalizedEncounter(
                patient_id="p1",
                encounter_id="e1",
                start_date=date(2020, 1, 1),
                source_resource_id="e1",
            )
        )
        qa = run_fhir_checks(dataset, errors=[], run_id="r1")
        check = next(r for r in qa.results if r.check_id == "fhir-007")
        assert check.status == "warning"

    def test_patients_without_encounters_flagged(self) -> None:
        dataset = _empty_dataset()
        dataset.patients.append(
            NormalizedPatient(patient_id="p1", sex="male", source_resource_id="p1")
        )
        qa = run_fhir_checks(dataset, errors=[], run_id="r1")
        check = next(r for r in qa.results if r.check_id == "fhir-010")
        assert check.status == "warning"

    def test_qa_summary_run_id_propagated(self) -> None:
        qa = run_fhir_checks(_empty_dataset(), errors=[], run_id="my-run-id")
        assert qa.run_id == "my-run-id"
