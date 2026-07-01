"""Export manifest generation."""

from __future__ import annotations

import json
import uuid

from src.exports.checksums import manifest_sha256, sha256_bytes
from src.schemas.exports import ExportArtifact, ExportManifest, mime_type_for


def build_manifest(
    brief_id: str,
    brief_version: int,
    brief_content_hash: str,
    snapshot_hash: str,
    generation_mode: str,
    origin_classification: str,
    review_status: str,
    evidence_run_id: str,
    bundle_name: str,
    artifacts: list[ExportArtifact],
    warnings: list[str] | None = None,
) -> ExportManifest:
    """Assemble a complete ExportManifest from a list of artifacts."""
    artifact_hashes = [a.sha256 for a in artifacts]
    m_sha256 = manifest_sha256(artifact_hashes)

    return ExportManifest(
        manifest_id=str(uuid.uuid4()),
        brief_id=brief_id,
        brief_version=brief_version,
        brief_content_hash=brief_content_hash,
        snapshot_hash=snapshot_hash,
        bundle_name=bundle_name,
        generator_version="1.0.0",
        schema_version="6.0.0",
        generation_mode=generation_mode,
        origin_classification=origin_classification,
        review_status=review_status,
        artifacts=artifacts,
        warnings=warnings or [],
        manifest_sha256=m_sha256,
        run_id=evidence_run_id,
        formats_requested=[a.export_format for a in artifacts],
        formats_completed=[a.export_format for a in artifacts],
        total_size_bytes=sum(a.byte_size for a in artifacts),
    )


def manifest_to_bytes(manifest: ExportManifest) -> bytes:
    """Serialise the manifest to JSON bytes for inclusion in ZIP."""
    data = manifest.model_dump(mode="json")
    return json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")


def make_artifact(
    brief_id: str,
    brief_version: int,
    export_format: str,
    filename: str,
    content: bytes,
    origin_classification: str,
    review_status: str,
    warnings: list[str] | None = None,
) -> ExportArtifact:
    """Create an ExportArtifact record for a generated file."""
    return ExportArtifact(
        artifact_id=str(uuid.uuid4()),
        brief_id=brief_id,
        brief_version=brief_version,
        export_format=export_format,  # type: ignore[arg-type]
        filename=filename,
        mime_type=mime_type_for(export_format),
        byte_size=len(content),
        sha256=sha256_bytes(content),
        content_source="persisted_brief",
        origin_classification=origin_classification,
        review_status=review_status,
        warnings=warnings or [],
    )
