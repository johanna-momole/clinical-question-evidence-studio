"""Pydantic schemas for evidence query construction, retrieval requests, runs, and provenance."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.schemas.evidence import EvidenceSourceName

OfflineMode = Literal["offline_fixture", "live", "cache"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SourceSpecificQuery(BaseModel):
    """A query string/parameter set tailored to one source's API syntax."""

    source_name: EvidenceSourceName
    query_string: str = Field(
        ..., description="Source-native query string (e.g., PubMed boolean query)"
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional source-specific request parameters",
    )
    terms_used: list[str] = Field(
        default_factory=list,
        description="Concept terms/codes that contributed to this query, for traceability",
    )


class EvidenceQuery(BaseModel):
    """A deterministic, non-LLM evidence query built from an approved question + reviewed phenotype."""

    id: str = Field(..., description="Unique query identifier")
    question_id: str = Field(
        ..., description="Source ClinicalQuestion.id — must have status='approved'"
    )
    phenotype_id: str = Field(
        ..., description="Source PhenotypeDefinition.id — must have review_status='approved'"
    )
    phenotype_version: str = Field(..., description="Phenotype version this query was built from")
    population_terms: list[str] = Field(default_factory=list)
    intervention_terms: list[str] = Field(default_factory=list)
    comparator_terms: list[str] = Field(default_factory=list)
    outcome_terms: list[str] = Field(default_factory=list)
    source_queries: list[SourceSpecificQuery] = Field(default_factory=list)
    query_hash: str = Field(
        ...,
        description="SHA-256 hash (truncated 16 hex chars) of the deterministic query inputs, "
        "for cross-run reproducibility verification",
    )
    built_at: datetime = Field(default_factory=_utcnow)


class RetrievalRequest(BaseModel):
    """A user/API-initiated request to execute a retrieval run against one or more sources."""

    query_id: str
    sources: list[EvidenceSourceName] = Field(..., min_length=1)
    use_cache: bool = Field(
        default=True, description="Serve cached results within TTL before a fresh fetch"
    )
    offline_only: bool = Field(
        default=True,
        description="If True, use only versioned fixtures — never call live APIs. "
        "Always True in this demo environment.",
    )
    max_results_per_source: int = Field(50, ge=1, le=500)


class RetrievalError(BaseModel):
    """A typed error from one source adapter during a retrieval run."""

    source_name: EvidenceSourceName
    error_type: Literal[
        "timeout",
        "rate_limited",
        "auth_failed",
        "not_found",
        "parse_error",
        "network_error",
        "fixture_missing",
        "unsupported_query",
    ]
    message: str
    is_fatal_for_source: bool = Field(
        default=True,
        description="If True this source contributed zero records for this run",
    )
    occurred_at: datetime = Field(default_factory=_utcnow)


class RetrievalProvenance(BaseModel):
    """Auditable provenance record for a single retrieval run."""

    run_id: str
    query_hash: str
    retrieval_mode: OfflineMode = "offline_fixture"
    sources_queried: list[EvidenceSourceName]
    fixture_manifest_versions: dict[str, str] = Field(
        default_factory=dict,
        description="source_name -> fixture manifest version string",
    )
    data_authenticity_note: str = Field(
        default=(
            "Evidence content is real, publicly available source data "
            "(PubMed, ClinicalTrials.gov, CMS Medicare Coverage). "
            "In this demo environment the records are served from versioned offline fixtures "
            "rather than live API calls. Only the patient cohort is synthetic."
        ),
    )
    retrieved_at: datetime = Field(default_factory=_utcnow)


class EvidenceSourceStatus(BaseModel):
    """Per-source outcome summary for a retrieval run."""

    source_name: EvidenceSourceName
    records_retrieved: int
    records_after_normalization: int
    errors: list[RetrievalError] = Field(default_factory=list)
    cache_hit: bool = False
    duration_ms: int | None = None


class RetrievalRun(BaseModel):
    """A complete, auditable execution of an evidence retrieval pipeline run."""

    run_id: str
    query: EvidenceQuery
    request: RetrievalRequest
    provenance: RetrievalProvenance
    source_statuses: list[EvidenceSourceStatus] = Field(default_factory=list)
    total_records_retrieved: int = 0
    total_records_after_dedup: int = 0
    started_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = None
