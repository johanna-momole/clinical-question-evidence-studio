"""Schemas for question parsing results, provenance, and phenotype audit trail."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

# Import at runtime (no circular dependency — question/phenotype do not import parsing)
from src.schemas.phenotype import PhenotypeDefinition  # noqa: TCH001
from src.schemas.question import ClinicalQuestion  # noqa: TCH001


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ParseProvenance(BaseModel):
    """Records how a clinical question was parsed so results are reproducible."""

    parser_name: str = Field(..., description="Parser class name (e.g., 'DemoQuestionParser')")
    parser_version: str = Field("0.1.0")
    is_demo_mode: bool = Field(..., description="True when no live LLM was used")
    model_id: str | None = Field(None, description="LLM model ID if live mode; None in demo mode")
    prompt_version: str | None = Field(None, description="Prompt template version tag")
    parse_timestamp: datetime = Field(default_factory=_utcnow)
    warnings: list[str] = Field(default_factory=list)


class ParseResult(BaseModel):
    """Full result of parsing a clinical question, including provenance."""

    run_id: str = Field(..., description="Stable UUID for this parsing run")
    question: ClinicalQuestion
    provenance: ParseProvenance
    is_supported_question: bool = Field(
        ...,
        description="True if the question matched one of the curated demo questions",
    )
    curated_question_id: str | None = Field(
        None, description="ID of the matching curated question; None for unsupported questions"
    )
    warnings: list[str] = Field(default_factory=list)


class PhenotypeAuditRecord(BaseModel):
    """One entry in the audit trail when a phenotype is edited during UI review."""

    audit_id: str
    phenotype_id: str
    phenotype_version: str
    timestamp: datetime = Field(default_factory=_utcnow)
    field_path: str = Field(..., description="Dot-path of the field that was changed")
    previous_value_json: str | None = Field(
        None, description="JSON representation of the previous value"
    )
    new_value_json: str | None = Field(None, description="JSON representation of the new value")
    change_type: Literal["mapping_review", "rule_edit", "note_added", "status_change", "restore"]
    changed_by: Literal["user", "system"]
    notes: str | None = None


class PhenotypeResult(BaseModel):
    """Result of building a phenotype from an approved clinical question."""

    run_id: str
    phenotype: PhenotypeDefinition | None = Field(
        None,
        description="Loaded phenotype definition; None when the question is unsupported",
    )
    is_available: bool = Field(..., description="True when a phenotype was found for this question")
    unavailable_reason: str | None = Field(None, description="Explanation when is_available=False")
    warnings: list[str] = Field(default_factory=list)
    audit_trail: list[PhenotypeAuditRecord] = Field(default_factory=list)
