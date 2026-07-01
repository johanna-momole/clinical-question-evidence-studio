# Evidence Retrieval Methodology

## Overview

The External Evidence Retrieval subsystem (Phase 4) fetches, normalizes, deduplicates, metatags, and ranks evidence records from three public sources: PubMed, ClinicalTrials.gov, and CMS Coverage. All retrieval is **offline-first**: the default mode uses versioned fixture files so the application runs without network access and produces deterministic output. Live mode is available but is excluded from the default test suite via `@pytest.mark.live`.

Evidence content is **real, publicly available source data** drawn from PubMed, ClinicalTrials.gov, and CMS Coverage documents. It is never synthetic or artificially generated.

---

## Source Adapters

### PubMed

- **Offline**: reads `data/fixtures/evidence/pubmed/articles.json` (keyed by PMID).
- **Live**: queries the NCBI E-utilities API (`esearch` + `efetch`) via httpx.
- **Identifier**: PMID (string, e.g. `"36473481"`).
- **Key fields**: title, abstract, authors, journal, DOI, MeSH terms, publication types, publication date.
- **Study design inference**: rule-based mapping from PubMed publication type labels (Meta-analysis → RCT → Systematic review → Observational cohort → Review → `None`). No free-text inference.

### ClinicalTrials.gov

- **Offline**: reads `data/fixtures/evidence/clinical_trials/studies.json` (keyed by NCT ID).
- **Live**: queries the ClinicalTrials.gov v2 JSON API (`/api/v2/studies`).
- **Identifier**: NCT ID (e.g. `"NCT04746183"`).
- **Key fields**: official title, overall status, phase, enrollment, conditions, interventions, lead sponsor, primary completion date, `hasResultsPosted`.
- **Design inference**: rule-based from `designModule.designInfo.allocation` + `maskingInfo` (Randomized double-blind → Randomized → Interventional) or `studyType=Observational`.

### CMS Coverage

- **Offline**: reads `data/fixtures/evidence/cms_coverage/documents.json` (keyed by document ID).
- **Live**: queries the CMS Coverage API.
- **Identifier**: LCD or NCD document ID.
- **Key fields**: title, document type (LCD/NCD), jurisdiction, effective/retirement date, contractor, coverage determination, applicable ICD-10/CPT codes.

### RxNorm (Terminology Verification, not evidence retrieval)

- **Offline**: reads `data/fixtures/evidence/rxnorm/rxnorm_index.json` (keyed by RxCUI).
- **Live**: queries `rxnav.nlm.nih.gov/REST`.
- Verification results are stored as `TerminologyVerificationResult` records. **No mapping is auto-approved** — a human reviewer must explicitly apply the result via a `TerminologyVerificationAuditRecord`.

---

## Retrieval Pipeline (8 Steps)

```
build_query → fetch → normalize → dedup → metatag → rank → QA → persist
```

1. **build_query** — `QueryBuilder` creates a deterministic `EvidenceQuery` from an approved `ClinicalQuestion` + reviewed `PhenotypeDefinition`. The query hash is SHA-256 over the canonical JSON of (PICO terms, phenotype_id, phenotype_version, sources).

2. **fetch** — each adapter is called; raw payloads are returned as `RawEvidenceRecord` objects. The cache layer (`EvidenceCache`, DuckDB-backed, 24-hour default TTL) is checked before fetching. Records include `is_fixture_data` and `fixture_manifest_version` for provenance.

3. **normalize** — `normalize_records()` maps each `RawEvidenceRecord` to a typed `EvidenceRecord` subclass (`PublicationRecord`, `ClinicalTrialRecord`, `CoverageRecord`). Missing fields are left `None`; not-applicable fields are listed in `not_applicable_fields`. The original content hash is preserved.

4. **dedup** — `dedup_records()` removes exact duplicates **within the same source only** (same source name + same content hash). Cross-source relationships are logged as informational. Records are **never** merged across sources by title similarity.

5. **metatag** — `tag_records()` applies 7-dimension rule-based tags using keyword lists:
   - `population`, `intervention`, `comparator`, `outcome`, `design`, `source`, `temporal`
   - Each tag has the form `dimension:value` (e.g. `intervention:sglt2_class`).
   - Tags are stored on both `EvidenceRecord.tags` (flat list) and `EvidenceRecord.structured_tags` (typed `EvidenceTag` objects with `rule_id`).

6. **rank** — `rank_records()` assigns a `relevance_score ∈ [0.0, 1.0]` using weighted tag overlap against the query's PICO:

   | Dimension   | Weight |
   |-------------|--------|
   | population  | 0.30   |
   | intervention| 0.30   |
   | outcome     | 0.20   |
   | design      | 0.10   |
   | recency     | 0.10   |

   Recency score decays linearly from 1.0 (≤ 2 years old) to 0.0 (≥ 10 years old). Records without a date receive 0.0 for the recency component.

7. **QA** — two check suites run:
   - `run_evidence_checks()` (EQ-001 through EQ-010): per-record checks (title present, source identifier present, content hash present, date completeness, etc.)
   - `run_retrieval_checks()` (RQ-001 through RQ-006): run-level checks (at least one record retrieved, no fatal errors, all requested sources queried, provenance hash matches, offline mode in demo, post-dedup count ≤ retrieved count).

8. **persist** — `EvidenceRepository.save_run()` writes all 10 tables to DuckDB. `save_run` is idempotent: re-saving the same `run_id` first deletes all prior rows, then re-inserts.

---

## Offline-First Architecture

All retrievals default to `offline_only=True`. The fixture directory structure is:

```
data/fixtures/evidence/
  pubmed/
    manifest.json          # version, index_file, generated_at, article_count
    articles.json          # dict keyed by PMID
  clinical_trials/
    manifest.json
    studies.json           # dict keyed by NCT ID
  cms_coverage/
    manifest.json
    documents.json         # dict keyed by document ID
  rxnorm/
    manifest.json
    rxnorm_index.json      # dict keyed by RxCUI
```

Each manifest records a `version` string. The version is stored in `RawEvidenceRecord.fixture_manifest_version` and propagated to `RetrievalProvenance.fixture_manifest_versions`, making every retrieval run reproducible and auditable.

---

## Gate Requirements

The `QueryBuilder` raises exceptions if either gate is not met:

- `ApprovalRequiredError` — `ClinicalQuestion.status != "approved"`
- `UnapprovedPhenotypeError` — `PhenotypeDefinition.review_status != "approved"`

The Streamlit UI and API both enforce these gates before calling the evidence service.

---

## Determinism

Given identical inputs (same `question_id`, `phenotype_id`, `phenotype_version`, `sources`) and the same fixture files, two independent runs always produce:

1. The same `query_hash` (SHA-256 over canonical JSON, hex-truncated to 16 chars).
2. The same set of `RawEvidenceRecord` objects (same `content_hash` per record).
3. The same normalized, deduped, tagged, and ranked records.
4. The same `evidence_id` values (deterministic: `ev-{source}-{identifier}-{content_hash}`).

This property is verified by the cross-process determinism check in the Phase 4 verification report.

---

## What This System Does NOT Do

- **No LLM-generated evidence synthesis** — the system retrieves and presents source records; it does not produce AI-generated summaries or clinical conclusions.
- **No clinical recommendations** — relevance scores and tags are mechanical; they are not clinical recommendations.
- **No cross-source merging by title similarity** — deduplication is within-source only.
- **No auto-approval of RxNorm mappings** — all terminology verification requires explicit human reviewer action.
- **No PDF or PowerPoint export** — out of scope for Phase 4.
