"""Pydantic schemas for evidence brief generation and citation management.

Every factual claim in the evidence brief must trace back to a Citation.
LLM-generated summaries are explicitly labeled and tracked separately from
retrieved facts and calculated cohort results.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


_DISCLAIMER = (
    "This project uses entirely synthetic patient data and publicly available evidence. "
    "It is an educational portfolio prototype, has not been clinically validated, "
    "and does not provide medical advice."
)


class Citation(BaseModel):
    """A citable reference linked to a specific EvidenceRecord."""

    citation_id: str = Field(..., description="Internal citation identifier (e.g., 'cite-001')")
    evidence_id: str = Field(..., description="Linked EvidenceRecord.id")
    source_type: str = Field(..., description="Evidence source type for display")
    title: str
    identifier: str = Field(..., description="External identifier (PMID, NCT ID, LCD number, etc.)")
    url: str | None = None
    authors_or_sponsor: list[str] = Field(default_factory=list)
    publication_date: str | None = Field(
        None, description="Publication date as ISO string or formatted text"
    )
    retrieval_date: str = Field(..., description="ISO date string of retrieval")
    short_reference: str = Field(
        ...,
        description="Compact inline citation text (e.g., 'Zinman et al., 2015 [PMID:26378978]')",
    )


class GeneratedClaim(BaseModel):
    """A single factual or interpretive claim in the evidence brief, with full provenance.

    Distinguishes retrieved facts (from external sources), cohort results (from
    synthetic data), LLM summaries (model-generated), and human-reviewed content.
    No claim should be marked is_causal=True for observational or synthetic outputs.
    """

    claim_id: str = Field(..., description="Unique claim identifier within this brief")
    claim_text: str = Field(..., description="The factual or interpretive statement")
    claim_type: Literal["retrieved_fact", "cohort_result", "llm_summary", "human_reviewed"] = Field(
        ..., description="Provenance type — determines display treatment in the UI"
    )
    source_ids: list[str] = Field(
        default_factory=list,
        description="EvidenceRecord IDs or CohortSummary IDs supporting this claim",
    )
    citation_ids: list[str] = Field(
        default_factory=list, description="Citation IDs for inline references"
    )
    is_cited: bool = Field(
        ..., description="True only if all source_ids have a corresponding Citation"
    )
    is_causal: bool = Field(
        False,
        description="True if the claim implies causation — must be False for observational/synthetic outputs",
    )
    confidence: Literal["high", "medium", "low", "not_assessed"] = Field("not_assessed")
    notes: str | None = None


class EvidenceBrief(BaseModel):
    """Synthesized evidence brief for a clinical research question.

    The brief distinguishes retrieved facts, cohort results, and LLM-generated
    summaries. Every section citing external evidence must have citation IDs.
    The disclaimer field must always be displayed to users.
    """

    id: str = Field(..., description="Unique brief identifier")
    question_id: str = Field(..., description="Linked ClinicalQuestion.id")
    phenotype_id: str = Field(..., description="Linked PhenotypeDefinition.id")
    cohort_summary_id: str | None = Field(
        None, description="Linked CohortSummary.id; None if cohort was not run"
    )
    research_question: str = Field(..., description="Raw research question text")
    pico_summary: str = Field(..., description="Formatted PICO summary for the brief header")
    phenotype_summary: str = Field(
        ..., description="Plain-language phenotype description for reviewers"
    )
    cohort_summary_text: str = Field(
        ..., description="Narrative summary of the synthetic cohort results"
    )
    evidence_overview: str = Field(
        ..., description="High-level summary of retrieved external evidence"
    )
    key_findings: list[GeneratedClaim] = Field(
        default_factory=list, description="Individual claims with full provenance"
    )
    evidence_gaps: list[str] = Field(
        default_factory=list, description="Identified gaps in the available evidence"
    )
    conflicting_findings: list[str] = Field(
        default_factory=list, description="Conflicting findings across sources"
    )
    limitations: list[str] = Field(
        default_factory=list, description="Study, data, and methodology limitations"
    )
    citations: list[Citation] = Field(default_factory=list)
    provenance_statement: str = Field(
        ..., description="Machine-generated statement describing how this brief was produced"
    )
    date_generated: datetime = Field(default_factory=_utcnow)
    model_id: str | None = Field(
        None, description="LLM model ID used; None when generated in deterministic mode"
    )
    is_deterministic_mode: bool = Field(
        True, description="True when generated without live LLM calls"
    )
    human_review_status: Literal["not_reviewed", "in_review", "approved"] = Field(
        "not_reviewed", description="Human review and approval status"
    )
    disclaimer: str = Field(
        default=_DISCLAIMER,
        description="Must be displayed to all users of this brief",
    )
