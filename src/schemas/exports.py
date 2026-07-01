"""Pydantic schemas for Phase 6 export artifacts, manifests, and bundles."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ── Constants ──────────────────────────────────────────────────────────────────

_GENERATOR_VERSION = "1.0.0"
_SCHEMA_VERSION = "6.0.0"

_MIME_TYPES: dict[str, str] = {
    "json": "application/json",
    "markdown": "text/markdown",
    "citation_map_tsv": "text/tab-separated-values",
    "citation_map_json": "application/json",
    "qa_report_markdown": "text/markdown",
    "qa_report_json": "application/json",
    "review_history_markdown": "text/markdown",
    "review_history_json": "application/json",
    "provenance": "application/json",
    "schema": "application/json",
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "zip": "application/zip",
}

_EXTENSIONS: dict[str, str] = {
    "json": ".json",
    "markdown": ".md",
    "citation_map_tsv": ".tsv",
    "citation_map_json": ".json",
    "qa_report_markdown": ".md",
    "qa_report_json": ".json",
    "review_history_markdown": ".md",
    "review_history_json": ".json",
    "provenance": ".json",
    "schema": ".json",
    "pdf": ".pdf",
    "pptx": ".pptx",
    "zip": ".zip",
}

ExportFormat = Literal[
    "json",
    "markdown",
    "citation_map_tsv",
    "citation_map_json",
    "qa_report_markdown",
    "qa_report_json",
    "review_history_markdown",
    "review_history_json",
    "provenance",
    "schema",
    "pdf",
    "pptx",
    "zip",
]

_ALL_FORMATS: list[ExportFormat] = [
    "json",
    "markdown",
    "citation_map_tsv",
    "citation_map_json",
    "qa_report_markdown",
    "qa_report_json",
    "review_history_markdown",
    "review_history_json",
    "provenance",
    "schema",
    "pdf",
    "pptx",
    "zip",
]

# ── Helpers ────────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(UTC)


def mime_type_for(fmt: str) -> str:
    return _MIME_TYPES.get(fmt, "application/octet-stream")


def extension_for(fmt: str) -> str:
    return _EXTENSIONS.get(fmt, ".bin")


def all_formats() -> list[str]:
    return list(_ALL_FORMATS)


# ── Request ────────────────────────────────────────────────────────────────────


class ExportRequest(BaseModel):
    """Request to generate one or more export artifacts for a persisted brief."""

    brief_id: str = Field(..., description="Brief to export")
    formats: list[ExportFormat] = Field(..., min_length=1, description="Formats to produce")
    bundle_name: str | None = Field(None, description="Override default ZIP base name")
    include_supporting_artifacts: bool = Field(
        True, description="Include schema, provenance, and QA in ZIP"
    )

    @field_validator("formats")
    @classmethod
    def _no_duplicate_formats(cls, v: list[ExportFormat]) -> list[ExportFormat]:
        seen: set[str] = set()
        for fmt in v:
            if fmt in seen:
                raise ValueError(f"Duplicate format requested: {fmt}")
            seen.add(fmt)
        return v


# ── Single artifact ────────────────────────────────────────────────────────────


class ExportArtifact(BaseModel):
    """Metadata record for one generated export file."""

    artifact_id: str = Field(..., description="Unique artifact identifier")
    brief_id: str = Field(..., description="Source brief ID")
    brief_version: int = Field(..., description="Source brief version")
    export_format: ExportFormat = Field(..., description="Format of this artifact")
    filename: str = Field(..., description="Safe filename (no path)")
    mime_type: str = Field(..., description="MIME type")
    byte_size: int = Field(..., ge=0, description="File size in bytes")
    sha256: str = Field(..., description="Hex SHA-256 of file content")
    created_at: datetime = Field(default_factory=_utcnow)
    content_source: str = Field(
        "persisted_brief",
        description="Where content was read from (persisted_brief | persisted_snapshot | etc.)",
    )
    schema_version: str = Field(default=_SCHEMA_VERSION)
    generator_version: str = Field(default=_GENERATOR_VERSION)
    origin_classification: str = Field(
        ...,
        description="DataOriginClass of the source brief",
    )
    review_status: str = Field(..., description="Human review status at export time")
    warnings: list[str] = Field(default_factory=list)

    @field_validator("filename")
    @classmethod
    def _filename_safe(cls, v: str) -> str:
        if "/" in v or "\\" in v or v.startswith("."):
            raise ValueError(f"Filename must not contain path separators or start with '.': {v!r}")
        if not v:
            raise ValueError("Filename must not be empty")
        return v

    @field_validator("sha256")
    @classmethod
    def _sha256_hex(cls, v: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", v):
            raise ValueError("sha256 must be a 64-character lowercase hex string")
        return v


# ── Manifest ───────────────────────────────────────────────────────────────────


class ExportManifest(BaseModel):
    """Complete manifest listing all artifacts in an export bundle."""

    manifest_id: str = Field(..., description="Unique manifest identifier")
    brief_id: str = Field(..., description="Brief this manifest covers")
    brief_version: int = Field(..., description="Brief version at export time")
    brief_content_hash: str = Field(..., description="Content hash of the exported brief")
    snapshot_hash: str = Field(..., description="Evidence snapshot hash")
    bundle_name: str = Field(..., description="Base name for the ZIP archive")
    created_at: datetime = Field(default_factory=_utcnow)
    generator_version: str = Field(default=_GENERATOR_VERSION)
    schema_version: str = Field(default=_SCHEMA_VERSION)
    generation_mode: str = Field(..., description="deterministic | live_llm")
    origin_classification: str = Field(...)
    review_status: str = Field(...)
    artifacts: list[ExportArtifact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    manifest_sha256: str = Field(
        default="",
        description="Hex SHA-256 of all artifact sha256s joined in filename order",
    )

    # Legacy compatibility for Phase 1 callers
    run_id: str = Field(default="", description="Evidence retrieval run ID")
    formats_requested: list[str] = Field(default_factory=list)
    formats_completed: list[str] = Field(default_factory=list)
    export_timestamp: datetime = Field(default_factory=_utcnow)
    file_paths: dict[str, str] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    total_size_bytes: int | None = Field(None, ge=0)

    @property
    def all_succeeded(self) -> bool:
        return set(self.formats_requested) == set(self.formats_completed)


# ── Provenance ─────────────────────────────────────────────────────────────────


class ExportProvenance(BaseModel):
    """Immutable provenance snapshot captured at export time."""

    brief_id: str
    brief_version: int
    snapshot_hash: str
    content_hash: str
    generation_mode: str
    data_origin: str
    review_status: str
    export_timestamp: datetime = Field(default_factory=_utcnow)
    generator_version: str = Field(default=_GENERATOR_VERSION)
    schema_version: str = Field(default=_SCHEMA_VERSION)


# ── QA gate ────────────────────────────────────────────────────────────────────


class ExportQAResult(BaseModel):
    """Result of the export gate check run before generating artifacts."""

    brief_id: str
    has_critical_failures: bool
    is_export_blocked: bool
    block_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=_utcnow)


# ── Bundle ─────────────────────────────────────────────────────────────────────


class ExportBundle(BaseModel):
    """Result returned after a full export generation run."""

    bundle_id: str
    manifest: ExportManifest
    export_qa: ExportQAResult
    zip_sha256: str | None = None
    zip_byte_size: int | None = None
    zip_filename: str | None = None
    artifacts_generated: list[str] = Field(
        default_factory=list,
        description="List of formats successfully generated",
    )
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    completed_at: datetime = Field(default_factory=_utcnow)
