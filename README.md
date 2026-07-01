# Clinical Question-Evidence Studio

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-496%20passed-brightgreen.svg)](#testing)
[![Coverage](https://img.shields.io/badge/coverage-83%25-green.svg)](#testing)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Required notice:** This project uses entirely synthetic patient data and publicly available evidence records. It is an educational portfolio prototype. It has not been clinically validated and does not provide medical advice. Nothing it produces constitutes a clinical recommendation.

---

## Project Summary

An end-to-end clinical informatics portfolio prototype that converts a structured clinical question into a multi-format, citable evidence brief with full provenance tracking, quality assurance, and secure export.

**Pipeline stages:**
1. Structured PICO-format clinical question with ambiguity detection
2. Versioned computable phenotype (ICD-10-CM, RxNorm)
3. Synthetic cohort simulation (700 Synthea FHIR R4 patients, 7-stage attrition)
4. External evidence retrieval (PubMed, ClinicalTrials.gov, CMS Coverage)
5. Immutable evidence snapshot with content-addressed hash
6. Automated brief generation + 16-check QA suite + human review gate
7. Multi-format export: JSON, Markdown, PDF, PPTX, TSV, ZIP bundle

---

## What This Project Is Not

- **Not a clinical decision support tool.** No output informs patient care.
- **Not a production system.** Local-only portfolio prototype.
- **Not peer-reviewed evidence synthesis.** Brief content uses deterministic templates, not expert synthesis.
- **Not validated against clinical guidelines.** QA checks verify structural integrity, not clinical accuracy.

---

## Architecture

```
┌──────────────────────────────────────────────┐
│            Streamlit UI — 7 pages            │
│  Home · Question · Phenotype · Cohort ·      │
│  Evidence · Brief · Export Center            │
└────────────────────┬─────────────────────────┘
                     │
┌────────────────────▼─────────────────────────┐
│           FastAPI REST API — port 8000        │
│  /questions /phenotypes /cohorts /evidence   │
│  /briefs    /reviews    /exports  /info      │
└────────────────────┬─────────────────────────┘
                     │
┌────────────────────▼─────────────────────────┐
│    src/ — Pydantic-validated service layer   │
│  question · phenotype · cohort · evidence    │
│  synthesis · review · exports · terminology  │
└────────────────────┬─────────────────────────┘
                     │
┌────────────────────▼─────────────────────────┐
│  DuckDB (local) · Versioned fixtures         │
│  Synthea FHIR R4 · Public APIs (offline-ok) │
└──────────────────────────────────────────────┘
```

See [docs/architecture.md](docs/architecture.md) for the full diagram.

---

## Demo Clinical Question

> "Among adults with type 2 diabetes and chronic kidney disease, does treatment with SGLT2 inhibitors reduce the risk of cardiovascular events compared to other glucose-lowering agents?"

- **Population:** Adults ≥18 with T2DM (ICD-10-CM E11.*) and CKD (N18.1–N18.5)
- **Intervention:** SGLT2 inhibitors (empagliflozin, dapagliflozin, canagliflozin)
- **Comparator:** Other glucose-lowering agents
- **Outcomes:** CV events, HF hospitalization, renal endpoints
- **Patient data:** Entirely synthetic (Synthea FHIR R4, 700 patients)

---

## Technical Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| UI | Streamlit 1.45+ |
| API | FastAPI + Uvicorn |
| Schemas | Pydantic v2 |
| Analytics DB | DuckDB |
| Document generation | reportlab (PDF), python-pptx (PPTX) |
| Testing | pytest 9+, pytest-cov |
| Linting / formatting | Ruff |
| Type checking | mypy |
| Infrastructure | Docker, Docker Compose |

---

## Supported Export Formats

| Format | Description |
|---|---|
| `json` | Full structured brief as JSON |
| `markdown` | Human-readable brief with citations |
| `citation_map_tsv` | Claim-to-source audit table (TSV) |
| `citation_map_json` | Machine-readable citation map |
| `qa_report_markdown` | QA check results |
| `qa_report_json` | Machine-readable QA results |
| `review_history_markdown` | Human review history |
| `review_history_json` | Machine-readable review history |
| `provenance` | Generation audit record (JSON) |
| `schema` | EvidenceBrief JSON Schema |
| `pdf` | Formatted evidence brief (reportlab) |
| `pptx` | Evidence summary slides (python-pptx) |
| `zip` | All of the above + manifest with SHA-256 checksums |

Every artifact includes a SHA-256 checksum, review status at export time, and data-origin classification.

---

## Setup

### Prerequisites
- Python 3.12+ (3.14.x also confirmed working)
- Docker Desktop with Linux engine (optional)

### Quick Start

```bash
# Clone
git clone <repo-url>
cd clinical-question-evidence-studio

# Virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
.venv\Scripts\activate           # Windows

# Install
pip install -e ".[dev]"

# Run tests
pytest                            # 496 tests, ~19 seconds

# End-to-end demo (offline, no API keys required)
python scripts/run_end_to_end_demo.py

# Launch UI
streamlit run app/Home.py         # http://localhost:8501

# Launch API (optional, separate terminal)
uvicorn src.api.main:app --reload --port 8000
```

### Docker

```bash
docker compose up --build
# Streamlit: http://localhost:8501
# FastAPI:   http://localhost:8000/docs
```

### Demo Mode

All tests and the demo script run offline by default using versioned fixture files. No API keys are required. To enable live evidence retrieval:

```bash
# .env
PUBMED_LIVE_RETRIEVAL=true
NCBI_API_KEY=your-key-here
```

---

## API Endpoints

```
GET  /health                          — Service health
GET  /info                            — API metadata and endpoint status

POST /questions/parse                 — PICO extraction
POST /phenotypes/build                — Phenotype builder
POST /cohorts/run                     — Synthetic cohort simulation
POST /evidence/search                 — Evidence retrieval (offline-first)
GET  /evidence/sources                — Source availability
GET  /evidence/runs/{run_id}          — Retrieval run detail

POST /briefs/generate                 — Evidence brief generation
GET  /briefs/{brief_id}               — Retrieve brief
POST /briefs/{brief_id}/review        — Submit review action
GET  /briefs/{brief_id}/review-history— Reviewer audit trail

GET  /exports/formats                 — List supported export formats
POST /exports                         — Generate export bundle (metadata)
POST /exports/download                — Generate and stream single format
GET  /exports/{manifest_id}/manifest  — Retrieve persisted manifest
```

---

## Testing

```bash
# All tests (496 total)
pytest

# With coverage
pytest --cov=src --cov-report=term-missing

# Phase 6 export tests only
pytest tests/unit/test_exports_phase6.py -v

# Unit tests only
pytest tests/unit/

# Integration tests only
pytest tests/integration/
```

**Test counts by category:**

| Category | Tests |
|---|---|
| Schemas and validation | ~80 |
| Business logic (services) | ~120 |
| Exports — Phase 6 | 78 |
| QA check suite | ~60 |
| Human review | ~40 |
| UI helpers | ~30 |
| FastAPI integration | ~88 |

---

## Security Model

The export pipeline enforces:

- **Export gate:** Blocks on invalid disclaimer, missing snapshot, or critical QA failures
- **Path traversal protection:** No ZIP entry may start with `/`, `\`, `../`, or `..\`
- **ZIP-slip protection:** Post-generation `verify_zip()` scans all entries
- **Blocked files:** `.env`, `id_rsa`, `.pyc`, `__pycache__/`, `.git/` — never in ZIP
- **Filename sanitization:** Only `[a-zA-Z0-9_-]` in filename stems; no path separators in artifact filenames
- **Checksum integrity:** SHA-256 on every artifact; manifest hash over all artifact hashes

See [docs/security_review.md](docs/security_review.md) for the full security review.

---

## Data Sources

| Source | Type | Usage |
|---|---|---|
| Synthea | Synthetic FHIR R4 | Patient cohort (700 patients) |
| PubMed / NCBI E-utilities | Public API | Literature metadata |
| ClinicalTrials.gov API v2 | Public API | Trial records |
| CMS Coverage Database | Public | LCD/NCD coverage documents |
| RxNorm (NLM) | Public API/terminology | Medication normalization |
| ICD-10-CM | Terminology | Diagnosis coding |

All external APIs have versioned local fixture fallbacks for offline operation.

---

## Known Limitations

1. **Python 3.12 not verified in the build environment.** Developed on Python 3.14.6. Syntax is compatible with 3.12+.
2. **Docker Linux engine required for `docker build`.** Dockerfile and Compose configuration are present but untested in the development environment.
3. **Live retrieval is offline by default.** Fixtures cover the demo question. Other questions require live API access.
4. **No authentication.** Local-only prototype. Do not expose to the internet.
5. **DuckDB is single-writer.** Multi-process deployment requires switching to PostgreSQL.

---

## Phase Summary

| Phase | Deliverable | Status |
|---|---|---|
| 1 | Foundation, schemas, DuckDB, CI scaffold | Complete |
| 2 | PICO question builder, phenotype builder, RxNorm | Complete |
| 3 | Synthetic cohort simulation, attrition pipeline | Complete |
| 4 | Evidence retrieval, normalization, ranking, QA | Complete |
| 5 | Brief generation, 16-check QA, human review, Markdown export | Complete |
| 6 | PDF, PPTX, ZIP export, export security, deployment config | Complete |

---

## Documentation

| Document | Description |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Full system architecture |
| [docs/portfolio_case_study.md](docs/portfolio_case_study.md) | Portfolio case study (skills, decisions, trade-offs) |
| [docs/security_review.md](docs/security_review.md) | Security review |
| [docs/deployment.md](docs/deployment.md) | Deployment guide |
| [docs/brief_qa_framework.md](docs/brief_qa_framework.md) | QA check catalog |
| [docs/evidence_provenance.md](docs/evidence_provenance.md) | Evidence provenance model |
| [docs/human_review_workflow.md](docs/human_review_workflow.md) | Review state machine |
| [docs/phase5_verification_report.md](docs/phase5_verification_report.md) | Phase 5 verification |

---

*Johanna Fiola · johannafiola25@gmail.com*  
*Educational portfolio prototype. Not for clinical use.*
