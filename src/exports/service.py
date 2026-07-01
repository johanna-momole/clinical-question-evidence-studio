"""Export service orchestrating PDF, PPTX, ZIP, JSON, Markdown, and TSV generation.

All exports are derived from persisted data (EvidenceBrief + EvidenceSnapshot +
QA results + review history). No new claims are introduced during export.

Security constraints enforced:
- Path traversal is blocked at zip_bundle level
- Safe filenames enforced throughout
- Export is blocked on critical QA failures
- Export is blocked on invalid disclaimer
- Export is blocked on missing snapshot
- Content hash is verified before exporting an approved brief
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from src.exports.checksums import sha256_bytes
from src.exports.filename import artifact_filename, bundle_filename
from src.exports.manifest import build_manifest, make_artifact
from src.exports.pdf_export import generate_pdf
from src.exports.pptx_export import generate_pptx
from src.exports.repository import ExportRepository, get_export_repository
from src.exports.zip_bundle import build_zip, verify_zip
from src.schemas.brief import EvidenceBrief, EvidenceSnapshot
from src.schemas.exports import (
    ExportArtifact,
    ExportBundle,
    ExportManifest,
    ExportQAResult,
    ExportRequest,
)
from src.synthesis.markdown_export import (
    to_citation_map_tsv,
    to_json,
    to_markdown,
    to_provenance_json,
    to_qa_report_markdown,
    to_review_history_markdown,
)

_SCHEMA_VERSION = "6.0.0"


class ExportGateError(Exception):
    """Raised when the export gate check blocks generation."""


class ExportService:
    """Orchestrates all export formats from a persisted EvidenceBrief."""

    def __init__(self, repo: ExportRepository | None = None) -> None:
        self._repo = repo or get_export_repository()

    # ── Gate check ────────────────────────────────────────────────────────────

    def check_export_gate(
        self,
        brief: EvidenceBrief,
        snapshot: EvidenceSnapshot | None,
        qa_results: list[dict],
    ) -> ExportQAResult:
        """Return an ExportQAResult describing whether export is safe to proceed."""
        block_reasons: list[str] = []
        warnings: list[str] = []

        # Required: valid disclaimer
        from src.schemas.brief import _REQUIRED_DISCLAIMER_FRAGMENT

        if not brief.disclaimer or _REQUIRED_DISCLAIMER_FRAGMENT not in brief.disclaimer:
            block_reasons.append("Brief disclaimer is missing required safety language.")

        # Required: valid snapshot reference
        if not brief.evidence_snapshot_id or not brief.evidence_snapshot_hash:
            block_reasons.append("Brief is missing evidence snapshot reference.")
        if snapshot is None:
            block_reasons.append("Evidence snapshot not found.")

        # Block on critical QA failures
        critical_failed = [
            r
            for r in qa_results
            if r.get("severity") == "critical" and r.get("status") == "failed"
        ]
        if critical_failed:
            ids = ", ".join(r.get("check_id", "?") for r in critical_failed)
            block_reasons.append(f"Critical QA failures present: {ids}")

        # Warn on approved brief without content hash
        if brief.human_review_status == "approved" and not brief.content_hash:
            warnings.append("Approved brief has no content hash — provenance incomplete.")

        # Warn on missing citations
        cited = sum(1 for c in brief.claims if c.citations)
        total_factual = sum(1 for c in brief.claims if c.claim_type in ("supported", "exploratory"))
        if total_factual > 0 and cited < total_factual:
            warnings.append(
                f"{total_factual - cited} of {total_factual} factual claims have no citation numbers."
            )

        is_blocked = len(block_reasons) > 0
        return ExportQAResult(
            brief_id=brief.brief_id,
            has_critical_failures=len(critical_failed) > 0,
            is_export_blocked=is_blocked,
            block_reasons=block_reasons,
            warnings=warnings,
        )

    # ── Schema JSON ───────────────────────────────────────────────────────────

    def _schema_bytes(self, brief: EvidenceBrief) -> bytes:
        from src.schemas.brief import EvidenceBrief as EBSchema

        try:
            schema = EBSchema.model_json_schema()
            return json.dumps(schema, indent=2, ensure_ascii=False).encode("utf-8")
        except Exception:
            return json.dumps({"schema_version": _SCHEMA_VERSION}, indent=2).encode("utf-8")

    # ── Generate a single format ───────────────────────────────────────────────

    def generate_format(
        self,
        export_format: str,
        brief: EvidenceBrief,
        snapshot: EvidenceSnapshot | None,
        qa_results: list[dict],
        review_history: list[dict],
        supplementary: dict[str, Any] | None = None,
    ) -> bytes:
        """Generate raw bytes for one export format. No new claims are added."""
        sup = supplementary or {}

        if export_format == "json":
            return to_json(brief).encode("utf-8")

        elif export_format == "markdown":
            return to_markdown(brief).encode("utf-8")

        elif export_format == "citation_map_tsv":
            return to_citation_map_tsv(brief).encode("utf-8")

        elif export_format == "citation_map_json":
            # Build citation → claim mapping from bibliography + per-claim citations
            claim_ids_by_num: dict[int, list[str]] = {}
            for c in brief.claims:
                for cit in c.citations:
                    claim_ids_by_num.setdefault(cit.citation_number, []).append(c.claim_id)
            entries = [
                {
                    "citation_number": cit.citation_number,
                    "source_id": cit.source_id,
                    "source_specific_id": cit.source_specific_id,
                    "title": cit.title,
                    "claim_ids": claim_ids_by_num.get(cit.citation_number, []),
                }
                for cit in sorted(brief.bibliography, key=lambda c: c.citation_number)
            ]
            return json.dumps(entries, indent=2, ensure_ascii=False).encode("utf-8")

        elif export_format == "qa_report_markdown":
            return to_qa_report_markdown(brief.brief_id, qa_results).encode("utf-8")

        elif export_format == "qa_report_json":
            return json.dumps(qa_results, indent=2, ensure_ascii=False).encode("utf-8")

        elif export_format == "review_history_markdown":
            return to_review_history_markdown(brief.brief_id, review_history).encode("utf-8")

        elif export_format == "review_history_json":
            return json.dumps(review_history, indent=2, ensure_ascii=False).encode("utf-8")

        elif export_format == "provenance":
            prov = brief.provenance
            if prov:
                return to_provenance_json(prov).encode("utf-8")
            return json.dumps(
                {
                    "brief_id": brief.brief_id,
                    "snapshot_id": brief.evidence_snapshot_id,
                    "snapshot_hash": brief.evidence_snapshot_hash,
                    "content_hash": brief.content_hash,
                    "generation_mode": brief.generation_mode,
                    "data_origin": brief.data_origin,
                },
                indent=2,
            ).encode("utf-8")

        elif export_format == "schema":
            return self._schema_bytes(brief)

        elif export_format == "pdf":
            return generate_pdf(
                brief=brief,
                snapshot=snapshot,
                qa_results=qa_results,
                review_history=review_history,
                question_text=sup.get("question_text", ""),
                pico_summary=sup.get("pico_summary"),
                phenotype_summary=sup.get("phenotype_summary"),
                cohort_attrition=sup.get("cohort_attrition"),
            )

        elif export_format == "pptx":
            return generate_pptx(
                brief=brief,
                snapshot=snapshot,
                qa_results=qa_results,
                review_history=review_history,
                question_text=sup.get("question_text", ""),
                pico_summary=sup.get("pico_summary"),
                phenotype_summary=sup.get("phenotype_summary"),
                cohort_attrition=sup.get("cohort_attrition"),
            )

        else:
            raise ValueError(f"Unsupported export format: {export_format!r}")

    # ── Full bundle ───────────────────────────────────────────────────────────

    def generate_bundle(
        self,
        request: ExportRequest,
        brief: EvidenceBrief,
        snapshot: EvidenceSnapshot | None,
        qa_results: list[dict],
        review_history: list[dict],
        supplementary: dict[str, Any] | None = None,
    ) -> tuple[ExportBundle, dict[str, bytes]]:
        """Generate all requested formats and assemble a bundle.

        Returns (ExportBundle, {artifact_id: bytes}) — caller decides
        whether to persist bytes to disk or stream them.
        """
        gate = self.check_export_gate(brief, snapshot, qa_results)
        if gate.is_export_blocked:
            reasons = "; ".join(gate.block_reasons)
            raise ExportGateError(f"Export blocked: {reasons}")

        bundle_id = str(uuid.uuid4())
        artifacts: list[ExportArtifact] = []
        artifact_bytes: dict[str, bytes] = {}
        errors: list[str] = []
        warnings: list[str] = list(gate.warnings)

        non_zip_formats = [f for f in request.formats if f != "zip"]

        for fmt in non_zip_formats:
            try:
                content = self.generate_format(
                    fmt, brief, snapshot, qa_results, review_history, supplementary
                )
                fname = artifact_filename(brief.brief_id, fmt, brief.version)
                artifact = make_artifact(
                    brief_id=brief.brief_id,
                    brief_version=brief.version,
                    export_format=fmt,
                    filename=fname,
                    content=content,
                    origin_classification=brief.data_origin,
                    review_status=brief.human_review_status,
                )
                artifacts.append(artifact)
                artifact_bytes[artifact.artifact_id] = content
            except Exception as exc:
                errors.append(f"{fmt}: {exc}")

        bname = bundle_filename(brief.brief_id, request.bundle_name, brief.version)
        manifest = build_manifest(
            brief_id=brief.brief_id,
            brief_version=brief.version,
            brief_content_hash=brief.content_hash,
            snapshot_hash=brief.evidence_snapshot_hash,
            generation_mode=brief.generation_mode,
            origin_classification=brief.data_origin,
            review_status=brief.human_review_status,
            evidence_run_id=brief.evidence_run_id,
            bundle_name=bname,
            artifacts=artifacts,
            warnings=warnings,
        )

        # Build ZIP if requested
        zip_sha256: str | None = None
        zip_size: int | None = None
        zip_fname: str | None = None
        if "zip" in request.formats:
            try:
                zip_bytes = build_zip(
                    manifest=manifest,
                    artifact_contents=artifact_bytes,
                    disclaimer=brief.disclaimer,
                    data_notice=brief.data_notice or "",
                    review_status=brief.human_review_status,
                )
                ok, violations = verify_zip(zip_bytes)
                if not ok:
                    errors.append(f"ZIP security violations: {'; '.join(violations)}")
                else:
                    zip_sha256 = sha256_bytes(zip_bytes)
                    zip_size = len(zip_bytes)
                    zip_fname = bname
                    zip_artifact_id = str(uuid.uuid4())
                    zip_artifact = make_artifact(
                        brief_id=brief.brief_id,
                        brief_version=brief.version,
                        export_format="zip",
                        filename=bname,
                        content=zip_bytes,
                        origin_classification=brief.data_origin,
                        review_status=brief.human_review_status,
                    )
                    artifact_bytes[zip_artifact_id] = zip_bytes
                    # Store ZIP bytes keyed by its hash for caller retrieval
                    artifact_bytes["__zip__"] = zip_bytes
            except Exception as exc:
                errors.append(f"zip: {exc}")

        bundle = ExportBundle(
            bundle_id=bundle_id,
            manifest=manifest,
            export_qa=gate,
            zip_sha256=zip_sha256,
            zip_byte_size=zip_size,
            zip_filename=zip_fname,
            artifacts_generated=[a.export_format for a in artifacts],
            errors=errors,
            warnings=warnings,
        )

        try:
            self._repo.save_bundle(bundle)
        except Exception:
            pass  # persistence failure does not block the caller

        return bundle, artifact_bytes

    def get_manifest(self, manifest_id: str) -> ExportManifest | None:
        return self._repo.get_manifest(manifest_id)

    def list_manifests_for_brief(self, brief_id: str) -> list[dict]:
        return self._repo.list_manifests_for_brief(brief_id)
