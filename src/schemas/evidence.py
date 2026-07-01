"""Pydantic schemas for normalized external evidence records from public sources.

Field convention — unknown / not-reported / not-applicable:
- A field left as ``None`` means the source did not report that value (not reported).
- ``not_applicable_fields`` lists field names that are structurally inapplicable to this
  record's ``source_type`` (e.g., ``enrollment`` has no meaning for a CoverageRecord).

Evidence content is REAL, publicly available source data (PubMed, ClinicalTrials.gov, CMS).
``is_fixture_data`` documents that this demo environment serves versioned offline fixtures
rather than live API responses; it does NOT imply the evidence text is fictional.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

EvidenceSourceName = Literal["pubmed", "clinical_trials_gov", "cms_coverage"]
DatePrecision = Literal["day", "month", "year", "unknown"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class EvidenceTag(BaseModel):
    """A single deterministic, rule-based metadata tag attached to an evidence record."""

    tag: str = Field(..., description="Tag value (e.g., 'population:ckd', 'design:rct')")
    dimension: str = Field(
        ...,
        description="Tag dimension — 'population', 'intervention', 'comparator', "
        "'outcome', 'design', 'source', or 'temporal'",
    )
    rule_id: str = Field(
        ..., description="ID of the deterministic tagging rule that produced this tag"
    )


class RawEvidenceRecord(BaseModel):
    """Preserves the raw, unmodified payload for one source record, pre-normalization."""

    id: str = Field(..., description="Internal raw-record identifier")
    source_name: EvidenceSourceName
    retrieval_run_id: str
    source_identifier: str = Field(
        ..., description="Native source identifier (PMID, NCT ID, LCD/NCD document ID)"
    )
    raw_payload: dict[str, Any] = Field(
        ..., description="Verbatim raw response fragment for this record"
    )
    content_hash: str = Field(
        ...,
        description="SHA-256 hash (truncated 16 hex chars) of the canonical JSON payload, "
        "for integrity verification and same-source deduplication",
    )
    fetched_at: datetime = Field(default_factory=_utcnow)
    is_fixture_data: bool = Field(
        default=True,
        description="True when sourced from a versioned offline fixture, not a live API call",
    )
    fixture_manifest_version: str | None = Field(
        None, description="Version tag of the fixture manifest this record was loaded from"
    )


class EvidenceRecord(BaseModel):
    """Normalized evidence record from any publicly accessible external source.

    Raw API responses are preserved separately (see RawEvidenceRecord) and linked via
    raw_record_id + content_hash for audit and reproducibility.
    All records carry a retrieval_timestamp so evidence freshness can be assessed.
    """

    id: str = Field(..., description="Internal evidence record identifier")
    source_type: Literal["publication", "clinical_trial", "cms_coverage", "guideline"] = Field(
        ..., description="Evidence source category"
    )
    source_name: EvidenceSourceName | None = Field(
        None, description="Originating adapter/source system"
    )
    title: str = Field(..., description="Full title of the evidence source")
    identifier: str = Field(
        ..., description="Source-specific identifier (PMID, NCT ID, LCD number, etc.)"
    )
    url: str | None = Field(None, description="Direct URL to the source; required for citations")
    authors_or_sponsor: list[str] = Field(
        default_factory=list, description="Author list or sponsoring organization"
    )
    publication_or_update_date: date | None = Field(
        None, description="Publication, posting, or last-update date"
    )
    date_precision: DatePrecision = Field(
        default="unknown",
        description="Precision of publication_or_update_date — day, month, year-only, or unknown",
    )
    study_design: str | None = Field(
        None,
        description="Study design label (e.g., 'RCT', 'retrospective cohort', 'meta-analysis')",
    )
    population: str | None = Field(None, description="Study population description")
    intervention: str | None = Field(None, description="Intervention or exposure studied")
    comparator: str | None = Field(None, description="Comparator arm if applicable")
    outcomes: list[str] = Field(default_factory=list, description="Reported outcomes")
    status: str | None = Field(
        None, description="Study or coverage status (e.g., 'Completed', 'Active', 'Covered')"
    )
    evidence_limitations: list[str] = Field(
        default_factory=list, description="Notable limitations from the source or reviewers"
    )
    retrieval_timestamp: datetime = Field(
        default_factory=_utcnow,
        description="UTC timestamp when this record was fetched — preserved for provenance",
    )
    retrieval_run_id: str | None = Field(
        None, description="RetrievalRun.run_id that produced this record"
    )
    fetched_from_cache: bool = Field(
        default=False, description="True if served from local cache rather than a fresh fetch"
    )
    is_fixture_data: bool = Field(
        default=True,
        description="True when retrieved from offline versioned fixtures, not a live API call",
    )
    raw_record_id: str | None = Field(
        None,
        description="ID of the linked RawEvidenceRecord preserving the original payload",
    )
    content_hash: str | None = Field(
        None,
        description="SHA-256 hash (truncated) of the raw source payload, for audit and dedup",
    )
    relevance_score: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Deterministic, rule-based relevance score. "
        "NOT a clinical-quality, confidence, or treatment-recommendation score.",
    )
    relevance_rationale: list[str] = Field(
        default_factory=list,
        description="Human-readable reasons contributing to the relevance score",
    )
    review_status: Literal["pending", "included", "excluded"] = Field(
        "pending", description="Human review status for inclusion in a future evidence brief"
    )
    tags: list[str] = Field(
        default_factory=list, description="Flat tag values for filtering and search"
    )
    structured_tags: list[EvidenceTag] = Field(
        default_factory=list,
        description="Deterministic metadata tags with dimension and rule provenance",
    )
    duplicate_of: str | None = Field(
        None,
        description="ID of the canonical record this is a same-source duplicate of, if any",
    )
    related_record_ids: list[str] = Field(
        default_factory=list,
        description="IDs of likely-related records from other sources — informational only, "
        "never auto-merged into a single record",
    )
    not_applicable_fields: list[str] = Field(
        default_factory=list,
        description="Field names structurally not applicable to this record's source_type",
    )
    raw_response: dict[str, Any] | None = Field(
        None,
        description="Preserved raw API response for audit (legacy inline storage; "
        "prefer raw_record_id + RawEvidenceRecord for new code)",
    )


# Alias preserved for any code that imports NormalizedEvidenceRecord by name.
NormalizedEvidenceRecord = EvidenceRecord


class PublicationRecord(EvidenceRecord):
    source_type: Literal["publication"] = "publication"
    pmid: str | None = Field(None, description="PubMed identifier")
    abstract: str | None = Field(None, description="Publication abstract text")
    journal: str | None = Field(None, description="Journal or publication venue")
    doi: str | None = Field(None, description="Digital Object Identifier")
    mesh_terms: list[str] = Field(default_factory=list, description="MeSH terms assigned by NLM")
    publication_types: list[str] = Field(
        default_factory=list,
        description="PubMed publication type labels (e.g., 'Randomized Controlled Trial')",
    )
    language: str | None = Field(None, description="Publication language")
    citation_count: int | None = Field(
        None,
        ge=0,
        description="Number of citations, if available. The bundled PubMed adapter does "
        "not retrieve citation counts; this remains None unless explicitly set.",
    )


class ClinicalTrialRecord(EvidenceRecord):
    source_type: Literal["clinical_trial"] = "clinical_trial"
    nct_id: str | None = Field(None, description="ClinicalTrials.gov NCT identifier")
    phase: str | None = Field(None, description="Trial phase (e.g., 'Phase 3', 'Phase 2/3')")
    enrollment: int | None = Field(None, ge=0, description="Planned or actual enrollment")
    trial_status: str | None = Field(
        None, description="Recruitment status (e.g., 'Completed', 'Recruiting')"
    )
    primary_completion_date: date | None = None
    sponsor: str | None = Field(None, description="Lead sponsor organization")
    conditions: list[str] = Field(default_factory=list, description="Studied conditions")
    interventions: list[str] = Field(default_factory=list, description="Studied interventions")
    has_results_posted: bool | None = Field(
        None, description="Whether results have been posted to the registry"
    )
    study_type: str | None = Field(None, description="'Interventional' or 'Observational'")


class CoverageRecord(EvidenceRecord):
    source_type: Literal["cms_coverage"] = "cms_coverage"
    lcd_or_ncd_id: str | None = Field(
        None, description="LCD (Local Coverage Determination) or NCD (National) document ID"
    )
    document_type: Literal["LCD", "NCD"] | None = Field(
        None, description="Local vs. National coverage determination"
    )
    jurisdiction: str | None = Field(
        None, description="Medicare jurisdiction or 'National' for NCDs"
    )
    effective_date: date | None = Field(None, description="Coverage effective date")
    retirement_date: date | None = Field(
        None, description="Date the determination was retired, if applicable"
    )
    contractor: str | None = Field(None, description="Medicare Administrative Contractor for LCDs")
    coverage_determination: str | None = Field(
        None,
        description="Coverage decision summary (e.g., 'Covered', 'Non-Covered', 'Conditional')",
    )
    applicable_codes: list[str] = Field(
        default_factory=list, description="ICD/CPT/HCPCS codes addressed in this document"
    )


class EvidenceSearchResult(BaseModel):
    """A single deterministic search hit: evidence record plus why it matched."""

    evidence_id: str
    source_type: Literal["publication", "clinical_trial", "cms_coverage", "guideline"]
    title: str
    relevance_score: float | None = None
    matched_tags: list[str] = Field(default_factory=list)
    snippet: str | None = Field(
        None, description="Short extracted text fragment showing the match context"
    )


class EvidenceDeduplicationResult(BaseModel):
    """Outcome of running deduplication over a retrieval run's records."""

    run_id: str
    total_records: int
    duplicate_groups: list[list[str]] = Field(
        default_factory=list,
        description="Groups of record IDs considered same-source duplicates",
    )
    duplicates_removed: int = 0
    cross_source_relationships: list[list[str]] = Field(
        default_factory=list,
        description="[record_id_a, record_id_b, relationship_type] triples — informational "
        "only, records are never auto-merged across sources",
    )
