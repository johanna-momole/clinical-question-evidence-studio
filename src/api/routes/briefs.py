"""FastAPI routes for Phase 5 evidence brief generation and review.

Endpoints:
  POST /briefs/generate              — generate a new evidence brief
  GET  /briefs/{brief_id}            — retrieve a brief
  POST /briefs/{brief_id}/review     — submit a human review action
  GET  /briefs/{brief_id}/review-history — retrieve full review history
  GET  /briefs/{brief_id}/sources    — retrieve source records for a brief
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.evidence.service import get_evidence_service
from src.review.brief_review_service import BriefReviewService
from src.schemas.brief import (
    BriefGenerationResult,
    BriefReviewStatus,
    GenerationMode,
)
from src.synthesis.brief_service import EvidenceBriefService
from src.utils.exceptions import (
    BriefGenerationError,
    BriefNotFoundError,
    CriticalQABlockError,
    InvalidReviewTransitionError,
    MissingExpectedSourceError,
)

router = APIRouter(prefix="/briefs", tags=["briefs"])


class BriefGenerateRequest(BaseModel):
    evidence_run_id: str
    question_id: str = "q-sglt2-ckd-cvd"
    generation_mode: GenerationMode = "deterministic"
    question_text: str = "What is the evidence for SGLT2 inhibitors in adults with T2DM and CKD?"


class BriefGenerateResponse(BaseModel):
    brief_id: str
    question_id: str
    generation_mode: GenerationMode
    num_claims: int
    num_gaps: int
    num_citations: int
    qa_summary: dict[str, Any]
    data_notice: str
    warnings: list[str]
    human_review_status: BriefReviewStatus
    content_hash: str
    evidence_snapshot_id: str
    evidence_snapshot_hash: str


class ReviewRequest(BaseModel):
    new_status: BriefReviewStatus
    reviewer_id: str
    reviewer_label: str = "Portfolio author review"
    note: str | None = None


class ReviewResponse(BaseModel):
    review_id: str
    brief_id: str
    previous_status: BriefReviewStatus
    new_status: BriefReviewStatus
    reviewer_label: str
    timestamp: str


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


@router.post(
    "/generate",
    response_model=BriefGenerateResponse,
    summary="Generate an evidence brief",
    description=(
        "Run the 8-step brief generation pipeline. "
        "Requires a completed evidence retrieval run. "
        "Returns QA summary and brief metadata; retrieve the full brief via GET /briefs/{id}."
    ),
)
async def generate_brief(request: BriefGenerateRequest) -> BriefGenerateResponse:
    # Fetch evidence run data from the evidence service
    ev_service = get_evidence_service()
    try:
        run_data = ev_service.get_run_as_dict(request.evidence_run_id)
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Evidence run not found: {request.evidence_run_id!r}. "
            "Run POST /evidence/search first.",
        ) from exc

    svc = EvidenceBriefService(question_id=request.question_id)
    try:
        result: BriefGenerationResult = svc.generate(
            run_data=run_data,
            generation_mode=request.generation_mode,
            question_text=request.question_text,
        )
    except (BriefGenerationError, MissingExpectedSourceError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except CriticalQABlockError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Brief generation blocked by critical QA failures: {exc}",
        ) from exc

    brief = result.brief
    return BriefGenerateResponse(
        brief_id=brief.brief_id,
        question_id=brief.question_id,
        generation_mode=brief.generation_mode,
        num_claims=len(brief.claims),
        num_gaps=len(brief.evidence_gaps),
        num_citations=len(brief.bibliography),
        qa_summary=brief.qa_summary,
        data_notice=result.data_notice,
        warnings=result.warnings,
        human_review_status=brief.human_review_status,
        content_hash=brief.content_hash,
        evidence_snapshot_id=brief.evidence_snapshot_id,
        evidence_snapshot_hash=brief.evidence_snapshot_hash,
    )


# ---------------------------------------------------------------------------
# Retrieve
# ---------------------------------------------------------------------------


@router.get(
    "/{brief_id}",
    summary="Retrieve an evidence brief",
    description="Return the full brief including claims, citations, gaps, and QA summary.",
)
async def get_brief(brief_id: str) -> dict[str, Any]:
    svc = EvidenceBriefService()
    try:
        brief = svc.get_brief(brief_id)
    except BriefNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return brief.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


@router.post(
    "/{brief_id}/review",
    response_model=ReviewResponse,
    summary="Submit a human review action",
    description=(
        "Record a human review status change. "
        "Valid transitions: not_reviewed→in_review, in_review→{approved,changes_requested,rejected}. "
        "reviewer_label must not imply clinical approval."
    ),
)
async def submit_review(brief_id: str, request: ReviewRequest) -> ReviewResponse:
    review_svc = BriefReviewService()
    try:
        record = review_svc.submit_review(
            brief_id=brief_id,
            new_status=request.new_status,
            reviewer_id=request.reviewer_id,
            reviewer_label=request.reviewer_label,
            note=request.note,
        )
    except BriefNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidReviewTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ReviewResponse(
        review_id=record.review_id,
        brief_id=record.brief_id,
        previous_status=record.previous_status,
        new_status=record.new_status,
        reviewer_label=record.reviewer_label,
        timestamp=record.timestamp.isoformat(),
    )


# ---------------------------------------------------------------------------
# Review history
# ---------------------------------------------------------------------------


@router.get(
    "/{brief_id}/review-history",
    summary="Retrieve review history",
    description="Return all human review actions for this brief in chronological order.",
)
async def get_review_history(brief_id: str) -> dict[str, Any]:
    review_svc = BriefReviewService()
    try:
        history = review_svc.get_review_history(brief_id)
    except BriefNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"brief_id": brief_id, "reviews": history}


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


@router.get(
    "/{brief_id}/sources",
    summary="Retrieve evidence sources used in a brief",
    description="Return the immutable evidence snapshot records linked to this brief.",
)
async def get_brief_sources(brief_id: str) -> dict[str, Any]:
    svc = EvidenceBriefService()
    try:
        brief = svc.get_brief(brief_id)
    except BriefNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    snapshot = svc.get_snapshot(brief.evidence_snapshot_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot {brief.evidence_snapshot_id!r} not found.",
        )

    return {
        "brief_id": brief_id,
        "evidence_snapshot_id": snapshot.snapshot_id,
        "snapshot_hash": snapshot.snapshot_hash,
        "total_records": len(snapshot.records),
        "data_origin": snapshot.data_origin,
        "records": [r.model_dump(mode="json") for r in snapshot.records],
    }
