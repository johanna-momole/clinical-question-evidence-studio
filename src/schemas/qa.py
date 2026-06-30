"""Pydantic schemas for quality assurance checks and provenance tracking."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def _utcnow() -> datetime:
    return datetime.now(UTC)


class QAResult(BaseModel):
    """Result of a single quality assurance check in the pipeline."""

    check_id: str = Field(..., description="Unique check identifier (e.g., 'dq-001-required-cols')")
    check_name: str = Field(..., description="Human-readable check name")
    category: Literal["data_quality", "evidence_quality", "ai_quality"] = Field(
        ..., description="QA check category"
    )
    status: Literal["passed", "warning", "failed", "not_applicable"] = Field(
        ..., description="Check outcome"
    )
    description: str = Field(..., description="What this check validates")
    details: str | None = Field(None, description="Additional context or specific failure details")
    affected_records: list[str] = Field(
        default_factory=list,
        description="IDs of records or fields affected by this check result",
    )
    severity: Literal["critical", "major", "minor", "info"] = Field(
        ...,
        description="Severity if failed ('critical' blocks pipeline); 'info' for always-passing checks",
    )
    timestamp: datetime = Field(default_factory=_utcnow)


class ProvenanceRecord(BaseModel):
    """Tracks the origin and processing history of any pipeline artifact."""

    id: str = Field(..., description="Provenance record identifier")
    run_id: str = Field(..., description="Pipeline run identifier this record belongs to")
    step: str = Field(
        ..., description="Pipeline step that produced this artifact (e.g., 'phenotype_build')"
    )
    artifact_id: str = Field(..., description="Identifier of the artifact being described")
    artifact_type: str = Field(
        ..., description="Artifact type (e.g., 'question', 'phenotype', 'evidence_record')"
    )
    source: str = Field(
        ..., description="Data source or system (e.g., 'PubMed', 'Synthea', 'DemoLLMClient')"
    )
    retrieval_timestamp: datetime = Field(
        default_factory=_utcnow,
        description="When the artifact was created or retrieved",
    )
    model_id: str | None = Field(
        None, description="LLM model identifier if this artifact was AI-generated"
    )
    prompt_hash: str | None = Field(
        None, description="SHA-256 hash of the prompt used, for reproducibility"
    )
    is_llm_generated: bool = Field(
        False, description="True if an LLM contributed to generating this artifact"
    )
    is_human_reviewed: bool = Field(False, description="True if a human has reviewed and approved")
    review_date: datetime | None = None
    reviewer: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class QASummary(BaseModel):
    """Aggregated QA results for a single pipeline run.

    Counts are computed automatically from the results list.
    If has_critical_failure is True, the pipeline should not proceed to export.
    """

    run_id: str
    timestamp: datetime = Field(default_factory=_utcnow)
    results: list[QAResult] = Field(default_factory=list)
    passed: int = Field(default=0, description="Auto-computed from results")
    warnings: int = Field(default=0, description="Auto-computed from results")
    failed: int = Field(default=0, description="Auto-computed from results")
    not_applicable: int = Field(default=0, description="Auto-computed from results")
    has_critical_failure: bool = Field(
        default=False, description="True if any 'critical' severity check failed"
    )

    @model_validator(mode="after")
    def compute_counts(self) -> "QASummary":
        """Recompute aggregate counts whenever results change."""
        self.passed = sum(1 for r in self.results if r.status == "passed")
        self.warnings = sum(1 for r in self.results if r.status == "warning")
        self.failed = sum(1 for r in self.results if r.status == "failed")
        self.not_applicable = sum(1 for r in self.results if r.status == "not_applicable")
        self.has_critical_failure = any(
            r.status == "failed" and r.severity == "critical" for r in self.results
        )
        return self
