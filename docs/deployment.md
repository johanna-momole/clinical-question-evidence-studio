# Deployment Guide

**Clinical Question-to-Evidence Studio — Phase 6**

> This project is a local portfolio prototype. The instructions below describe how to run it locally via Docker Compose or directly with Python. No cloud deployment is included.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12+ | 3.14.x also confirmed working |
| pip | 24+ | Bundled with Python |
| Docker Desktop | 27+ | Linux engine required for `docker build` |
| Git | 2.40+ | For cloning |

---

## Quick Start (Python, no Docker)

```bash
# 1. Clone
git clone <repo-url>
cd clinical-question-evidence-studio

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate          # Linux/macOS
.venv\Scripts\activate             # Windows

# 3. Install
pip install -e ".[dev]"

# 4. Verify
pytest                             # 496 tests
ruff check .                       # 0 errors
python scripts/run_end_to_end_demo.py   # 11-stage demo

# 5. Launch Streamlit UI
streamlit run app/Home.py

# 6. Launch FastAPI (optional, separate terminal)
uvicorn src.api.main:app --reload --port 8000
```

---

## Environment Variables

All environment variables have safe defaults for local/demo use. No secrets are required to run the default demo.

| Variable | Default | Required | Description |
|---|---|---|---|
| `STUDIO_ENV` | `development` | No | `development` \| `production` |
| `STUDIO_DB_PATH` | `data/studio.duckdb` | No | DuckDB file path |
| `STUDIO_LOG_LEVEL` | `INFO` | No | Python logging level |
| `PUBMED_LIVE_RETRIEVAL` | `false` | No | Enable live PubMed API calls |
| `NCBI_API_KEY` | *(empty)* | No* | NCBI E-utilities API key. Required only when `PUBMED_LIVE_RETRIEVAL=true` |
| `CLINICALTRIALS_LIVE_RETRIEVAL` | `false` | No | Enable live ClinicalTrials.gov API calls |
| `CMS_LIVE_RETRIEVAL` | `false` | No | Enable live CMS coverage API calls |
| `STUDIO_MAX_EXPORT_SIZE_MB` | `50` | No | Maximum ZIP bundle size (MB) |
| `STUDIO_EXPORT_DIR` | *(empty)* | No | If set, export files are written here. Unset = in-memory only |

**Security note:** Never commit `.env` files. The `.gitignore` already excludes `.env*`.

### Sample `.env` for local development

```
STUDIO_ENV=development
STUDIO_DB_PATH=data/studio.duckdb
STUDIO_LOG_LEVEL=DEBUG
PUBMED_LIVE_RETRIEVAL=false
```

---

## Docker Compose

```bash
# Build and start
docker compose up --build

# Run in background
docker compose up -d

# Check logs
docker compose logs -f studio

# Stop
docker compose down
```

The Compose file starts two services:
- `studio` — Streamlit UI on port 8501
- `api` — FastAPI server on port 8000

### Health checks

```bash
# Streamlit health
curl http://localhost:8501/_stcore/health

# FastAPI health
curl http://localhost:8000/health

# FastAPI info (lists all endpoints and their implementation status)
curl http://localhost:8000/info | python -m json.tool
```

---

## Docker Image Details

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .
COPY . .
EXPOSE 8501 8000
```

The image:
- Uses `python:3.12-slim` base
- Installs only production dependencies (not `[dev]` extras)
- Does not include `.env*` files, `.venv/`, or `__pycache__/`
- Mounts `data/` as a volume so the DuckDB file persists across container restarts

---

## Release Checklist

Before tagging a release:

- [ ] `pytest` — all tests pass (currently 496/496)
- [ ] `ruff check .` — zero errors
- [ ] `ruff format --check .` — zero reformats needed
- [ ] `mypy src/ --ignore-missing-imports` — zero type errors
- [ ] `python scripts/run_end_to_end_demo.py` — all 11 stages pass
- [ ] Run demo script twice and confirm identical content hashes (determinism check)
- [ ] Verify `docker build` succeeds (requires Linux Docker engine)
- [ ] Verify `docker compose up` starts both services without errors
- [ ] Confirm `/health` and `/info` endpoints respond on both ports
- [ ] Review `docs/phase6_verification_report.md` — no open blockers
- [ ] Confirm no secrets committed: `git log --all -- '*.env*'` returns nothing
- [ ] Tag release: `git tag -a v0.6.0 -m "Phase 6 complete"`

---

## Architecture Constraints for Deployment

1. **DuckDB is a single-process database.** Running multiple concurrent Streamlit or FastAPI workers against the same DuckDB file will cause lock contention. For a multi-process deployment, switch to PostgreSQL and update the repository layer.

2. **Exports are in-memory by default.** Setting `STUDIO_EXPORT_DIR` writes artifacts to disk. Ensure the target directory is writable and has adequate space (ZIP bundles can be 1–5 MB each).

3. **Live API retrieval is off by default.** Enabling `PUBMED_LIVE_RETRIEVAL=true` requires a stable internet connection and an NCBI API key (free, rate-limited to 10 req/s with key).

4. **No authentication is implemented.** This is a local prototype. Do not expose it to the internet without adding authentication.

---

## Schema and Generator Versions

| Component | Version |
|---|---|
| EvidenceBrief schema | 5.0 |
| Export schema | 6.0.0 |
| Generator version | 1.0.0 |
| Fixture manifest | 1.0.0 |

Schema versions appear in every export artifact and in the `/info` endpoint response.
