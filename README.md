# Clinical Question-Evidence Studio

[![CI](https://github.com/johannamomole/clinical-question-evidence-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/johannamomole/clinical-question-evidence-studio/actions)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Disclaimer:** This project uses entirely synthetic patient data and publicly available evidence. It is an educational portfolio prototype, has not been clinically validated, and does not provide medical advice.

---

## Project Summary

An end-to-end clinical informatics portfolio prototype that converts a natural-language clinical research question into:

1. A structured PICO-style question
2. A version-controlled computable phenotype with ICD-10-CM, RxNorm, and LOINC mappings
3. A cohort generated from synthetic FHIR R4 patient data (Synthea)
4. External evidence retrieved from PubMed and ClinicalTrials.gov
5. A cited evidence brief with full provenance tracking
6. JSON, Markdown, PDF, and PowerPoint exports
7. Automated data-quality and content-quality checks at every step

## Problem

Translating a clinical question into a computable phenotype, retrieving relevant evidence, and producing a citable summary with complete audit trails is time-consuming, error-prone, and lacks standard tooling in the research setting.

## Architecture

```
Streamlit UI (port 8501)
    ↕ HTTP
FastAPI REST API (port 8000)
    ↕
src/ modules: config · schemas · llm · question_parser · terminology
              fhir · cohorts · evidence_sources · synthesis · qa · exports
    ↕
DuckDB (local) · Synthea fixtures · Public APIs (PubMed, CT.gov, CMS)
```

See [docs/architecture.md](docs/architecture.md) for the full diagram.

## Supported Demo Question (Phase 1)

> "Among adults with type 2 diabetes and chronic kidney disease, how would a computable cohort for SGLT2 inhibitor research be defined, and what external evidence is available?"

- **Population:** Adults ≥18 with T2DM (ICD-10-CM E11.*) and CKD (N18.1–N18.5)
- **Intervention:** SGLT2 inhibitors (empagliflozin, dapagliflozin, canagliflozin)
- **Comparator:** None (descriptive cohort characterization)
- **Data:** Synthetic Synthea FHIR R4 patients

## Technical Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12 |
| Web UI | Streamlit |
| API | FastAPI + Uvicorn |
| Schemas | Pydantic v2 |
| Analytics DB | DuckDB |
| Data wrangling | pandas, Polars |
| Charts | Plotly |
| LLM interface | Provider-agnostic (Anthropic / OpenAI / Demo) |
| Exports | python-pptx, reportlab, JSON, Markdown |
| Testing | pytest + pytest-cov |
| Linting | Ruff |
| Type checking | mypy |
| Infrastructure | Docker, Docker Compose, GitHub Actions |

## Setup

### Prerequisites
- Python 3.12+
- Docker and Docker Compose (optional but recommended)

### Quick Start (local)

```bash
# 1. Clone and enter the repository
git clone https://github.com/johannamomole/clinical-question-evidence-studio.git
cd clinical-question-evidence-studio

# 2. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -e ".[dev]"

# 4. Copy environment template
cp .env.example .env
# Edit .env if you want live LLM support; leave DEMO_MODE=true for offline demo

# 5. Run the Streamlit app
streamlit run app/Home.py

# 6. (Optional) Run the FastAPI server in a second terminal
uvicorn src.api.main:app --reload --port 8000
```

### Docker

```bash
# Build and start both services (Streamlit + FastAPI)
docker compose up -d

# View logs
docker compose logs -f

# Access
# Streamlit: http://localhost:8501
# FastAPI:   http://localhost:8000
# API docs:  http://localhost:8000/docs
```

### Demo Mode

The application runs in deterministic demo mode by default (`DEMO_MODE=true` in `.env`). No API keys are required. All external evidence is served from local fixture files, and all LLM responses use pre-computed outputs.

To enable live LLM responses:
```env
DEMO_MODE=false
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

## API

FastAPI exposes a REST API with automatic Swagger documentation.

```bash
# Health check
curl http://localhost:8000/health

# API metadata
curl http://localhost:8000/info

# Documentation
open http://localhost:8000/docs
```

Phases 1–4 implement:
- `GET /health` — service health
- `GET /info` — API metadata and phase status
- `POST /questions/parse` — PICO extraction
- `POST /phenotypes/build` — phenotype builder
- `POST /cohorts/run` — cohort execution
- `POST /evidence/search` — evidence retrieval (offline-first, all sources)
- `GET /evidence/sources` — source availability
- `GET /evidence/runs/{run_id}` — retrieval run detail
- `GET /evidence/{evidence_id}` — single evidence record
- `POST /terminology/rxnorm/verify` — RxNorm terminology verification

## Testing

```bash
# All tests
pytest tests/ -v

# Unit tests only
pytest tests/unit/ -v

# With coverage
pytest tests/ --cov=src --cov-report=term-missing

# Validate fixtures
python scripts/generate_fixtures.py
```

## Quality Assurance Framework

QA runs at every pipeline step and produces `QAResult` objects in three categories:

- **Data quality** — schema validation, attrition reconciliation, missingness
- **Evidence quality** — citation coverage, source freshness, deduplication
- **AI quality** — uncited claim detection, causal claim flagging, provenance logging

See [docs/qa_framework.md](docs/qa_framework.md) for the full check catalog.

## Data Sources

| Source | Type | Usage |
|--------|------|-------|
| Synthea | Synthetic FHIR R4 | Patient cohort data |
| PubMed / NCBI E-utilities | Public API | Literature metadata |
| ClinicalTrials.gov API v2 | Public API | Trial records |
| CMS Coverage Database | Public | LCD/NCD documents |
| RxNorm (NLM) | Public API | Medication normalization |
| ICD-10-CM | Terminology | Diagnosis coding |
| LOINC | Terminology | Lab/clinical concepts |

All external APIs have local fixture fallbacks for offline operation.

## Limitations

- Supports three curated questions; does not generalize to all medical conditions
- Terminology mappings are candidate suggestions requiring clinical expert review
- Synthetic cohort results reflect Synthea data patterns, not real-world epidemiology
- PDF and PowerPoint styling is functional but not fully designed in Phase 1
- LLM text is labeled and separated from retrieved facts, but accuracy depends on source quality
- No real patient data is used or displayed anywhere in this application

## Ethical and Clinical Disclaimer

This is an educational portfolio project built by Johanna Momole to demonstrate clinical informatics engineering skills. It:

- Uses **only synthetic patient data** (Synthea) and publicly accessible evidence
- Has **not been clinically validated** or deployed in any healthcare organization
- Does **not provide medical advice** or patient-specific recommendations
- Makes **no causal claims** from observational or synthetic data
- Labels all LLM-suggested mappings as **candidate — requiring human review**

## Project Roadmap

| Phase | Content | Status |
|-------|---------|--------|
| 1 | Foundation: schemas, config, fixtures, tests, CI, Docker, health API, overview page | ✅ Complete |
| 2 | PICO extraction, phenotype builder, terminology mapping UI | ✅ Complete |
| 3 | Synthetic FHIR parsing, cohort engine, attrition waterfall | ✅ Complete |
| 4 | External evidence retrieval (PubMed, CT.gov, CMS), normalization, metatagging, ranking, QA | ✅ Complete |
| 5 | Evidence brief generation, citation validation, QA runner | Planned |
| 6 | Full Streamlit pages, export center (JSON/MD/PDF/PPTX) | Planned |
| 7 | UI polish, documentation, architecture diagrams, portfolio case study | Planned |

## Portfolio Impact Statement

This project demonstrates the ability to design and implement a production-style clinical informatics platform from scratch, including FHIR-based data modeling, standard ontology mapping (ICD-10-CM, RxNorm, LOINC), AI governance for healthcare, real-world evidence methodology, and full-stack Python engineering with CI/CD, Docker, and comprehensive testing.

---

*Johanna Momole · johannafiola25@gmail.com · [GitHub](https://github.com/johannamomole)*
