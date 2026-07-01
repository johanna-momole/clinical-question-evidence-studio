"""FastAPI routes for Phase 6 export generation.

Endpoints:
  POST /exports              — generate export bundle for a brief
  GET  /exports/{id}/manifest — retrieve a persisted manifest
  GET  /exports/formats       — list supported formats and MIME types
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from src.exports.service import ExportGateError, ExportService
from src.schemas.exports import (
    ExportFormat,
    ExportManifest,
    ExportRequest,
    all_formats,
    mime_type_for,
)
from src.synthesis.repository import get_synthesis_repository

router = APIRouter(prefix="/exports", tags=["exports"])

_service = ExportService()


# ── Response models ────────────────────────────────────────────────────────────


class FormatInfo(BaseModel):
    format: str
    mime_type: str
    description: str


class FormatsResponse(BaseModel):
    formats: list[FormatInfo]


class BundleResponse(BaseModel):
    bundle_id: str
    brief_id: str
    formats_generated: list[str]
    zip_sha256: str | None
    zip_byte_size: int | None
    zip_filename: str | None
    manifest_id: str
    warnings: list[str]
    errors: list[str]


_FORMAT_DESCRIPTIONS: dict[str, str] = {
    "json": "Structured brief as JSON",
    "markdown": "Evidence brief as Markdown",
    "citation_map_tsv": "Claim-to-citation mapping as TSV",
    "citation_map_json": "Claim-to-citation mapping as JSON",
    "qa_report_markdown": "QA check results as Markdown",
    "qa_report_json": "QA check results as JSON",
    "review_history_markdown": "Human review history as Markdown",
    "review_history_json": "Human review history as JSON",
    "provenance": "Provenance record as JSON",
    "schema": "Brief JSON Schema definition",
    "pdf": "Evidence brief as PDF",
    "pptx": "Evidence summary as PowerPoint",
    "zip": "Complete ZIP bundle with all artifacts and manifest",
}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _get_brief_or_404(brief_id: str) -> tuple[Any, Any, list[dict], list[dict]]:
    """Load brief + snapshot + QA results + review history or raise 404."""
    repo = get_synthesis_repository()

    brief_data = repo.get_brief(brief_id)
    if brief_data is None:
        raise HTTPException(status_code=404, detail=f"Brief not found: {brief_id}")

    from src.schemas.brief import EvidenceBrief

    brief = EvidenceBrief.model_validate(brief_data)

    snap_data = repo.get_snapshot(brief.evidence_snapshot_id)
    from src.schemas.brief import EvidenceSnapshot

    snapshot = EvidenceSnapshot.model_validate(snap_data) if snap_data else None

    qa_results: list[dict] = repo.get_brief_qa(brief_id) or []
    review_history: list[dict] = repo.get_review_history(brief_id) or []

    return brief, snapshot, qa_results, review_history


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.get(
    "/formats",
    response_model=FormatsResponse,
    summary="List supported export formats",
    description="Returns all export formats supported by this service.",
)
async def list_formats() -> FormatsResponse:
    return FormatsResponse(
        formats=[
            FormatInfo(
                format=fmt,
                mime_type=mime_type_for(fmt),
                description=_FORMAT_DESCRIPTIONS.get(fmt, ""),
            )
            for fmt in all_formats()
        ]
    )


@router.post(
    "",
    summary="Generate export bundle",
    description=(
        "Generate one or more export artifacts for a persisted evidence brief. "
        "Returns bundle metadata. Use format=zip to get a single ZIP download."
    ),
)
async def generate_exports(request: ExportRequest) -> BundleResponse:
    brief, snapshot, qa_results, review_history = _get_brief_or_404(request.brief_id)

    try:
        bundle, _ = _service.generate_bundle(
            request=request,
            brief=brief,
            snapshot=snapshot,
            qa_results=qa_results,
            review_history=review_history,
        )
    except ExportGateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Export generation failed: {exc}") from exc

    return BundleResponse(
        bundle_id=bundle.bundle_id,
        brief_id=request.brief_id,
        formats_generated=bundle.artifacts_generated,
        zip_sha256=bundle.zip_sha256,
        zip_byte_size=bundle.zip_byte_size,
        zip_filename=bundle.zip_filename,
        manifest_id=bundle.manifest.manifest_id,
        warnings=bundle.warnings,
        errors=bundle.errors,
    )


@router.post(
    "/download",
    summary="Generate and stream a single format",
    description=(
        "Generate and immediately return a single export format as a binary response. "
        "Use this for direct browser downloads. For multiple formats, use POST /exports "
        "with format=zip."
    ),
)
async def download_export(
    brief_id: str,
    export_format: ExportFormat,
) -> Response:
    brief, snapshot, qa_results, review_history = _get_brief_or_404(brief_id)

    gate = _service.check_export_gate(brief, snapshot, qa_results)
    if gate.is_export_blocked:
        raise HTTPException(
            status_code=422,
            detail={"blocked": True, "reasons": gate.block_reasons},
        )

    try:
        content = _service.generate_format(
            export_format=export_format,
            brief=brief,
            snapshot=snapshot,
            qa_results=qa_results,
            review_history=review_history,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}") from exc

    from src.exports.filename import artifact_filename

    fname = artifact_filename(brief_id, export_format, brief.version)
    return Response(
        content=content,
        media_type=mime_type_for(export_format),
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get(
    "/{manifest_id}/manifest",
    response_model=ExportManifest,
    summary="Retrieve persisted export manifest",
    description="Returns the manifest for a previously generated export bundle.",
)
async def get_manifest(manifest_id: str) -> ExportManifest:
    manifest = _service.get_manifest(manifest_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"Manifest not found: {manifest_id}")
    return manifest
