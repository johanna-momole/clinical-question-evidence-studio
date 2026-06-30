"""Pydantic schemas for clinical question intake and PICO framework representation."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AmbiguityFlag(BaseModel):
    """Identifies a specific ambiguity in a clinical question that requires human resolution."""

    field: str = Field(..., description="PICO field affected (e.g., 'comparator', 'timeframe')")
    description: str = Field(..., description="Plain-language description of the ambiguity")
    suggested_clarification: str = Field(
        ..., description="Recommended approach to resolve this ambiguity before study design"
    )
    severity: Literal["low", "medium", "high"] = Field(
        ..., description="Impact severity on study validity if left unresolved"
    )


class PICOFramework(BaseModel):
    """PICO (Population, Intervention, Comparator, Outcome) structured representation."""

    population: str = Field(..., description="Target patient population")
    population_detail: str | None = Field(
        None, description="Refined population specification including inclusion criteria"
    )
    intervention: str = Field(..., description="Intervention or exposure of interest")
    comparator: str | None = Field(
        None, description="Comparator arm; None for single-arm descriptive studies"
    )
    outcomes: list[str] = Field(
        ..., min_length=1, description="Research outcomes, ordered by primary then secondary"
    )
    timeframe: str | None = Field(
        None, description="Observation window or follow-up period description"
    )
    study_intent: str | None = Field(
        None, description="Study design intent (e.g., 'retrospective cohort characterization')"
    )


class ClinicalQuestion(BaseModel):
    """Full representation of a curated clinical research question with PICO and metadata."""

    id: str = Field(..., description="Unique question identifier (e.g., 'q-sglt2-ckd-t2dm-001')")
    raw_question: str = Field(..., description="Original natural-language research question text")
    pico: PICOFramework
    ambiguity_flags: list[AmbiguityFlag] = Field(
        default_factory=list, description="Identified ambiguities requiring human resolution"
    )
    clarifying_questions: list[str] = Field(
        default_factory=list,
        description="Specific questions to resolve before finalizing the study design",
    )
    structured_json: dict[str, Any] = Field(
        default_factory=dict,
        description="Machine-readable metadata (terminology anchors, domain tags, etc.)",
    )
    created_at: datetime = Field(default_factory=_utcnow)
    status: Literal["draft", "approved", "archived"] = Field(
        "draft", description="Question lifecycle status; must be 'approved' before phenotype build"
    )
    source: Literal["user_input", "predefined", "llm_generated"] = Field(
        ..., description="How this question was created"
    )
