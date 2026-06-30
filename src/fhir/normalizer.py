"""Orchestrate parsing of raw LoadedResource objects into normalized model instances.

Returns per-type lists and collects parse warnings without raising on individual
resource failures — every resource is attempted.
"""

from __future__ import annotations

from src.fhir import parser as p
from src.fhir.loader import LoadedResource
from src.schemas.fhir import (
    FHIRIngestionError,
    NormalizedCondition,
    NormalizedEncounter,
    NormalizedMedication,
    NormalizedObservation,
    NormalizedPatient,
    NormalizedProcedure,
)


class NormalizedDataset:
    """All normalized resources extracted from a single ingestion run."""

    def __init__(self) -> None:
        self.patients: list[NormalizedPatient] = []
        self.conditions: list[NormalizedCondition] = []
        self.encounters: list[NormalizedEncounter] = []
        self.observations: list[NormalizedObservation] = []
        self.medications: list[NormalizedMedication] = []
        self.procedures: list[NormalizedProcedure] = []
        self.warnings: list[FHIRIngestionError] = []

    @property
    def patient_ids(self) -> frozenset[str]:
        return frozenset(p.patient_id for p in self.patients)

    def resource_type_counts(self) -> dict[str, int]:
        return {
            "Patient": len(self.patients),
            "Condition": len(self.conditions),
            "Encounter": len(self.encounters),
            "Observation": len(self.observations),
            "Medication": len(self.medications),
            "Procedure": len(self.procedures),
        }


_DISPATCH = {
    "Patient": p.parse_patient,
    "Condition": p.parse_condition,
    "Encounter": p.parse_encounter,
    "Observation": p.parse_observation,
    "MedicationRequest": p.parse_medication_request,
    "MedicationStatement": p.parse_medication_statement,
    "Procedure": p.parse_procedure,
}


def normalize(resources: list[LoadedResource]) -> NormalizedDataset:
    """Parse all loaded resources into a NormalizedDataset."""
    ds = NormalizedDataset()

    for lr in resources:
        fn = _DISPATCH.get(lr.resource_type)
        if fn is None:
            continue  # loader already captured unsupported-type errors

        try:
            result = fn(lr.resource)
        except Exception as exc:
            ds.warnings.append(
                FHIRIngestionError(
                    file_name=lr.source_file,
                    resource_id=lr.resource_id,
                    resource_type=lr.resource_type,
                    error_type="other",
                    message=f"Parser raised unexpected error: {exc}",
                    is_fatal=False,
                )
            )
            continue

        if result is None:
            ds.warnings.append(
                FHIRIngestionError(
                    file_name=lr.source_file,
                    resource_id=lr.resource_id,
                    resource_type=lr.resource_type,
                    error_type="missing_patient_reference",
                    message=f"{lr.resource_type}/{lr.resource_id} has no resolvable patient reference; skipped",
                    is_fatal=True,
                )
            )
            continue

        if isinstance(result, NormalizedPatient):
            ds.patients.append(result)
        elif isinstance(result, NormalizedCondition):
            ds.conditions.append(result)
        elif isinstance(result, NormalizedEncounter):
            ds.encounters.append(result)
        elif isinstance(result, NormalizedObservation):
            ds.observations.append(result)
        elif isinstance(result, NormalizedMedication):
            ds.medications.append(result)
        elif isinstance(result, NormalizedProcedure):
            ds.procedures.append(result)

    return ds
