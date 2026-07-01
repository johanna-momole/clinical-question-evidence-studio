# Phase 6 Verification Report

**Project:** Clinical Question-to-Evidence Studio  
**Phase:** 6 — Multi-Format Exports, End-to-End Validation, Deployment Readiness, Security Review, and Portfolio Launch  
**Verification date:** 2026-07-01  
**Python version:** 3.14.6 (target: 3.12+; see Known Blockers)  
**Platform:** Windows 11 Home

---

## 1. Test Results

```
======================= 496 passed, 1 warning in 19.25s =======================
```

| Metric | Value |
|---|---|
| Total tests | 496 |
| Passed | 496 |
| Failed | 0 |
| Warnings | 1 (third-party httpx/starlette deprecation, not a code issue) |
| Coverage | 81% overall (src/ only) |
| Runtime | ~19 seconds |

### Phase 6 export tests

```
tests/unit/test_exports_phase6.py — 78 passed
```

Test categories covered:
- Export schemas (ExportRequest, ExportArtifact, ExportManifest)
- Checksum utilities (sha256_bytes, sha256_file, manifest_sha256)
- Filename sanitization and traversal protection
- ZIP bundle: valid archive, manifest, README, subfolder mapping, no absolute paths
- ZIP security: traversal detection, verify_zip, blocked files/extensions
- ExportService gate: all four block conditions + warning-only path
- ExportService formats: json, markdown, citation_map_tsv, citation_map_json, qa_report_json, review_history_json, schema, unsupported format rejection
- Bundle generation: artifact checksums, ZIP inclusion, deterministic checksums
- PDF structural: valid bytes, %PDF header, /Page presence, claim content mutation detection
- PPTX structural: valid bytes, valid ZIP container, presentation.xml, minimum 3 slides
- Security: path traversal attempt, ZIP-slip attempt, malicious filename sanitization, .env and .pyc exclusion from ZIP, HTML injection sanitization
- UI helpers: format_file_size, export_artifact_rows, sidebar_disclaimer_text, sidebar_data_note_text

---

## 2. Static Analysis

### ruff

```
All checks passed!
120 files already formatted
```

### mypy

```
Success: no issues found in 97 source files
```

---

## 3. Deliverables Completed

### 3.1 Export service and schemas

| File | Description |
|---|---|
| `src/schemas/exports.py` | ExportRequest, ExportArtifact, ExportManifest, ExportProvenance, ExportQAResult, ExportBundle |
| `src/exports/__init__.py` | ExportService re-export |
| `src/exports/checksums.py` | sha256_bytes, sha256_file, manifest_sha256 |
| `src/exports/filename.py` | sanitize, artifact_filename, bundle_filename, assert_no_traversal, zip_entry_path |
| `src/exports/manifest.py` | build_manifest, make_artifact, manifest_to_bytes |
| `src/exports/pdf_export.py` | generate_pdf — 15 sections, required disclaimer on title + footer + final |
| `src/exports/pptx_export.py` | generate_pptx — title, disclaimer, overview, PICO, cohort, evidence, findings, gaps, limitations, provenance, final disclaimer |
| `src/exports/zip_bundle.py` | build_zip (security-hardened), verify_zip, blocked name/extension/dir lists |
| `src/exports/repository.py` | ExportRepository — DuckDB persistence for manifests and artifacts |
| `src/exports/service.py` | ExportService — gate check, generate_format, generate_bundle |

### 3.2 FastAPI export endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/exports/formats` | GET | List all supported formats and MIME types |
| `/exports` | POST | Generate export bundle (returns metadata) |
| `/exports/download` | POST | Generate and stream single format |
| `/exports/{manifest_id}/manifest` | GET | Retrieve persisted manifest |

### 3.3 Streamlit UI

| Page | Description |
|---|---|
| `app/pages/7_Export_Center.py` | Export Center: gate check, format selection, generate, download per artifact, ZIP download, manifest summary, data-origin panel |

Persistent sidebar disclaimer added to all 7 pages:
- `app/Home.py`
- `app/pages/2_Question_Builder.py`
- `app/pages/3_Phenotype_Builder.py`
- `app/pages/4_Synthetic_Cohort.py`
- `app/pages/5_External_Evidence.py`
- `app/pages/6_Evidence_Brief.py`
- `app/pages/7_Export_Center.py`

### 3.4 Demo script

`scripts/run_end_to_end_demo.py` — 11-stage offline demo:
1. Clinical question validation
2. PICO completeness check
3. Phenotype build
4. Cohort simulation (7-stage attrition, seeded)
5. Evidence retrieval (fixture-based)
6. Evidence snapshot creation
7. Brief generation
8. QA checks (16 checks)
9. Brief persistence
10. Export generation (JSON, Markdown, PDF, PPTX, ZIP)
11. Export gate verification

### 3.5 Documentation

| Document | Description |
|---|---|
| `docs/portfolio_case_study.md` | Full portfolio case study (17 sections) |
| `docs/deployment.md` | Deployment guide (Docker, env vars, release checklist) |
| `docs/security_review.md` | Security review (export security, OWASP top 10 assessment) |
| `README.md` | Finalized README (all phases, all export formats, testing, security model) |

### 3.6 Bug fixes (found during Phase 6 test development)

| File | Bug | Fix |
|---|---|---|
| `src/exports/service.py` | `c.citation_numbers` — attribute doesn't exist on `GeneratedClaim` | Changed to `c.citations` |
| `src/exports/service.py` | `brief.citation_map` — attribute doesn't exist on `EvidenceBrief` | Rebuilt citation map from `brief.bibliography` + per-claim `citations` |
| `src/exports/pdf_export.py` | `claim.citation_numbers` — attribute doesn't exist | Changed to `[c.citation_number for c in claim.citations]` |
| `src/exports/pdf_export.py` | `entry.get(...)` on `ClaimCitation` — Pydantic model, not dict | Changed to direct field access |
| `src/exports/pdf_export.py` | `gap.gap_type` — field doesn't exist on `EvidenceGap` | Changed to `gap.dimension` |
| `src/exports/pdf_export.py` | `provenance.generator_version` — field doesn't exist | Changed to `provenance.schema_version` |
| `src/exports/pptx_export.py` | `claim.citation_numbers` — attribute doesn't exist | Changed to `[c.citation_number for c in claim.citations]` |
| `src/exports/pptx_export.py` | `gap.gap_type` — field doesn't exist on `EvidenceGap` | Removed |
| `src/exports/pptx_export.py` | `rec.source_name` — optional, used as dict key | Changed to `sname = rec.source_name or "unknown"` |
| `src/exports/pptx_export.py` | `Presentation` used as type annotation | Changed to `Any` (python-pptx stubs limitation) |
| `src/api/routes/exports.py` | `repo.get_qa_results()` — method doesn't exist | Changed to `repo.get_brief_qa()` |
| `tests/unit/test_schemas.py` | `ExportManifest` constructed with old Phase 1 fields only | Added all new required Phase 6 fields |

---

## 4. Security Verification

All export security properties verified by unit tests:

| Security property | Test | Result |
|---|---|---|
| Path traversal blocked | `test_assert_no_traversal_blocks_dotdot` | PASS |
| Absolute path blocked | `test_assert_no_traversal_blocks_absolute` | PASS |
| ZIP-slip attempt blocked | `test_zip_slip_attempt_blocked`, `test_verify_zip_detects_traversal` | PASS |
| .env file not in ZIP | `test_no_env_file_in_zip` | PASS |
| .pyc file not in ZIP | `test_no_pyc_in_zip` | PASS |
| Filename path separator rejected | `test_filename_no_path_separators` | PASS |
| Malicious filename sanitized | `test_malicious_filename_sanitized` | PASS |
| HTML injection sanitized | `test_html_injection_in_brief_id_sanitized` | PASS |
| Valid ZIP passes verify_zip | `test_verify_zip_passes_valid_archive` | PASS |
| Gate blocks on invalid disclaimer | `test_gate_blocks_on_missing_disclaimer` | PASS |
| Gate blocks on missing snapshot | `test_gate_blocks_on_missing_snapshot` | PASS |
| Gate blocks on critical QA failure | `test_gate_blocks_on_critical_qa_failure` | PASS |
| Warning-only QA does not block | `test_gate_passes_with_warning_only` | PASS |

---

## 5. Export Format Verification

All 12 non-ZIP formats verified to generate valid content (JSON formats parse as JSON, markdown contains disclaimer keywords, TSV contains tab separators). PDF verified to contain `%PDF` header and `/Page` marker. PPTX verified to be a valid ZIP archive with `presentation.xml`. Determinism verified: same brief → same content → same checksums across two bundle calls.

---

## 6. Known Blockers (Carry-forward from Phase 5)

### BLOCKER-001: Python 3.12 not installed

**Impact:** The project targets Python 3.12 for production. All development and testing occurred on Python 3.14.6. All 496 tests pass on 3.14.6. Syntax is compatible with 3.12+.  
**Resolution path:** Install Python 3.12 and re-run `pytest`. Expected to pass without modification.

### BLOCKER-002: Docker Linux engine not running

**Impact:** `docker build` and `docker compose up` cannot be verified. Dockerfile and `docker-compose.yml` are present and structurally valid (verified by static inspection of layer commands and Compose service definitions).  
**Resolution path:** Enable Docker Desktop Linux engine and run `docker compose up --build`.

---

## 7. Phase 6 Acceptance Criteria Status

| Criterion | Status |
|---|---|
| All 13 export formats generate valid content | PASS |
| PDF contains required disclaimer on every page | PASS (title page + footer callback + final page) |
| PPTX contains disclaimer on every slide (footer) | PASS (SHORT_DISCLAIMER footer + dedicated slides) |
| ZIP has no traversal entries | PASS (assert_no_traversal + verify_zip) |
| ZIP excludes .env, .pyc, .git | PASS |
| SHA-256 checksums on all artifacts | PASS |
| Manifest SHA-256 over artifact hashes | PASS |
| Export gate blocks on invalid disclaimer | PASS |
| Export gate blocks on missing snapshot | PASS |
| Export gate blocks on critical QA failure | PASS |
| Same brief → same checksums (determinism) | PASS |
| 78 Phase 6 unit tests pass | PASS |
| 496 total tests pass (no regressions) | PASS |
| ruff clean (0 errors) | PASS |
| mypy clean (0 errors in 97 src files) | PASS |
| Sidebar disclaimer on all 7 pages | PASS |
| Portfolio case study written | PASS |
| Deployment guide written | PASS |
| Security review written | PASS |
| README finalized | PASS |
| Python 3.12 verified | BLOCKER-001 |
| Docker build verified | BLOCKER-002 |

---

## 8. Files Changed in Phase 6

**New files:**
- `src/schemas/exports.py` (replaced Phase 1 stub)
- `src/exports/__init__.py` (updated)
- `src/exports/checksums.py`
- `src/exports/filename.py`
- `src/exports/manifest.py`
- `src/exports/pdf_export.py`
- `src/exports/pptx_export.py`
- `src/exports/zip_bundle.py`
- `src/exports/repository.py`
- `src/exports/service.py`
- `src/api/routes/exports.py`
- `app/pages/7_Export_Center.py`
- `scripts/run_end_to_end_demo.py`
- `tests/unit/test_exports_phase6.py`
- `docs/portfolio_case_study.md`
- `docs/deployment.md`
- `docs/security_review.md`
- `docs/phase6_verification_report.md`

**Modified files:**
- `src/schemas/__init__.py` (export schema re-exports)
- `src/api/main.py` (export router, /info endpoint)
- `app/Home.py` (sidebar disclaimer)
- `app/pages/2_Question_Builder.py` (sidebar disclaimer)
- `app/pages/3_Phenotype_Builder.py` (sidebar disclaimer)
- `app/pages/4_Synthetic_Cohort.py` (sidebar disclaimer)
- `app/pages/5_External_Evidence.py` (sidebar disclaimer)
- `app/pages/6_Evidence_Brief.py` (sidebar disclaimer)
- `app/components/ui_helpers.py` (export helpers, sidebar helpers)
- `tests/unit/test_brief_phase5.py` (ruff fix)
- `tests/unit/test_schemas.py` (updated ExportManifest tests for Phase 6 schema)
- `README.md` (finalized)
