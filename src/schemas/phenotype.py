"""Pydantic schemas for version-controlled computable phenotype definitions."""

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TerminologyMapping(BaseModel):
    """A candidate code mapping from a clinical concept to a standard terminology system.

    LLM-suggested mappings (is_llm_suggested=True) must be labeled as candidate mappings
    and require human review before use in a production phenotype.
    """

    concept_id: str = Field(..., description="Parent concept this mapping belongs to")
    concept_name: str = Field(..., description="Human-readable concept name")
    terminology_system: Literal["ICD-10-CM", "RxNorm", "LOINC", "SNOMED-CT", "CPT"] = Field(
        ..., description="Standard terminology system"
    )
    code: str = Field(..., description="Standard code within the terminology system")
    description: str = Field(..., description="Official code description from the terminology")
    terminology_version: str | None = Field(
        None, description="Terminology version or fiscal year (e.g., 'FY2024')"
    )
    source_or_rationale: str = Field(
        ..., description="Clinical rationale or source reference for this mapping"
    )
    review_status: Literal["candidate", "approved", "rejected"] = Field(
        "candidate",
        description="Human review status; all LLM-suggested mappings start as 'candidate'",
    )
    confidence: Literal["high", "medium", "low"] = Field(
        ..., description="Mapping confidence based on specificity and clinical evidence"
    )
    is_llm_suggested: bool = Field(
        False,
        description="True if an LLM suggested this mapping — requires explicit human review",
    )
    verification_date: date | None = Field(
        None,
        description="Date the code was verified against an authoritative source; None means verification is pending",
    )
    verification_source: str | None = Field(
        None,
        description="Authoritative source used for verification (e.g., 'RxNorm API', 'ICD-10-CM Tabular FY2024')",
    )
    notes: str | None = Field(None, description="Reviewer notes or caveats")


class ClinicalConcept(BaseModel):
    """A clinical concept with its candidate terminology mappings and FHIR resource context."""

    concept_id: str = Field(..., description="Unique concept identifier within this phenotype")
    name: str = Field(..., description="Concept name (e.g., 'Type 2 Diabetes Diagnosis')")
    clinical_intent: str = Field(
        ..., description="Role of this concept in the phenotype (e.g., index condition)"
    )
    mappings: list[TerminologyMapping] = Field(
        default_factory=list, description="Candidate terminology mappings for this concept"
    )
    fhir_resource: str = Field(
        ..., description="Primary FHIR resource type (e.g., 'Condition', 'MedicationRequest')"
    )
    notes: str | None = None


class PhenotypeRule(BaseModel):
    """A single inclusion or exclusion criterion in a computable phenotype definition."""

    rule_id: str = Field(..., description="Unique rule identifier within this phenotype")
    rule_type: Literal["inclusion", "exclusion"] = Field(
        ..., description="Whether this rule includes or excludes patients"
    )
    concept_id: str = Field(..., description="Associated ClinicalConcept identifier")
    label: str = Field(..., description="Short human-readable rule label")
    logic: str = Field(..., description="Plain-language description of the rule logic")
    lookback_days: int | None = Field(
        None,
        description="Lookback window in days before index date; None means no temporal restriction",
    )
    temporal_relationship: str | None = Field(
        None,
        description="Temporal relationship to index date (e.g., 'before_index', 'on_or_after_index')",
    )
    required: bool = Field(
        True, description="Whether this rule is mandatory (vs. a contributing criterion)"
    )


class FHIRResourceMapping(BaseModel):
    """Maps a phenotype concept to its FHIR resource structure for implementation."""

    resource_type: str = Field(
        ..., description="FHIR resource type (e.g., 'Condition', 'MedicationRequest')"
    )
    element_path: str = Field(..., description="FHIR element path (e.g., 'code.coding.code')")
    terminology_system_url: str | None = Field(
        None,
        description="FHIR system URL (e.g., 'http://hl7.org/fhir/sid/icd-10-cm')",
    )
    value: str | None = Field(
        None, description="Expected value or code prefix to match (e.g., 'E11')"
    )
    concept_id: str = Field(..., description="Associated phenotype concept identifier")
    notes: str | None = None


class PhenotypeDefinition(BaseModel):
    """Complete version-controlled computable phenotype definition.

    This is the serializable, versionable artifact that drives cohort construction.
    Changes to inclusion/exclusion logic must increment the version.
    """

    id: str = Field(..., description="Unique phenotype identifier")
    version: str = Field(..., description="Semantic version string (e.g., '0.1.0')")
    name: str = Field(..., description="Phenotype name")
    description: str = Field(..., description="Plain-language phenotype description")
    clinical_intent: str = Field(
        ..., description="Study purpose this phenotype serves (e.g., observational cohort)"
    )
    question_id: str = Field(..., description="Associated ClinicalQuestion ID")
    concepts: list[ClinicalConcept] = Field(
        default_factory=list, description="Clinical concepts used in this phenotype"
    )
    inclusion_rules: list[PhenotypeRule] = Field(
        default_factory=list, description="Criteria that qualify patients for the cohort"
    )
    exclusion_rules: list[PhenotypeRule] = Field(
        default_factory=list, description="Criteria that remove patients from the cohort"
    )
    fhir_mappings: list[FHIRResourceMapping] = Field(
        default_factory=list, description="FHIR resource mappings for implementation"
    )
    lookback_period_days: int = Field(
        ..., ge=0, description="Minimum required lookback window in days (e.g., 365)"
    )
    index_date_definition: str = Field(
        ...,
        description="Definition of the study index date (e.g., 'date of first qualifying SGLT2 prescription')",
    )
    review_status: Literal["draft", "under_review", "approved"] = Field(
        "draft", description="Phenotype review lifecycle status"
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    changelog: list[str] = Field(
        default_factory=list, description="Version history entries in descending order"
    )
