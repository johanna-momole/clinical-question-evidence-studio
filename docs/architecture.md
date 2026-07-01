# Architecture

## System Overview

The Clinical Question-Evidence Studio is a multi-tier portfolio prototype with three deployable components: a FastAPI REST API, a Streamlit web application, and shared Python source modules.

```
┌─────────────────────────────────────────────────────────────────┐
│                    Streamlit Web App (port 8501)                 │
│  Home · Question Builder · Phenotype · Cohort · Evidence ·      │
│  Brief · QA & Provenance · Export Center                        │
└──────────────────────┬──────────────────────────────────────────┘
                       │ HTTP (internal)
┌──────────────────────▼──────────────────────────────────────────┐
│                   FastAPI REST API (port 8000)                   │
│  /health · /questions/parse · /phenotypes/build · /cohorts/run  │
│  /evidence/search · /briefs/generate · /qa/{id} · /exports      │
└──────┬───────────┬──────────┬──────────┬────────────────────────┘
       │           │          │          │
  ┌────▼───┐  ┌───▼────┐ ┌──▼───┐ ┌───▼──────┐
  │DuckDB  │  │Synthea │ │Public│ │LLM       │
  │(local) │  │Fixtures│ │APIs  │ │(optional)│
  └────────┘  └────────┘ └──────┘ └──────────┘
```

## Module Structure

```
src/
├── config/          # Settings (pydantic-settings, .env)
├── schemas/         # Pydantic data models (contracts between all layers)
├── question_parser/ # PICO extraction (Phase 2)
├── terminology/     # ICD-10-CM, RxNorm, LOINC mapping (Phase 2)
├── fhir/            # Synthea FHIR R4 parsing (Phase 3)
├── cohorts/         # Cohort engine and attrition (Phase 3)
├── cache/           # DuckDB-backed evidence cache with injectable clock (Phase 4)
├── evidence_sources/# PubMed, CT.gov, CMS, RxNorm adapters (Phase 4)
├── evidence/        # Query builder, normalizer, dedup, metatagging, ranking, service (Phase 4)
├── synthesis/       # Brief generation, snapshot, citation resolver, export (Phase 5)
├── review/          # Human review service and audit trail (Phase 5)
├── qa/              # QA check runners (Phases 3–5)
├── exports/         # JSON, Markdown, PDF, PPTX (Phase 6)
├── llm/             # Provider-agnostic LLM interface
└── api/             # FastAPI routes
```

## Phase 4 Evidence Subsystem

```
EvidenceService.run()
  ├─ QueryBuilder.build()          → EvidenceQuery (deterministic, gated)
  ├─ Adapter.fetch() × 3           → RawEvidenceRecord[]
  │    └─ EvidenceCache (DuckDB)   → TTL-aware per-source cache
  ├─ normalize_records()           → EvidenceRecord[] (typed subclasses)
  ├─ dedup_records()               → EvidenceDeduplicationResult
  ├─ tag_records()                 → EvidenceRecord[] (with tags)
  ├─ rank_records()                → EvidenceRecord[] (with relevance_score)
  ├─ run_evidence_checks()         → QASummary (EQ-001 – EQ-010)
  ├─ run_retrieval_checks()        → QASummary (RQ-001 – RQ-006)
  └─ EvidenceRepository.save_run() → DuckDB persistence (10 tables)
```

All retrieval is offline-first. The default mode (`offline_only=True`) reads from versioned fixtures under `data/fixtures/evidence/` and produces deterministic output. Live mode (`offline_only=False`) is available but excluded from the default test suite via `@pytest.mark.live`.

## Phase 5 Brief Generation Subsystem

```
EvidenceBriefService.generate()
  ├─ _validate_evidence_run()          → Gate: run_id, records, query_hash required
  ├─ build_snapshot()                  → EvidenceSnapshot (content-addressed SHA-256)
  ├─ _gate_snapshot()                  → warn on failed sources
  ├─ generate_deterministic() OR       → list[GeneratedClaim], list[EvidenceGap]
  │   generate_live_llm()              → (strict JSON validation, 1 retry max)
  ├─ resolve_citations()               → stable [N] numbers by claim_id alpha sort
  ├─ generate_limitations()            → deterministic from structured metadata
  ├─ run_brief_checks()                → BQ-001 through BQ-016
  │    └─ has_critical_failures()      → block on critical failures
  └─ SynthesisRepository.save_*()     → DuckDB (9 tables)

BriefReviewService.submit_review()
  ├─ _check_transition()               → guard rail on valid status changes
  ├─ BriefReviewRecord validation      → blocks "clinically approved" label
  └─ SynthesisRepository.log_audit()  → append-only audit trail
```

## Key Design Decisions

- **Repository pattern**: All data access goes through adapter classes so DuckDB can be swapped for PostgreSQL without touching business logic.
- **Provider-agnostic LLM**: The `BaseLLMClient` interface allows Anthropic or OpenAI to be swapped; demo mode requires no API key.
- **Schema-first**: Pydantic models define the data contract before any code is written against it.
- **Fixture-driven development**: All external APIs have local fixture fallbacks for offline testing and demo.
- **QA as a first-class feature**: Every pipeline step emits `QAResult` objects that aggregate into a `QASummary`.
