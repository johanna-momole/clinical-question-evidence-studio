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
├── evidence_sources/# PubMed, CT.gov, CMS adapters (Phase 4)
├── metatagging/     # Tag indexing and search (Phase 4)
├── synthesis/       # Evidence brief generation (Phase 5)
├── qa/              # QA check runners (Phase 5)
├── exports/         # JSON, Markdown, PDF, PPTX (Phase 6)
├── llm/             # Provider-agnostic LLM interface
└── api/             # FastAPI routes
```

## Key Design Decisions

- **Repository pattern**: All data access goes through adapter classes so DuckDB can be swapped for PostgreSQL without touching business logic.
- **Provider-agnostic LLM**: The `BaseLLMClient` interface allows Anthropic or OpenAI to be swapped; demo mode requires no API key.
- **Schema-first**: Pydantic models define the data contract before any code is written against it.
- **Fixture-driven development**: All external APIs have local fixture fallbacks for offline testing and demo.
- **QA as a first-class feature**: Every pipeline step emits `QAResult` objects that aggregate into a `QASummary`.
