"""Phase 5 schemas for evidence brief generation, claim-level citations, and human review.

Schema migration notes (from synthesis.py Phase 1 schemas):
  - GeneratedClaim.claim_type changed from ["retrieved_fact","cohort_result","llm_summary",
    "human_reviewed"] to ["supported","exploratory","insufficient_evidence"].
  - Old Citation renamed to ClaimCitation; new fields: support_type, locator.
  - EvidenceBrief completely replaced with a richer Phase 5 version.
  - Old EvidenceBrief, GeneratedClaim, Citation preserved as aliases in synthesis.py
    for the duration of the existing schema tests; those tests have been updated to
    import from this module.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

DataOriginClass = Literal[
    "live_api",
    "captured_source_fixture",
    "manually_constructed_fixture",
    "mixed",
]

BriefReviewStatus = Literal[
    "not_reviewed",
    "in_review",
    "changes_requested",
    "approved",
    "rejected",
]

GenerationMode = Literal["deterministic", "live_llm"]

ClaimType = Literal["supported", "exploratory", "insufficient_evidence"]

ClaimDimension = Literal[
    "population",
    "intervention",
    "outcome",
    "safety",
    "design",
    "coverage",
    "evidence_gap",
]

EvidenceBasis = Literal["record_supported", "retrieval_gap", "mixed"]

CitationSupportType = Literal["direct", "contextual", "contradictory", "design_limitation"]

_REQUIRED_DISCLAIMER_FRAGMENT = (
    "This brief was generated with automated methods. "
    "It is not a clinical recommendation, has not been clinically validated, "
    "and must not be used for patient care decisions."
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _make_disclaimer(generation_mode: GenerationMode) -> str:
    base = _REQUIRED_DISCLAIMER_FRAGMENT
    if generation_mode == "live_llm":
        return base + " Generative AI was used to draft the narrative content."
    return (
        base
        + " The narrative was generated using deterministic templates without a live language-model call."
    )


def _canon_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


# ---------------------------------------------------------------------------
# Core claim and citation schemas
# ---------------------------------------------------------------------------


class ClaimCitation(BaseModel):
    """A single evidence-record citation supporting a claim."""

    citation_number: int = Field(..., ge=1, description="Reader-facing [N] inline number")
    source_id: str = Field(..., description="EvidenceRecord.id in the immutable snapshot")
    source_specific_id: str = Field(..., description="PMID, NCT ID, LCD document ID, etc.")
    source_type: str = Field(..., description="publication | clinical_trial | cms_coverage")
    title: str
    url: str | None = None
    support_type: CitationSupportType = "direct"
    locator: str | None = Field(
        None,
        description="Structural field that supports this citation (e.g., 'has_results_posted=True'). "
        "Never a fabricated page number or quotation.",
    )
    review_status: str = "pending"


class GeneratedClaim(BaseModel):
    """A single finding in an evidence brief with full citation provenance.

    Validation rules:
    - supported/exploratory: at least one source_id required.
    - exploratory: uncertainty_note is required.
    - insufficient_evidence: may have empty source_ids only when evidence_basis
      is 'retrieval_gap' (a linked EvidenceGap provides the search provenance).
    - Text must use scoped language for absence claims (see spec §9).
    """

    claim_id: str = Field(..., description="Stable identifier within this brief version")
    text: str = Field(..., description="The factual finding as presented to the reader")
    claim_type: ClaimType
    dimension: ClaimDimension
    evidence_basis: EvidenceBasis
    source_ids: list[str] = Field(default_factory=list)
    citations: list[ClaimCitation] = Field(default_factory=list)
    design_limitations: list[str] = Field(default_factory=list)
    uncertainty_note: str | None = None

    @model_validator(mode="after")
    def _validate_citation_rules(self) -> "GeneratedClaim":
        if self.claim_type in ("supported", "exploratory"):
            if not self.source_ids:
                raise ValueError(
                    f"Claim {self.claim_id!r} (type={self.claim_type!r}) requires at least one source_id."
                )
        if self.claim_type == "exploratory" and not self.uncertainty_note:
            raise ValueError(
                f"Exploratory claim {self.claim_id!r} requires uncertainty_note."
            )
        if (
            self.claim_type == "insufficient_evidence"
            and self.source_ids
            and self.evidence_basis != "retrieval_gap"
        ):
            pass  # having source_ids on an insufficient_evidence claim is allowed (e.g. partial evidence)
        return self


class EvidenceGap(BaseModel):
    """Structured record of a gap in retrieved evidence for one dimension."""

    gap_id: str
    description: str
    dimension: ClaimDimension
    retrieval_run_id: str
    sources_searched: list[str] = Field(default_factory=list)
    source_statuses: dict[str, str] = Field(
        default_factory=dict, description="source_name -> 'ok'|'failed'|'empty'"
    )
    query_strings: dict[str, str] = Field(
        default_factory=dict, description="source_name -> query string used"
    )
    filters_applied: dict[str, Any] = Field(default_factory=dict)
    date_range: str | None = None
    result_counts: dict[str, int] = Field(
        default_factory=dict, description="source_name -> number of records returned"
    )
    failed_sources: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Snapshot schema
# ---------------------------------------------------------------------------


class EvidenceSnapshotRecord(BaseModel):
    """Immutable reference to one evidence record within a brief snapshot."""

    evidence_id: str
    source_specific_id: str
    source_type: str
    source_name: str | None
    title: str
    content_hash: str | None
    is_fixture_data: bool
    fixture_manifest_version: str | None
    data_origin: DataOriginClass
    retrieval_run_id: str | None
    relevance_score: float | None
    tags: list[str] = Field(default_factory=list)
    url: str | None = None
    warnings: list[str] = Field(default_factory=list)


class EvidenceSnapshot(BaseModel):
    """Immutable, content-addressed snapshot of evidence records used for a brief.

    Created before generation; the brief is linked to this snapshot so any
    change to the underlying retrieval run requires a new brief version.
    """

    snapshot_id: str
    retrieval_run_id: str
    query_hash: str
    records: list[EvidenceSnapshotRecord] = Field(default_factory=list)
    source_statuses: dict[str, str] = Field(
        default_factory=dict, description="source_name -> 'ok'|'failed'|'partial'"
    )
    qa_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)
    data_origin: DataOriginClass = "captured_source_fixture"
    snapshot_hash: str = Field(
        default="",
        description="SHA-256 of the canonical ordered record IDs + content hashes",
    )

    @model_validator(mode="after")
    def _compute_hash(self) -> "EvidenceSnapshot":
        if not self.snapshot_hash:
            payload = _canon_json(
                {
                    "retrieval_run_id": self.retrieval_run_id,
                    "query_hash": self.query_hash,
                    "record_ids": sorted(r.evidence_id for r in self.records),
                    "content_hashes": sorted(
                        r.content_hash for r in self.records if r.content_hash
                    ),
                }
            )
            self.snapshot_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]
        return self


# ---------------------------------------------------------------------------
# Provenance and generation request
# ---------------------------------------------------------------------------


class BriefProvenance(BaseModel):
    """Complete audit trail for how a brief was generated."""

    brief_id: str
    schema_version: str = "5.0"
    question_id: str
    phenotype_id: str
    phenotype_version: str
    cohort_run_id: str | None
    evidence_run_id: str
    evidence_snapshot_id: str
    evidence_snapshot_hash: str
    generation_mode: GenerationMode
    model_provider: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    model_parameters: dict[str, Any] = Field(default_factory=dict)
    data_origin: DataOriginClass
    generated_at: datetime = Field(default_factory=_utcnow)
    created_by_process: str = "EvidenceBriefService"


class BriefGenerationRequest(BaseModel):
    """API/service request to generate an evidence brief."""

    evidence_run_id: str
    question_id: str
    generation_mode: GenerationMode = "deterministic"
    cohort_run_id: str | None = None


# ---------------------------------------------------------------------------
# Review and audit
# ---------------------------------------------------------------------------


class BriefReviewRecord(BaseModel):
    """A single human review action on a brief."""

    review_id: str
    brief_id: str
    brief_version: int
    previous_status: BriefReviewStatus
    new_status: BriefReviewStatus
    reviewer_id: str = Field(..., description="Local display name or user identifier")
    reviewer_label: str = Field(
        "Portfolio author review",
        description="Human-facing label. Never 'clinically approved'.",
    )
    timestamp: datetime = Field(default_factory=_utcnow)
    note: str | None = None
    content_hash_reviewed: str = Field(
        ..., description="Brief content_hash at the time of this review action"
    )

    @field_validator("reviewer_label")
    @classmethod
    def _no_clinical_approval(cls, v: str) -> str:
        forbidden = {"clinically approved", "clinical approval", "clinically validated"}
        if any(f in v.lower() for f in forbidden):
            raise ValueError(
                "reviewer_label must not imply clinical approval. "
                "Use 'Portfolio author review' or 'Technical review'."
            )
        return v


class BriefAuditRecord(BaseModel):
    """An immutable entry in the brief audit log."""

    audit_id: str
    brief_id: str
    event_type: Literal[
        "created",
        "review_started",
        "changes_requested",
        "approved",
        "rejected",
        "note_added",
        "qa_run",
        "content_changed",
    ]
    actor: str
    timestamp: datetime = Field(default_factory=_utcnow)
    detail: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Main EvidenceBrief
# ---------------------------------------------------------------------------


class EvidenceBrief(BaseModel):
    """Phase 5 evidence brief: structured findings with full citation provenance.

    The disclaimer field is immutable through normal editing — it is set from
    generation_mode and cannot be overridden to remove required safety language.
    """

    brief_id: str
    schema_version: str = "5.0"
    version: int = Field(default=1, ge=1)
    question_id: str
    phenotype_id: str
    phenotype_version: str
    cohort_run_id: str | None = None
    evidence_run_id: str
    evidence_snapshot_id: str
    evidence_snapshot_hash: str
    generated_at: datetime = Field(default_factory=_utcnow)
    generation_mode: GenerationMode = "deterministic"
    model_provider: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    model_parameters: dict[str, Any] = Field(default_factory=dict)
    data_origin: DataOriginClass = "captured_source_fixture"
    data_notice: str = ""
    claims: list[GeneratedClaim] = Field(default_factory=list)
    evidence_gaps: list[EvidenceGap] = Field(default_factory=list)
    bibliography: list[ClaimCitation] = Field(
        default_factory=list, description="Ordered citation list for the brief"
    )
    limitations: list[str] = Field(default_factory=list)
    disclaimer: str = Field(default="", description="Immutable safety disclaimer")
    qa_summary: dict[str, Any] = Field(default_factory=dict)
    human_review_status: BriefReviewStatus = "not_reviewed"
    content_hash: str = ""
    provenance: BriefProvenance | None = None
    created_by_process: str = "EvidenceBriefService"
    audit_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _set_disclaimer_and_hash(self) -> "EvidenceBrief":
        # Disclaimer is always set from generation_mode; cannot be cleared
        if not self.disclaimer:
            self.disclaimer = _make_disclaimer(self.generation_mode)
        elif _REQUIRED_DISCLAIMER_FRAGMENT not in self.disclaimer:
            raise ValueError(
                "disclaimer must contain the required safety language. "
                f"Required fragment: {_REQUIRED_DISCLAIMER_FRAGMENT!r}"
            )
        # Data notice defaults
        if not self.data_notice:
            self.data_notice = _default_data_notice(self.data_origin)
        # Content hash
        if not self.content_hash:
            self.content_hash = _compute_brief_hash(self)
        return self


def _default_data_notice(origin: DataOriginClass) -> str:
    if origin == "live_api":
        return (
            "Brief generated from publicly available evidence records "
            "retrieved directly from the documented sources."
        )
    if origin == "captured_source_fixture":
        return (
            "Brief generated from publicly available evidence records "
            "retrieved or captured from the documented sources."
        )
    if origin == "manually_constructed_fixture":
        return (
            "Brief generated from demonstration fixtures. "
            "These fixtures are not represented as current live-source records."
        )
    return (
        "Brief generated from a combination of documented public-source records "
        "and demonstration fixtures. Record-level provenance identifies each origin."
    )


def _compute_brief_hash(brief: "EvidenceBrief") -> str:
    """Stable content hash over claims, citations, gaps, and disclaimer."""
    payload = _canon_json(
        {
            "evidence_snapshot_hash": brief.evidence_snapshot_hash,
            "generation_mode": brief.generation_mode,
            "claims": [
                {
                    "id": c.claim_id,
                    "text": c.text,
                    "type": c.claim_type,
                    "sources": sorted(c.source_ids),
                }
                for c in brief.claims
            ],
            "gaps": [g.gap_id for g in brief.evidence_gaps],
            "disclaimer": brief.disclaimer,
        }
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Generation result
# ---------------------------------------------------------------------------


class BriefGenerationResult(BaseModel):
    """Return value of EvidenceBriefService.generate()."""

    brief: EvidenceBrief
    snapshot: EvidenceSnapshot
    qa_summary: dict[str, Any]
    data_notice: str
    warnings: list[str] = Field(default_factory=list)
    provenance: BriefProvenance


# ---------------------------------------------------------------------------
# Backward-compat type for old synthesis.py tests
# ---------------------------------------------------------------------------

# These legacy types remain importable from synthesis.py for existing tests.
# New code must import from brief.py directly.
_LegacyClaimType = Literal["retrieved_fact", "cohort_result", "llm_summary", "human_reviewed"]
