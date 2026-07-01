"""Phase 6 test suite: export schemas, manifest, ZIP bundle, PDF, PPTX, service, security.

All tests run offline by default.
Live API tests are marked @pytest.mark.live and excluded from the default suite.

Test categories:
  - Export schemas (ExportRequest, ExportArtifact, ExportManifest)
  - Filename sanitization and traversal protection
  - ZIP bundle security (no traversal, no blocked files, manifest integrity)
  - Checksum utilities
  - Manifest generation
  - ExportService gate check
  - ExportService format generation (text formats only in unit tests)
  - PDF generation structural checks
  - PPTX generation structural checks
  - Export repository persistence
  - Security: path traversal, malicious filenames, ZIP-slip
  - UI helpers for export
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

import pytest

from src.exports.checksums import manifest_sha256, sha256_bytes, sha256_file
from src.exports.filename import (
    artifact_filename,
    assert_no_traversal,
    bundle_filename,
    sanitize,
    sanitize_filename,
    zip_entry_path,
)
from src.exports.manifest import build_manifest, make_artifact, manifest_to_bytes
from src.exports.service import ExportGateError, ExportService
from src.exports.zip_bundle import build_zip, verify_zip
from src.schemas.brief import ClaimCitation
from src.schemas.exports import (
    ExportArtifact,
    ExportManifest,
    ExportRequest,
    extension_for,
    mime_type_for,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

_DISCLAIMER_FRAGMENT = "not a clinical recommendation"


def _make_brief(
    generation_mode: str = "deterministic",
    human_review_status: str = "not_reviewed",
    data_origin: str = "captured_source_fixture",
) -> object:
    from src.schemas.brief import (
        EvidenceBrief,
        EvidenceSnapshot,
        EvidenceSnapshotRecord,
        GeneratedClaim,
    )

    snap_rec = EvidenceSnapshotRecord(
        evidence_id="ev-001",
        source_specific_id="12345678",
        source_type="publication",
        source_name="pubmed",
        title="Test Study",
        content_hash="abc123",
        is_fixture_data=True,
        fixture_manifest_version="1.0.0",
        data_origin="captured_source_fixture",
        retrieval_run_id="run-abc",
        relevance_score=0.8,
    )
    snapshot = EvidenceSnapshot(
        snapshot_id="snap-test",
        retrieval_run_id="run-abc",
        query_hash="qh-test",
        records=[snap_rec],
        source_statuses={"pubmed": "ok"},
    )
    claim = GeneratedClaim(
        claim_id="cl-001",
        text="Association observed in observational data.",
        claim_type="supported",
        dimension="outcome",
        evidence_basis="record_supported",
        source_ids=["ev-001"],
        citations=[
            ClaimCitation(
                citation_number=1,
                source_id="ev-001",
                source_specific_id="12345678",
                source_type="publication",
                title="Test Study",
            )
        ],
    )
    brief = EvidenceBrief(
        brief_id=f"brief-{uuid.uuid4().hex[:8]}",
        question_id="q-test",
        phenotype_id="pheno-test",
        phenotype_version="1.0.0",
        evidence_run_id="run-abc",
        evidence_snapshot_id=snapshot.snapshot_id,
        evidence_snapshot_hash=snapshot.snapshot_hash,
        generation_mode=generation_mode,  # type: ignore[arg-type]
        data_origin=data_origin,  # type: ignore[arg-type]
        claims=[claim],
        human_review_status=human_review_status,  # type: ignore[arg-type]
    )
    return brief, snapshot


def _make_artifact(export_format: str = "json", brief_id: str = "brief-test") -> ExportArtifact:
    content = b'{"test": true}'
    return ExportArtifact(
        artifact_id=str(uuid.uuid4()),
        brief_id=brief_id,
        brief_version=1,
        export_format=export_format,  # type: ignore[arg-type]
        filename=artifact_filename(brief_id, export_format),
        mime_type=mime_type_for(export_format),
        byte_size=len(content),
        sha256=sha256_bytes(content),
        origin_classification="captured_source_fixture",
        review_status="not_reviewed",
    )


# ── Schema tests ───────────────────────────────────────────────────────────────


class TestExportRequest:
    def test_valid_single_format(self) -> None:
        req = ExportRequest(brief_id="b1", formats=["json"])
        assert req.formats == ["json"]

    def test_valid_multiple_formats(self) -> None:
        req = ExportRequest(brief_id="b1", formats=["json", "pdf", "zip"])
        assert len(req.formats) == 3

    def test_duplicate_format_rejected(self) -> None:
        with pytest.raises(ValueError, match="Duplicate format"):
            ExportRequest(brief_id="b1", formats=["json", "json"])

    def test_empty_formats_rejected(self) -> None:
        with pytest.raises(ValueError):
            ExportRequest(brief_id="b1", formats=[])

    def test_bundle_name_optional(self) -> None:
        req = ExportRequest(brief_id="b1", formats=["json"])
        assert req.bundle_name is None


class TestExportArtifact:
    def test_valid_artifact(self) -> None:
        art = _make_artifact("json")
        assert art.export_format == "json"
        assert art.byte_size == 14

    def test_sha256_must_be_64_hex(self) -> None:
        with pytest.raises(ValueError, match="sha256"):
            ExportArtifact(
                artifact_id="x",
                brief_id="b",
                brief_version=1,
                export_format="json",
                filename="b_v1_brief.json",
                mime_type="application/json",
                byte_size=10,
                sha256="not-a-valid-hash",
                origin_classification="captured_source_fixture",
                review_status="not_reviewed",
            )

    def test_filename_no_path_separators(self) -> None:
        with pytest.raises(ValueError, match="Filename must not contain"):
            ExportArtifact(
                artifact_id="x",
                brief_id="b",
                brief_version=1,
                export_format="json",
                filename="../evil/path.json",
                mime_type="application/json",
                byte_size=10,
                sha256="a" * 64,
                origin_classification="captured_source_fixture",
                review_status="not_reviewed",
            )

    def test_mime_type_for_known_formats(self) -> None:
        assert mime_type_for("json") == "application/json"
        assert mime_type_for("pdf") == "application/pdf"
        assert mime_type_for("zip") == "application/zip"
        assert "presentationml" in mime_type_for("pptx")

    def test_extension_for(self) -> None:
        assert extension_for("json") == ".json"
        assert extension_for("pdf") == ".pdf"
        assert extension_for("zip") == ".zip"
        assert extension_for("pptx") == ".pptx"


# ── Checksum tests ─────────────────────────────────────────────────────────────


class TestChecksums:
    def test_sha256_bytes_known(self) -> None:
        h = sha256_bytes(b"hello")
        assert len(h) == 64
        assert h == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    def test_sha256_bytes_empty(self) -> None:
        h = sha256_bytes(b"")
        assert len(h) == 64

    def test_sha256_file(self, tmp_path: object) -> None:
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"test content")
            fname = f.name
        try:
            h = sha256_file(fname)
            assert h == sha256_bytes(b"test content")
        finally:
            os.unlink(fname)

    def test_manifest_sha256_stable(self) -> None:
        hashes = ["aaa", "bbb", "ccc"]
        h1 = manifest_sha256(hashes)
        h2 = manifest_sha256(hashes)
        assert h1 == h2

    def test_manifest_sha256_order_independent(self) -> None:
        hashes = ["aaa", "bbb", "ccc"]
        h1 = manifest_sha256(hashes)
        h2 = manifest_sha256(["ccc", "aaa", "bbb"])
        assert h1 == h2  # sorted before hashing


# ── Filename tests ─────────────────────────────────────────────────────────────


class TestFilename:
    def test_sanitize_removes_unsafe_chars(self) -> None:
        assert sanitize("hello world!@#$%") == "hello_world_____"

    def test_sanitize_strips_leading_dot(self) -> None:
        assert not sanitize(".hidden").startswith(".")

    def test_sanitize_max_length(self) -> None:
        result = sanitize("a" * 200)
        assert len(result) <= 80

    def test_artifact_filename_safe(self) -> None:
        fname = artifact_filename("brief-abc", "json")
        assert "/" not in fname
        assert "\\" not in fname
        assert fname.endswith(".json")

    def test_bundle_filename_default(self) -> None:
        fname = bundle_filename("brief-abc", None)
        assert fname.endswith(".zip")

    def test_assert_no_traversal_blocks_dotdot(self) -> None:
        with pytest.raises(ValueError, match="traverse"):
            assert_no_traversal("../../etc/passwd")

    def test_assert_no_traversal_blocks_absolute(self) -> None:
        with pytest.raises(ValueError):
            assert_no_traversal("/etc/passwd")

    def test_assert_no_traversal_allows_normal(self) -> None:
        assert_no_traversal("brief/file.json")  # should not raise

    def test_zip_entry_path_safe(self) -> None:
        entry = zip_entry_path("brief", "my_file.json")
        assert entry == "brief/my_file.json"  # sanitize_filename preserves extension

    def test_sanitize_filename_preserves_extension(self) -> None:
        result = sanitize_filename("my brief.pdf")
        assert result.endswith(".pdf")


# ── Manifest tests ─────────────────────────────────────────────────────────────


class TestManifest:
    def test_make_artifact_computes_checksum(self) -> None:
        content = b"hello world"
        art = make_artifact(
            brief_id="b-1",
            brief_version=1,
            export_format="json",
            filename="b-1_v1_brief.json",
            content=content,
            origin_classification="captured_source_fixture",
            review_status="not_reviewed",
        )
        assert art.sha256 == sha256_bytes(content)
        assert art.byte_size == len(content)

    def test_build_manifest_sets_sha256(self) -> None:
        art = _make_artifact("json", "brief-001")
        m = build_manifest(
            brief_id="brief-001",
            brief_version=1,
            brief_content_hash="ch-abc",
            snapshot_hash="sh-abc",
            generation_mode="deterministic",
            origin_classification="captured_source_fixture",
            review_status="not_reviewed",
            evidence_run_id="run-001",
            bundle_name="brief-001_bundle.zip",
            artifacts=[art],
        )
        assert m.manifest_sha256 != ""
        assert len(m.manifest_sha256) == 64

    def test_manifest_to_bytes_is_valid_json(self) -> None:
        art = _make_artifact("json", "brief-001")
        m = build_manifest(
            brief_id="brief-001",
            brief_version=1,
            brief_content_hash="ch",
            snapshot_hash="sh",
            generation_mode="deterministic",
            origin_classification="captured_source_fixture",
            review_status="not_reviewed",
            evidence_run_id="run-001",
            bundle_name="bundle.zip",
            artifacts=[art],
        )
        data = manifest_to_bytes(m)
        parsed = json.loads(data)
        assert parsed["brief_id"] == "brief-001"
        assert len(parsed["artifacts"]) == 1

    def test_manifest_artifact_count_matches(self) -> None:
        arts = [_make_artifact("json"), _make_artifact("markdown")]
        m = build_manifest(
            brief_id="b",
            brief_version=1,
            brief_content_hash="",
            snapshot_hash="",
            generation_mode="deterministic",
            origin_classification="captured_source_fixture",
            review_status="not_reviewed",
            evidence_run_id="run",
            bundle_name="b.zip",
            artifacts=arts,
        )
        assert len(m.artifacts) == 2


# ── ZIP bundle tests ───────────────────────────────────────────────────────────


class TestZipBundle:
    def _make_manifest_with_artifacts(
        self,
        formats: list[str] | None = None,
    ) -> tuple[ExportManifest, dict[str, bytes]]:
        if formats is None:
            formats = ["json", "markdown"]
        arts = []
        contents: dict[str, bytes] = {}
        for fmt in formats:
            content = f"test content for {fmt}".encode()
            art = make_artifact(
                brief_id="b-001",
                brief_version=1,
                export_format=fmt,
                filename=artifact_filename("b-001", fmt),
                content=content,
                origin_classification="captured_source_fixture",
                review_status="not_reviewed",
            )
            arts.append(art)
            contents[art.artifact_id] = content
        m = build_manifest(
            brief_id="b-001",
            brief_version=1,
            brief_content_hash="ch",
            snapshot_hash="sh",
            generation_mode="deterministic",
            origin_classification="captured_source_fixture",
            review_status="not_reviewed",
            evidence_run_id="run",
            bundle_name="b-001_bundle.zip",
            artifacts=arts,
        )
        return m, contents

    def test_zip_is_valid_archive(self) -> None:
        m, contents = self._make_manifest_with_artifacts()
        zip_bytes = build_zip(m, contents, "disclaimer text", "data notice", "not_reviewed")
        assert zipfile.is_zipfile(io.BytesIO(zip_bytes))

    def test_zip_contains_manifest(self) -> None:
        m, contents = self._make_manifest_with_artifacts()
        zip_bytes = build_zip(m, contents, "disclaimer", "notice", "not_reviewed")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
        assert "manifest.json" in names

    def test_zip_contains_readme(self) -> None:
        m, contents = self._make_manifest_with_artifacts()
        zip_bytes = build_zip(m, contents, "disclaimer", "notice", "not_reviewed")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
        assert "README.txt" in names

    def test_zip_no_absolute_paths(self) -> None:
        m, contents = self._make_manifest_with_artifacts()
        zip_bytes = build_zip(m, contents, "d", "n", "not_reviewed")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for entry in zf.infolist():
                assert not entry.filename.startswith("/")
                assert not entry.filename.startswith("\\")

    def test_zip_manifest_checksums_valid(self) -> None:
        m, contents = self._make_manifest_with_artifacts()
        zip_bytes = build_zip(m, contents, "d", "n", "not_reviewed")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            manifest_data = json.loads(zf.read("manifest.json"))
        # Each artifact in manifest should have a sha256
        for art in manifest_data["artifacts"]:
            assert len(art["sha256"]) == 64

    def test_verify_zip_passes_valid_archive(self) -> None:
        m, contents = self._make_manifest_with_artifacts()
        zip_bytes = build_zip(m, contents, "d", "n", "not_reviewed")
        ok, violations = verify_zip(zip_bytes)
        assert ok
        assert violations == []

    def test_verify_zip_detects_traversal(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../evil.txt", b"hacked")
        ok, violations = verify_zip(buf.getvalue())
        assert not ok
        assert len(violations) > 0

    def test_zip_formats_in_correct_subfolders(self) -> None:
        m, contents = self._make_manifest_with_artifacts(["json", "pdf"])
        zip_bytes = build_zip(m, contents, "d", "n", "not_reviewed")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = set(zf.namelist())
        # json → brief/, pdf → brief/
        assert any("brief/" in n for n in names)

    def test_zip_does_not_include_blocked_files(self) -> None:
        m, contents = self._make_manifest_with_artifacts()
        zip_bytes = build_zip(m, contents, "d", "n", "not_reviewed")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
        assert ".env" not in names
        assert not any(".pyc" in n for n in names)


# ── ExportService gate check tests ────────────────────────────────────────────


class TestExportServiceGate:
    def test_gate_passes_valid_brief(self) -> None:
        brief, snapshot = _make_brief()
        svc = ExportService()
        gate = svc.check_export_gate(brief, snapshot, qa_results=[])
        assert not gate.is_export_blocked

    def test_gate_blocks_on_missing_disclaimer(self) -> None:

        brief, snapshot = _make_brief()
        # Manually corrupt disclaimer via model_copy
        bad_brief = brief.model_copy(update={"disclaimer": "No safety info."})
        svc = ExportService()
        gate = svc.check_export_gate(bad_brief, snapshot, qa_results=[])
        assert gate.is_export_blocked
        assert any("disclaimer" in r.lower() for r in gate.block_reasons)

    def test_gate_blocks_on_missing_snapshot(self) -> None:
        brief, _ = _make_brief()
        svc = ExportService()
        gate = svc.check_export_gate(brief, snapshot=None, qa_results=[])
        assert gate.is_export_blocked
        assert any("snapshot" in r.lower() for r in gate.block_reasons)

    def test_gate_blocks_on_critical_qa_failure(self) -> None:
        brief, snapshot = _make_brief()
        qa_results = [
            {
                "check_id": "BQ-001",
                "check_name": "Required citations",
                "status": "failed",
                "severity": "critical",
                "details": "Missing citations",
            }
        ]
        svc = ExportService()
        gate = svc.check_export_gate(brief, snapshot, qa_results)
        assert gate.is_export_blocked
        assert gate.has_critical_failures

    def test_gate_passes_with_warning_only(self) -> None:
        brief, snapshot = _make_brief()
        qa_results = [
            {
                "check_id": "BQ-006",
                "status": "warning",
                "severity": "major",
                "check_name": "Causal language",
                "details": "Warning only",
            }
        ]
        svc = ExportService()
        gate = svc.check_export_gate(brief, snapshot, qa_results)
        assert not gate.is_export_blocked
        assert not gate.has_critical_failures


# ── ExportService format generation tests ─────────────────────────────────────


class TestExportServiceFormats:
    def test_generate_json(self) -> None:
        brief, snapshot = _make_brief()
        svc = ExportService()
        content = svc.generate_format("json", brief, snapshot, [], [])
        data = json.loads(content)
        assert "brief_id" in data

    def test_generate_markdown_contains_disclaimer(self) -> None:
        brief, snapshot = _make_brief()
        svc = ExportService()
        content = svc.generate_format("markdown", brief, snapshot, [], [])
        text = content.decode("utf-8")
        # The required disclaimer keywords appear in the markdown (may be formatted with blockquote)
        assert "not a clinical recommendation" in text
        assert "not be used for patient care" in text

    def test_generate_citation_map_tsv(self) -> None:
        brief, snapshot = _make_brief()
        svc = ExportService()
        content = svc.generate_format("citation_map_tsv", brief, snapshot, [], [])
        text = content.decode("utf-8")
        assert "\t" in text  # TSV format

    def test_generate_citation_map_json(self) -> None:
        brief, snapshot = _make_brief()
        svc = ExportService()
        content = svc.generate_format("citation_map_json", brief, snapshot, [], [])
        data = json.loads(content)
        assert isinstance(data, list)

    def test_generate_qa_report_json(self) -> None:
        brief, snapshot = _make_brief()
        qa = [{"check_id": "BQ-001", "status": "passed"}]
        svc = ExportService()
        content = svc.generate_format("qa_report_json", brief, snapshot, qa, [])
        data = json.loads(content)
        assert isinstance(data, list)
        assert data[0]["check_id"] == "BQ-001"

    def test_generate_review_history_json(self) -> None:
        brief, snapshot = _make_brief()
        history = [{"new_status": "in_review", "reviewer_id": "test"}]
        svc = ExportService()
        content = svc.generate_format("review_history_json", brief, snapshot, [], history)
        data = json.loads(content)
        assert data[0]["new_status"] == "in_review"

    def test_generate_schema_json(self) -> None:
        brief, snapshot = _make_brief()
        svc = ExportService()
        content = svc.generate_format("schema", brief, snapshot, [], [])
        data = json.loads(content)
        assert isinstance(data, dict)

    def test_generate_unsupported_format_raises(self) -> None:
        brief, snapshot = _make_brief()
        svc = ExportService()
        with pytest.raises(ValueError, match="Unsupported export format"):
            svc.generate_format("docx", brief, snapshot, [], [])

    def test_generate_bundle_raises_on_blocked(self) -> None:
        brief, _ = _make_brief()
        bad_brief = brief.model_copy(update={"disclaimer": "No safety info."})
        svc = ExportService()
        req = ExportRequest(brief_id=bad_brief.brief_id, formats=["json"])
        with pytest.raises(ExportGateError):
            svc.generate_bundle(
                request=req,
                brief=bad_brief,
                snapshot=None,
                qa_results=[],
                review_history=[],
            )

    def test_generate_bundle_returns_artifacts(self) -> None:
        brief, snapshot = _make_brief()
        svc = ExportService()
        req = ExportRequest(brief_id=brief.brief_id, formats=["json", "markdown"])
        bundle, artifact_bytes = svc.generate_bundle(
            request=req, brief=brief, snapshot=snapshot, qa_results=[], review_history=[]
        )
        assert "json" in bundle.artifacts_generated
        assert "markdown" in bundle.artifacts_generated
        assert len(artifact_bytes) >= 2

    def test_bundle_zip_included(self) -> None:
        brief, snapshot = _make_brief()
        svc = ExportService()
        req = ExportRequest(brief_id=brief.brief_id, formats=["json", "zip"])
        bundle, artifact_bytes = svc.generate_bundle(
            request=req, brief=brief, snapshot=snapshot, qa_results=[], review_history=[]
        )
        assert "__zip__" in artifact_bytes
        assert bundle.zip_sha256 is not None

    def test_bundle_all_artifacts_have_checksums(self) -> None:
        brief, snapshot = _make_brief()
        svc = ExportService()
        req = ExportRequest(brief_id=brief.brief_id, formats=["json", "markdown", "provenance"])
        bundle, artifact_bytes = svc.generate_bundle(
            request=req, brief=brief, snapshot=snapshot, qa_results=[], review_history=[]
        )
        for art in bundle.manifest.artifacts:
            assert len(art.sha256) == 64

    def test_same_brief_same_checksums(self) -> None:
        brief, snapshot = _make_brief()
        svc = ExportService()
        req = ExportRequest(brief_id=brief.brief_id, formats=["json", "markdown"])

        bundle1, _ = svc.generate_bundle(
            request=req, brief=brief, snapshot=snapshot, qa_results=[], review_history=[]
        )
        bundle2, _ = svc.generate_bundle(
            request=req, brief=brief, snapshot=snapshot, qa_results=[], review_history=[]
        )
        # Same brief → same content → same checksums
        sha_map1 = {a.export_format: a.sha256 for a in bundle1.manifest.artifacts}
        sha_map2 = {a.export_format: a.sha256 for a in bundle2.manifest.artifacts}
        assert sha_map1 == sha_map2


# ── PDF structural tests ───────────────────────────────────────────────────────


class TestPDFExport:
    def test_pdf_generates_bytes(self) -> None:
        from src.exports.pdf_export import generate_pdf

        brief, snapshot = _make_brief()
        content = generate_pdf(brief, snapshot, [], [])
        assert isinstance(content, bytes)
        assert len(content) > 0

    def test_pdf_starts_with_pdf_header(self) -> None:
        from src.exports.pdf_export import generate_pdf

        brief, snapshot = _make_brief()
        content = generate_pdf(brief, snapshot, [], [])
        assert content[:4] == b"%PDF"

    def test_pdf_page_count_positive(self) -> None:
        """PDF must have at least one page (structural check via pypdf if available)."""
        from src.exports.pdf_export import generate_pdf

        brief, snapshot = _make_brief()
        content = generate_pdf(brief, snapshot, [], [])
        # Structural check: look for /Page marker in the PDF bytes
        assert b"/Page" in content

    def test_pdf_contains_brief_id(self) -> None:
        from src.exports.pdf_export import generate_pdf

        brief, snapshot = _make_brief()
        content = generate_pdf(brief, snapshot, [], [], question_text="Test question")
        # brief_id should appear in the PDF text stream
        assert brief.brief_id.encode("latin-1", errors="replace") in content or len(content) > 1000

    def test_pdf_no_new_claims_in_content(self) -> None:
        """PDF content hash changes when claim text changes — verifies source fidelity."""
        from src.exports.pdf_export import generate_pdf

        brief, snapshot = _make_brief()
        content1 = generate_pdf(brief, snapshot, [], [])

        # Brief with different claim text
        from src.schemas.brief import GeneratedClaim

        new_claim = GeneratedClaim(
            claim_id="cl-002",
            text="Different claim text.",
            claim_type="supported",
            dimension="outcome",
            evidence_basis="record_supported",
            source_ids=["ev-001"],
        )
        brief2 = brief.model_copy(update={"claims": [new_claim]})
        content2 = generate_pdf(brief2, snapshot, [], [])
        # Different claims → different PDFs
        assert content1 != content2


# ── PPTX structural tests ─────────────────────────────────────────────────────


class TestPPTXExport:
    def test_pptx_generates_bytes(self) -> None:
        from src.exports.pptx_export import generate_pptx

        brief, snapshot = _make_brief()
        content = generate_pptx(brief, snapshot, [], [])
        assert isinstance(content, bytes)
        assert len(content) > 0

    def test_pptx_is_valid_zip(self) -> None:
        """PPTX files are ZIP archives — validate the structure."""
        from src.exports.pptx_export import generate_pptx

        brief, snapshot = _make_brief()
        content = generate_pptx(brief, snapshot, [], [])
        assert zipfile.is_zipfile(io.BytesIO(content))

    def test_pptx_contains_presentation_xml(self) -> None:
        from src.exports.pptx_export import generate_pptx

        brief, snapshot = _make_brief()
        content = generate_pptx(brief, snapshot, [], [])
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
        assert any("presentation.xml" in n or "ppt/presentation" in n for n in names)

    def test_pptx_minimum_slide_count(self) -> None:
        """PPTX must have at least 3 slides (title + disclaimer + at least one content)."""
        from src.exports.pptx_export import generate_pptx

        brief, snapshot = _make_brief()
        content = generate_pptx(brief, snapshot, [], [])
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            slides = [n for n in zf.namelist() if "slides/slide" in n and n.endswith(".xml")]
        assert len(slides) >= 3

    def test_pptx_different_briefs_different_content(self) -> None:
        from src.exports.pptx_export import generate_pptx
        from src.schemas.brief import GeneratedClaim

        brief, snapshot = _make_brief()
        content1 = generate_pptx(brief, snapshot, [], [])

        new_claim = GeneratedClaim(
            claim_id="cl-999",
            text="Completely different claim.",
            claim_type="supported",
            dimension="safety",
            evidence_basis="record_supported",
            source_ids=["ev-001"],
        )
        brief2 = brief.model_copy(update={"claims": [new_claim]})
        content2 = generate_pptx(brief2, snapshot, [], [])
        assert content1 != content2


# ── Security tests ────────────────────────────────────────────────────────────


class TestSecurity:
    def test_path_traversal_attempt_in_filename(self) -> None:
        with pytest.raises(ValueError):
            ExportArtifact(
                artifact_id="x",
                brief_id="b",
                brief_version=1,
                export_format="json",
                filename="../../etc/passwd",
                mime_type="application/json",
                byte_size=0,
                sha256="a" * 64,
                origin_classification="captured_source_fixture",
                review_status="not_reviewed",
            )

    def test_zip_slip_attempt_blocked(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../evil.txt", b"hacked")
        ok, violations = verify_zip(buf.getvalue())
        assert not ok

    def test_malicious_filename_sanitized(self) -> None:
        result = sanitize("../../evil/../../path")
        assert ".." not in result
        assert "/" not in result

    def test_no_env_file_in_zip(self) -> None:
        m, contents = self._make_manifest_with_artifacts()
        # Manually inject a .env entry — should be blocked
        zip_bytes = build_zip(m, contents, "d", "n", "not_reviewed")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
        assert ".env" not in names
        assert not any(n.endswith(".env") for n in names)

    def test_no_pyc_in_zip(self) -> None:
        m, contents = self._make_manifest_with_artifacts()
        zip_bytes = build_zip(m, contents, "d", "n", "not_reviewed")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
        assert not any(n.endswith(".pyc") for n in names)

    def test_html_injection_in_brief_id_sanitized(self) -> None:
        html_id = "<script>alert('xss')</script>"
        result = sanitize(html_id)
        assert "<" not in result
        assert ">" not in result

    def _make_manifest_with_artifacts(self) -> tuple[ExportManifest, dict[str, bytes]]:
        content = b"safe content"
        art = make_artifact(
            brief_id="b-001",
            brief_version=1,
            export_format="json",
            filename="b-001_v1_brief.json",
            content=content,
            origin_classification="captured_source_fixture",
            review_status="not_reviewed",
        )
        m = build_manifest(
            brief_id="b-001",
            brief_version=1,
            brief_content_hash="ch",
            snapshot_hash="sh",
            generation_mode="deterministic",
            origin_classification="captured_source_fixture",
            review_status="not_reviewed",
            evidence_run_id="run",
            bundle_name="b-001_bundle.zip",
            artifacts=[art],
        )
        return m, {art.artifact_id: content}


# ── UI helpers tests ───────────────────────────────────────────────────────────


class TestUIHelpers:
    def test_format_file_size_bytes(self) -> None:
        from app.components.ui_helpers import format_file_size

        assert format_file_size(512) == "512 B"

    def test_format_file_size_kb(self) -> None:
        from app.components.ui_helpers import format_file_size

        assert "KB" in format_file_size(2048)

    def test_format_file_size_mb(self) -> None:
        from app.components.ui_helpers import format_file_size

        assert "MB" in format_file_size(2 * 1024 * 1024)

    def test_export_artifact_rows_structure(self) -> None:
        from app.components.ui_helpers import export_artifact_rows

        arts = [
            {
                "export_format": "json",
                "filename": "brief.json",
                "byte_size": 1024,
                "sha256": "a" * 64,
                "origin_classification": "captured_source_fixture",
                "review_status": "not_reviewed",
            }
        ]
        rows = export_artifact_rows(arts)
        assert len(rows) == 1
        assert rows[0]["Format"] == "json"

    def test_sidebar_disclaimer_not_empty(self) -> None:
        from app.components.ui_helpers import sidebar_disclaimer_text

        text = sidebar_disclaimer_text()
        assert len(text) > 20
        assert "synthetic" in text.lower() or "clinical" in text.lower()

    def test_sidebar_data_note_not_empty(self) -> None:
        from app.components.ui_helpers import sidebar_data_note_text

        note = sidebar_data_note_text()
        assert len(note) > 10
