"""FastAPI routes for external evidence retrieval and search.

Phase 4 endpoints:
  POST /evidence/search          — build query + run full retrieval pipeline
  GET  /evidence/runs/{run_id}   — retrieve metadata for a past run
  GET  /evidence/{evidence_id}   — retrieve a single normalized evidence record
  GET  /evidence/sources         — list available source adapters

No file paths, API keys, or internal implementation details are exposed in responses.
Partial source failures are reported in source_statuses, not as 500 errors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.evidence.service import get_evidence_service
from src.phenotypes.repository import PhenotypeRepository
from src.question_parser.service import get_question_service
from src.utils.exceptions import (
    ApprovalRequiredError,
    EvidenceNotFoundError,
    RetrievalRunNotFoundError,
    UnapprovedPhenotypeError,
)

router = APIRouter(prefix="/evidence", tags=["evidence"])

_FIXTURE_DIR = Path("data/fixtures")


class EvidenceSearchRequest(BaseModel):
    question_id: str = "q-sglt2-ckd-t2dm-001"
    phenotype_id: str = "pheno-sglt2-ckd-t2dm-001"
    sources: list[str] | None = None
    max_results_per_source: int = 50
    approve_question_for_demo: bool = True
    approve_phenotype_for_demo: bool = True


class EvidenceSearchResponse(BaseModel):
    run_id: str
    query_hash: str
    total_records_retrieved: int
    total_records_after_dedup: int
    sources_queried: list[str]
    source_statuses: list[dict[str, Any]]
    retrieval_mode: str
    data_notice: str = (
        "Evidence content is real, publicly available source data "
        "(PubMed, ClinicalTrials.gov, CMS). "
        "In this demo environment records are served from versioned offline fixtures. "
        "Only the patient cohort is synthetic."
    )


@router.post("/search", response_model=EvidenceSearchResponse, summary="Run evidence retrieval")
def search_evidence(request: EvidenceSearchRequest) -> EvidenceSearchResponse:
    """Build an evidence query from an approved question + phenotype and run the full retrieval
    pipeline (normalize, dedup, tag, rank, QA, persist). Returns run metadata."""
    qs = get_question_service()
    question = qs.get_curated_question(request.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail=f"Question '{request.question_id}' not found")

    if request.approve_question_for_demo and question.status != "approved":
        question = question.model_copy(update={"status": "approved"})

    repo = PhenotypeRepository(_FIXTURE_DIR)
    try:
        phenotype = repo.load(request.phenotype_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Phenotype not found: {exc}") from exc

    if request.approve_phenotype_for_demo and phenotype.review_status != "approved":
        phenotype = phenotype.model_copy(update={"review_status": "approved"})

    svc = get_evidence_service()
    try:
        run = svc.run(
            question=question,
            phenotype=phenotype,
            sources=request.sources,
            max_results_per_source=request.max_results_per_source,
            offline_only=True,
        )
    except ApprovalRequiredError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UnapprovedPhenotypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Evidence retrieval failed: {exc}") from exc

    return EvidenceSearchResponse(
        run_id=run.run_id,
        query_hash=run.query.query_hash,
        total_records_retrieved=run.total_records_retrieved,
        total_records_after_dedup=run.total_records_after_dedup,
        sources_queried=list(run.provenance.sources_queried),
        source_statuses=[
            {
                "source_name": ss.source_name,
                "records_retrieved": ss.records_retrieved,
                "records_after_normalization": ss.records_after_normalization,
                "cache_hit": ss.cache_hit,
                "error_count": len(ss.errors),
            }
            for ss in run.source_statuses
        ],
        retrieval_mode=run.provenance.retrieval_mode,
    )


@router.get("/sources", summary="List available evidence sources")
def list_sources() -> dict[str, Any]:
    """Return the names and status of all registered evidence source adapters."""
    from src.evidence_sources.registry import list_sources as _list_sources

    sources = _list_sources()
    return {
        "sources": [{"name": s, "status": "available", "mode": "offline_fixture"} for s in sources]
    }


@router.get("/runs/{run_id}", summary="Get retrieval run metadata")
def get_run(run_id: str) -> dict[str, Any]:
    """Retrieve metadata for a previously executed evidence retrieval run by run_id."""
    svc = get_evidence_service()
    try:
        return svc.get_run(run_id)
    except RetrievalRunNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"No retrieval run found with run_id='{run_id}'"
        ) from exc


@router.get("/{evidence_id}", summary="Get a single evidence record")
def get_evidence_record(evidence_id: str) -> dict[str, Any]:
    """Retrieve a normalized evidence record by its internal evidence_id."""
    svc = get_evidence_service()
    try:
        return svc.get_evidence(evidence_id)
    except EvidenceNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"No evidence record found with id='{evidence_id}'"
        ) from exc
