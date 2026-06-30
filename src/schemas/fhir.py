"""Pydantic schemas for synthetic FHIR R4 ingestion and normalization.

All resources processed by this module are SYNTHETIC — either bundled deterministic
fixtures or Synthea-generated data. No real patient data is supported or implied.
"""

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Normalized analytical models
# ---------------------------------------------------------------------------


class NormalizedPatient(BaseModel):
    """Patient resource normalized to a flat analytical row."""

    patient_id: str = Field(..., description="Source FHIR Patient resource ID")
    birth_date: date | None = Field(None, description="Date of birth; None if not represented")
    sex: Literal["male", "female", "other", "unknown"] = Field(
        "unknown", description="FHIR administrative gender"
    )
    race: str | None = Field(None, description="US Core race extension display, if present")
    ethnicity: str | None = Field(
        None, description="US Core ethnicity extension display, if present"
    )
    deceased: bool = Field(False, description="True if deceasedBoolean/deceasedDateTime present")
    deceased_date: date | None = None
    source_resource_id: str = Field(..., description="Original FHIR resource.id")


class NormalizedCondition(BaseModel):
    """Condition resource normalized to a flat analytical row."""

    patient_id: str
    condition_id: str = Field(..., description="Source FHIR Condition resource ID")
    code: str = Field(..., description="Condition code value")
    code_system: str = Field(..., description="Code system URI or short name")
    display: str | None = Field(None, description="Human-readable code display")
    onset_date: date | None = Field(None, description="Clinical onset date; None if unknown")
    recorded_date: date | None = Field(None, description="Date condition was recorded")
    clinical_status: str | None = Field(None, description="active | resolved | inactive | ...")
    verification_status: str | None = Field(None, description="confirmed | provisional | ...")
    source_resource_id: str


class NormalizedEncounter(BaseModel):
    """Encounter resource normalized to a flat analytical row."""

    patient_id: str
    encounter_id: str = Field(..., description="Source FHIR Encounter resource ID")
    encounter_class: str | None = Field(None, description="Encounter.class code (e.g., AMB, IMP)")
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None
    source_resource_id: str


class ReferenceRange(BaseModel):
    """Optional reference range for a normalized observation."""

    low: float | None = None
    high: float | None = None
    unit: str | None = None


class NormalizedObservation(BaseModel):
    """Observation resource normalized to a flat analytical row."""

    patient_id: str
    observation_id: str = Field(..., description="Source FHIR Observation resource ID")
    code: str
    code_system: str
    display: str | None = None
    value_numeric: float | None = Field(None, description="Numeric value, if valueQuantity")
    value_text: str | None = Field(None, description="Text/coded value, if not numeric")
    unit: str | None = None
    effective_date: date | None = None
    status: str | None = None
    reference_range: ReferenceRange | None = None
    source_resource_id: str


class NormalizedMedication(BaseModel):
    """MedicationRequest/MedicationStatement normalized to a shared analytical row."""

    patient_id: str
    medication_record_id: str = Field(..., description="Source FHIR resource ID")
    code: str
    code_system: str
    display: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None
    source_resource_type: Literal["MedicationRequest", "MedicationStatement"]
    source_resource_id: str


class NormalizedProcedure(BaseModel):
    """Procedure resource normalized to a flat analytical row, if present in a dataset."""

    patient_id: str
    procedure_id: str = Field(..., description="Source FHIR Procedure resource ID")
    code: str
    code_system: str
    display: str | None = None
    performed_date: date | None = None
    status: str | None = None
    source_resource_id: str


# ---------------------------------------------------------------------------
# Ingestion request / result models
# ---------------------------------------------------------------------------


class FHIRIngestionError(BaseModel):
    """A single ingestion-time error or warning captured during FHIR loading."""

    file_name: str | None = Field(None, description="Originating file name, not a full path")
    resource_id: str | None = None
    resource_type: str | None = None
    error_type: Literal[
        "malformed_json",
        "missing_resource_id",
        "missing_patient_reference",
        "duplicate_resource_id",
        "unsupported_resource_type",
        "invalid_date",
        "orphaned_reference",
        "other",
    ]
    message: str
    is_fatal: bool = Field(
        False, description="True if this error caused the resource to be dropped"
    )


class FHIRResourceSummary(BaseModel):
    """Count of a single FHIR resource type ingested in a run."""

    resource_type: str
    count: int = Field(..., ge=0)


class FHIRIngestionRequest(BaseModel):
    """Request to ingest a named synthetic FHIR dataset."""

    dataset_id: str = Field(..., description="Identifier of a bundled synthetic dataset")
    force_reload: bool = Field(
        False, description="If True, re-ingest even if already loaded for this dataset_id"
    )


class FHIRIngestionResult(BaseModel):
    """Outcome of ingesting a synthetic FHIR dataset into normalized storage."""

    run_id: str
    dataset_id: str
    ingestion_timestamp: datetime = Field(default_factory=_utcnow)
    resource_counts: list[FHIRResourceSummary] = Field(default_factory=list)
    patient_count: int = Field(..., ge=0)
    warnings: list[str] = Field(default_factory=list)
    errors: list[FHIRIngestionError] = Field(default_factory=list)
    is_synthetic: Literal[True] = True


# ---------------------------------------------------------------------------
# Dataset catalog
# ---------------------------------------------------------------------------


class SyntheticDatasetInfo(BaseModel):
    """Metadata describing an available bundled synthetic FHIR dataset."""

    dataset_id: str
    name: str
    description: str
    patient_count: int = Field(..., ge=0)
    source: Literal["bundled_deterministic", "synthea_import"] = "bundled_deterministic"
    is_synthetic: Literal[True] = True
