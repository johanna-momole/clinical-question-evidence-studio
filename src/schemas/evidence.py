"""Pydantic schemas for normalized external evidence records from public sources."""

from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class EvidenceRecord(BaseModel):
    """Normalized evidence record from any publicly accessible external source.

    Raw API responses are preserved in raw_response for audit and reproducibility.
    All records carry a retrieval_timestamp so evidence freshness can be assessed.
    """

    id: str = Field(..., description="Internal evidence record identifier")
    source_type: Literal["publication", "clinical_trial", "cms_coverage", "guideline"] = Field(
        ..., description="Evidence source category"
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
    relevance_score: float | None = Field(
        None, ge=0.0, le=1.0, description="Computed relevance to the active research question"
    )
    review_status: Literal["pending", "included", "excluded"] = Field(
        "pending", description="Human review status for inclusion in the evidence brief"
    )
    tags: list[str] = Field(
        default_factory=list, description="Metadata tags for filtering and search"
    )
    raw_response: dict[str, Any] | None = Field(
        None, description="Preserved raw API response for audit purposes"
    )


class PublicationRecord(EvidenceRecord):
    """Evidence record sourced from PubMed or similar peer-reviewed publication databases."""

    source_type: Literal["publication"] = "publication"
    pmid: str | None = Field(None, description="PubMed identifier")
    abstract: str | None = Field(None, description="Publication abstract text")
    journal: str | None = Field(None, description="Journal or publication venue")
    doi: str | None = Field(None, description="Digital Object Identifier")
    mesh_terms: list[str] = Field(default_factory=list, description="MeSH terms assigned by NLM")
    citation_count: int | None = Field(None, ge=0, description="Number of citations (if available)")


class ClinicalTrialRecord(EvidenceRecord):
    """Evidence record sourced from ClinicalTrials.gov."""

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


class CoverageRecord(EvidenceRecord):
    """Evidence record from CMS Medicare coverage documentation (LCD/NCD)."""

    source_type: Literal["cms_coverage"] = "cms_coverage"
    lcd_or_ncd_id: str | None = Field(
        None, description="LCD (Local Coverage Determination) or NCD (National) document ID"
    )
    jurisdiction: str | None = Field(
        None, description="Medicare jurisdiction or 'National' for NCDs"
    )
    effective_date: date | None = Field(None, description="Coverage effective date")
    contractor: str | None = Field(None, description="Medicare Administrative Contractor for LCDs")
    coverage_determination: str | None = Field(
        None,
        description="Coverage decision summary (e.g., 'Covered', 'Non-Covered', 'Conditional')",
    )
    applicable_codes: list[str] = Field(
        default_factory=list, description="ICD/CPT/HCPCS codes addressed in this document"
    )
