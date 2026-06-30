"""Phase 3 FHIR loading, parsing, and normalization tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.fhir.loader import load_directory, load_file
from src.fhir.normalizer import normalize
from src.fhir.parser import (
    parse_condition,
    parse_medication_request,
    parse_observation,
    parse_patient,
)

_FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "fixtures"
    / "fhir"
    / "synthetic_cohort_v1"
)
_EDGE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "fhir_edge_cases"


class TestFHIRLoader:
    def test_load_directory_returns_resources(self) -> None:
        if not _FIXTURE_DIR.exists():
            pytest.skip("Synthetic FHIR fixtures not generated yet")
        result = load_directory(_FIXTURE_DIR)
        assert len(result.resources) > 0

    def test_load_directory_deduplicates_across_files(self) -> None:
        if not _FIXTURE_DIR.exists():
            pytest.skip("Synthetic FHIR fixtures not generated yet")
        result = load_directory(_FIXTURE_DIR)
        ids_seen = [r.resource.get("id") for r in result.resources if r.resource.get("id")]
        assert len(ids_seen) == len(set(ids_seen)), "Duplicate resource IDs found across files"

    def test_load_directory_skips_dataset_info(self) -> None:
        if not _FIXTURE_DIR.exists():
            pytest.skip("Synthetic FHIR fixtures not generated yet")
        result = load_directory(_FIXTURE_DIR)
        for r in result.resources:
            assert r.resource.get("resourceType") != "DatasetInfo", (
                "dataset_info.json should be skipped"
            )

    def test_load_malformed_json_produces_error(self) -> None:
        malformed = _EDGE_DIR / "malformed.json"
        if not malformed.exists():
            pytest.skip("Edge case fixtures not present")
        result = load_file(malformed)
        assert len(result.errors) == 1
        assert result.errors[0].error_type == "malformed_json"

    def test_load_missing_resource_id_produces_error(self) -> None:
        missing_id = _EDGE_DIR / "missing_id.json"
        if not missing_id.exists():
            pytest.skip("Edge case fixtures not present")
        result = load_file(missing_id)
        assert any(e.error_type == "missing_resource_id" for e in result.errors)

    def test_load_unsupported_type_produces_error(self) -> None:
        unsupported = _EDGE_DIR / "unsupported_type.json"
        if not unsupported.exists():
            pytest.skip("Edge case fixtures not present")
        result = load_file(unsupported)
        assert any(e.error_type == "unsupported_resource_type" for e in result.errors)

    def test_load_duplicate_ids_across_files_deduped(self) -> None:
        dup_a = _EDGE_DIR / "duplicate_a.json"
        dup_b = _EDGE_DIR / "duplicate_b.json"
        if not (dup_a.exists() and dup_b.exists()):
            pytest.skip("Edge case fixtures not present")
        result_a = load_file(dup_a)
        result_b = load_file(dup_b)
        from src.fhir.loader import LoadResult

        combined = LoadResult()
        for r in result_a.resources:
            combined.add_resource(r)
        for r in result_b.resources:
            combined.add_resource(r)
        resource_ids = [r.resource.get("id") for r in combined.resources if r.resource.get("id")]
        assert len(resource_ids) == len(set(resource_ids))
        assert any(e.error_type == "duplicate_resource_id" for e in combined.errors)


class TestFHIRParser:
    def test_parse_patient_minimal(self) -> None:
        resource = {
            "resourceType": "Patient",
            "id": "pt-001",
            "gender": "male",
            "birthDate": "1960-03-15",
        }
        result = parse_patient(resource)
        assert result.patient_id == "pt-001"
        assert result.sex == "male"
        assert result.birth_date == date(1960, 3, 15)

    def test_parse_patient_missing_birthdate(self) -> None:
        resource = {"resourceType": "Patient", "id": "pt-002", "gender": "female"}
        result = parse_patient(resource)
        assert result.birth_date is None

    def test_parse_condition_returns_patient_id(self) -> None:
        resource = {
            "resourceType": "Condition",
            "id": "cond-001",
            "subject": {"reference": "Patient/pt-001"},
            "code": {"coding": [{"code": "E11.9", "system": "http://hl7.org/fhir/sid/icd-10-cm"}]},
            "clinicalStatus": {"coding": [{"code": "active"}]},
        }
        result = parse_condition(resource)
        assert result is not None
        assert result.patient_id == "pt-001"
        assert result.code == "E11.9"

    def test_parse_condition_no_patient_reference_returns_none(self) -> None:
        resource = {
            "resourceType": "Condition",
            "id": "cond-002",
            "code": {"coding": [{"code": "E11.9"}]},
        }
        result = parse_condition(resource)
        assert result is None

    def test_parse_observation_numeric_value(self) -> None:
        resource = {
            "resourceType": "Observation",
            "id": "obs-001",
            "subject": {"reference": "Patient/pt-001"},
            "code": {"coding": [{"code": "62238-1", "system": "http://loinc.org"}]},
            "status": "final",
            "effectiveDateTime": "2024-01-15",
            "valueQuantity": {"value": 52.3, "unit": "mL/min/1.73m2"},
        }
        result = parse_observation(resource)
        assert result is not None
        assert result.value_numeric == pytest.approx(52.3)
        assert result.unit == "mL/min/1.73m2"

    def test_parse_medication_request_returns_patient_id(self) -> None:
        resource = {
            "resourceType": "MedicationRequest",
            "id": "med-001",
            "subject": {"reference": "Patient/pt-001"},
            "status": "active",
            "medicationCodeableConcept": {
                "coding": [
                    {"code": "1545653", "system": "http://www.nlm.nih.gov/research/umls/rxnorm"}
                ]
            },
        }
        result = parse_medication_request(resource)
        assert result is not None
        assert result.patient_id == "pt-001"
        assert result.code == "1545653"


class TestFHIRNormalizer:
    def test_normalize_full_dataset(self) -> None:
        if not _FIXTURE_DIR.exists():
            pytest.skip("Synthetic FHIR fixtures not generated yet")
        load_result = load_directory(_FIXTURE_DIR)
        dataset = normalize(load_result.resources)
        assert len(dataset.patients) == 160
        assert len(dataset.conditions) > 0
        assert len(dataset.encounters) > 0
        assert len(dataset.medications) > 0
        assert len(dataset.observations) > 0

    def test_normalize_patient_ids_are_unique(self) -> None:
        if not _FIXTURE_DIR.exists():
            pytest.skip("Synthetic FHIR fixtures not generated yet")
        load_result = load_directory(_FIXTURE_DIR)
        dataset = normalize(load_result.resources)
        ids = [p.patient_id for p in dataset.patients]
        assert len(ids) == len(set(ids))

    def test_patient_ids_property(self) -> None:
        if not _FIXTURE_DIR.exists():
            pytest.skip("Synthetic FHIR fixtures not generated yet")
        load_result = load_directory(_FIXTURE_DIR)
        dataset = normalize(load_result.resources)
        assert isinstance(dataset.patient_ids, frozenset)
        assert len(dataset.patient_ids) == len(dataset.patients)
