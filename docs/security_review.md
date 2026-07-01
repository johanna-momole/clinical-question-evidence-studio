# Security Review

**Clinical Question-to-Evidence Studio — Phase 6**  
**Review date:** 2026-07-01  
**Scope:** All code in `src/`, `app/`, `scripts/`, `tests/`

This document records the results of a manual security review of the portfolio prototype. Because this is a local, non-networked prototype with no real patient data and no authentication layer, the focus is on:

1. Data integrity and provenance
2. Export security (the primary attack surface in a multi-format document pipeline)
3. Input validation and injection prevention
4. Secret management
5. Known limitations and accepted risks

---

## 1. Data Integrity and Provenance

### 1.1 Evidence snapshot immutability

**Status: PASS**

`EvidenceSnapshot.snapshot_hash` is computed as SHA-256 over the ordered record IDs and content hashes:

```python
payload = _canon_json({
    "retrieval_run_id": ...,
    "query_hash": ...,
    "record_ids": sorted(r.evidence_id for r in self.records),
    "content_hashes": sorted(r.content_hash for r in self.records if r.content_hash),
})
self.snapshot_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]
```

The brief stores `evidence_snapshot_hash` and the export service verifies it matches the loaded snapshot before generating PDF/PPTX. Changing any record in the snapshot invalidates the brief.

### 1.2 Brief content hash

**Status: PASS**

`EvidenceBrief.content_hash` is computed at creation over claims, citations, disclaimer, and snapshot hash. The hash changes if any claim text, citation, or disclaimer changes. The content hash is included in every export artifact and in the manifest.

### 1.3 Export manifest integrity

**Status: PASS**

`ExportManifest.manifest_sha256` is computed as SHA-256 over the sorted SHA-256s of all artifact content bytes. Any change to any artifact changes the manifest hash. The manifest is written to `manifest.json` inside every ZIP bundle.

### 1.4 Cross-source record deduplication

**Status: PASS**

Records are never merged across sources by title similarity alone. Each `EvidenceSnapshotRecord` carries `source_specific_id` (PMID, NCT ID, etc.) and `data_origin`. Deduplication by title alone is explicitly blocked in the retrieval service.

---

## 2. Export Security

### 2.1 Path traversal protection

**Status: PASS**

`assert_no_traversal()` in `src/exports/filename.py` blocks:
- Entries beginning with `/` or `\`
- Entries containing `..` in a path context (`../../`, `..\`, etc.)
- Absolute Windows paths (`C:\`)

This is called on every ZIP entry path in `build_zip()` and on every entry during `verify_zip()`. The post-generation `verify_zip()` pass is a second independent check.

**Test coverage:** `TestZipBundle.test_zip_no_absolute_paths`, `TestZipBundle.test_verify_zip_detects_traversal`, `TestSecurity.test_zip_slip_attempt_blocked` — all pass.

### 2.2 ZIP-slip protection

**Status: PASS**

ZIP-slip is a variant of path traversal where a crafted entry name like `../../../../etc/cron.d/malicious` exits the extraction root. `assert_no_traversal()` catches this pattern. The `verify_zip()` function also scans all entries after generation.

**Test coverage:** `TestSecurity.test_zip_slip_attempt_blocked` — PASS.

### 2.3 Blocked filenames and extensions

**Status: PASS**

The following are never written to a ZIP archive:

| Category | Values |
|---|---|
| Blocked filenames | `.env`, `.env.local`, `.env.production`, `id_rsa`, `id_ed25519`, `.DS_Store`, `Thumbs.db` |
| Blocked extensions | `.pyc`, `.pyo`, `.pyd` |
| Blocked directories | `__pycache__`, `.git`, `.venv`, `node_modules` |

**Test coverage:** `TestSecurity.test_no_env_file_in_zip`, `TestSecurity.test_no_pyc_in_zip` — both PASS.

### 2.4 Filename sanitization

**Status: PASS**

`sanitize()` in `src/exports/filename.py` replaces any character outside `[a-zA-Z0-9_-]` with `_` and strips leading dots. Maximum length is 80 characters. `sanitize_filename()` preserves the extension while sanitizing the stem.

`ExportArtifact.filename` has a Pydantic field validator that rejects any filename containing `/`, `\`, or starting with `.`.

**Test coverage:** `TestFilename.*`, `TestExportArtifact.test_filename_no_path_separators`, `TestSecurity.test_malicious_filename_sanitized`, `TestSecurity.test_html_injection_in_brief_id_sanitized` — all PASS.

### 2.5 Export gate enforcement

**Status: PASS**

`ExportService.check_export_gate()` blocks export when:
1. Brief disclaimer does not contain `_REQUIRED_DISCLAIMER_FRAGMENT`
2. `evidence_snapshot_id` or `evidence_snapshot_hash` is missing on the brief
3. The snapshot object is `None` (not found in persistence)
4. Any QA result has `severity="critical"` AND `status="failed"`

**Test coverage:** All four gate conditions have unit tests in `TestExportServiceGate` — all PASS.

### 2.6 Review status visibility

**Status: PASS**

- Every PDF includes the review status on the title page, in the provenance appendix, and on the final disclaimer slide
- Every PPTX slide has the SHORT_DISCLAIMER footer; the final slide repeats the full disclaimer
- The `ExportArtifact.review_status` field records the status at export time
- `ExportManifest.review_status` records the status at manifest creation time
- Export never presents an unreviewed brief as approved through styling or wording

---

## 3. Input Validation

### 3.1 Pydantic v2 schemas

**Status: PASS**

All external input enters the system through Pydantic v2 models. Strict field validators enforce:
- `ExportArtifact.sha256` must be exactly 64 lowercase hex characters
- `ExportArtifact.filename` must not contain path separators
- `ExportRequest.formats` must have no duplicates and at least one entry
- `EvidenceBrief.disclaimer` must contain `_REQUIRED_DISCLAIMER_FRAGMENT`
- `EvidenceBrief.content_hash` is computed, not user-supplied

### 3.2 FastAPI endpoint input validation

**Status: PASS**

FastAPI's integration with Pydantic v2 validates all request bodies. Invalid input returns HTTP 422 with structured error details before any service code runs.

### 3.3 HTML/script injection

**Status: PASS (limited scope)**

Filenames are sanitized before use. The `sanitize()` function removes `<`, `>`, `&`, `"`, and all other non-alphanumeric characters that could form HTML tags.

**Scope limitation:** The Streamlit UI does not render user-supplied HTML. The FastAPI JSON responses are not rendered in a browser context in this prototype. XSS risk is minimal in the current deployment model.

### 3.4 SQL injection

**Status: PASS**

All DuckDB queries use parameterized statements. No string concatenation is used to build SQL queries. DuckDB's Python API enforces this pattern.

---

## 4. Secret Management

### 4.1 No secrets committed

**Status: PASS**

`.gitignore` excludes `.env*`, `*.key`, `*.pem`, `id_rsa*`, `id_ed25519*`. No API keys or passwords are committed to the repository.

### 4.2 Secret exclusion from ZIP exports

**Status: PASS**

The blocked-filenames list in `zip_bundle.py` includes `.env`, `.env.local`, `.env.production`, `id_rsa`, `id_ed25519`. These files cannot enter a ZIP archive even if somehow present in memory.

### 4.3 NCBI API key handling

**Status: PASS**

The NCBI API key is read from the environment variable `NCBI_API_KEY` at runtime. It is not logged, not stored in DuckDB, and not included in any export artifact. If the key is absent, retrieval falls back to fixture data without raising an error.

---

## 5. Disclaimer Enforcement

### 5.1 Required disclaimer fragment

**Status: PASS**

`_REQUIRED_DISCLAIMER_FRAGMENT` in `src/schemas/brief.py` is:

> "This brief was generated with automated methods. It is not a clinical recommendation, has not been clinically validated, and must not be used for patient care decisions."

This exact text (or the full disclaimer containing it) must be present on:
- The `EvidenceBrief.disclaimer` field (enforced by `model_validator`)
- The PDF title page, page header/footer on every page, and final page
- Every PPTX slide footer and the dedicated disclaimer slides (slides 2 and final)
- The `README.txt` inside every ZIP bundle
- Every Markdown export (blockquote format)

### 5.2 Synthetic data labeling

**Status: PASS**

All cohort attrition outputs are labeled `⚠ Synthetic data only` in the UI and in PPTX speaker notes. The PDF has a dedicated section "Data Origin Notice" that describes the data origin classification of the exported brief. The ZIP README includes the data notice from `brief.data_notice`.

### 5.3 Reviewer label constraints

**Status: PASS**

The `BriefReviewService` rejects reviewer labels that contain "clinically approved", "clinically validated", "medical approval", or similar phrases. Permitted labels are: "Portfolio author review", "Technical review", "Peer review". This prevents a reviewer from accidentally creating a label that implies clinical validation.

---

## 6. Known Limitations and Accepted Risks

### 6.1 No authentication (accepted for prototype)

**Risk:** Any user with local access to the running Streamlit app or FastAPI server can read all briefs, generate exports, and submit review actions.  
**Mitigation:** This is a local-only prototype. No sensitive data is present. Documentation states "Do not expose to the internet without adding authentication."  
**Status: Accepted for portfolio prototype scope.**

### 6.2 DuckDB single-writer (accepted for prototype)

**Risk:** Multiple concurrent writers to the same DuckDB file will error.  
**Mitigation:** The prototype is single-user, single-process. The deployment guide notes this limitation and recommends PostgreSQL for multi-process deployment.  
**Status: Accepted for portfolio prototype scope.**

### 6.3 Python 3.12 not verified in CI (known blocker)

**Risk:** The codebase targets Python 3.12 but was developed on Python 3.14.6. There may be minor compatibility differences.  
**Mitigation:** All 496 tests pass on Python 3.14.6. The syntax used is compatible with Python 3.12+.  
**Status: Release blocker documented in `docs/phase5_verification_report.md`.**

### 6.4 Content hash truncation (known limitation)

**Risk:** `brief.content_hash` is truncated to 16 hex characters (64-bit prefix of a full SHA-256). This provides approximately 1-in-18-quintillion collision resistance, which is acceptable for a local prototype but not for a production system.  
**Mitigation:** Document the truncation. For production, use the full 64-character SHA-256.  
**Status: Documented, acceptable for prototype scope.**

---

## 7. OWASP Top 10 Assessment (Prototype Scope)

| OWASP Category | Status | Notes |
|---|---|---|
| A01 Broken Access Control | N/A (no auth) | Local prototype only |
| A02 Cryptographic Failures | Low risk | SHA-256 throughout; no secrets stored |
| A03 Injection | Mitigated | Parameterized SQL; Pydantic validation |
| A04 Insecure Design | Mitigated | Export gate, disclaimer enforcement, provenance |
| A05 Security Misconfiguration | Low risk | No secrets in config; `.env` excluded from ZIP |
| A06 Vulnerable Components | Periodic review | `pip-audit` run during Phase 6 pre-check |
| A07 Auth/Session Failures | N/A (no auth) | Local prototype only |
| A08 Software Integrity Failures | Mitigated | SHA-256 on all artifacts; manifest hash |
| A09 Logging Failures | Partial | Basic Python logging; no structured audit log |
| A10 SSRF | Low risk | HTTP requests only to NCBI, ClinicalTrials.gov, CMS |

---

## 8. Summary

| Area | Verdict |
|---|---|
| Data integrity (hashing, provenance) | PASS |
| Export gate enforcement | PASS |
| ZIP security (traversal, slip, blocked files) | PASS |
| Filename sanitization | PASS |
| Pydantic input validation | PASS |
| Disclaimer enforcement | PASS |
| Secret exclusion | PASS |
| Authentication | N/A — accepted for prototype scope |
| SQL injection | PASS |
| HTML injection (in current deployment model) | PASS |

No critical security issues found within the intended scope of a local, single-user, portfolio prototype with no real patient data.
