"""FastAPI application entry point.

Run with:
    uvicorn src.api.main:app --reload --port 8000

API docs are available at:
    http://localhost:8000/docs   (Swagger UI)
    http://localhost:8000/redoc (ReDoc)
"""

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.api.routes import cohorts as cohort_routes
from src.api.routes import evidence as evidence_routes
from src.api.routes import fhir as fhir_routes
from src.api.routes import phenotypes as phenotype_routes
from src.api.routes import questions as question_routes
from src.api.routes import terminology as terminology_routes
from src.config.settings import get_settings

logger = logging.getLogger(__name__)


# ── Lifespan ───────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    settings = get_settings()
    logger.info(
        "Starting %s v%s (demo_mode=%s)",
        settings.app_name,
        settings.app_version,
        settings.is_demo_mode,
    )
    yield
    logger.info("Shutting down %s", settings.app_name)


# ── App ────────────────────────────────────────────────────────────────────────

settings = get_settings()

app = FastAPI(
    title="Clinical Question-Evidence Studio API",
    description=(
        "API for the Clinical Question-Evidence Studio portfolio prototype. "
        "Converts clinical research questions into structured phenotypes, "
        "synthetic cohorts, and evidence briefs. "
        "**This is an educational prototype using synthetic data only.**"
    ),
    version=settings.app_version,
    lifespan=lifespan,
    contact={
        "name": "Johanna Momole",
        "email": "johannafiola25@gmail.com",
    },
    license_info={"name": "MIT"},
    openapi_tags=[
        {"name": "system", "description": "Health checks and API metadata"},
        {"name": "questions", "description": "Clinical question parsing and PICO extraction"},
        {"name": "phenotypes", "description": "Computable phenotype construction"},
        {"name": "cohorts", "description": "Synthetic cohort generation"},
        {"name": "evidence", "description": "External evidence retrieval and search"},
        {"name": "briefs", "description": "Evidence brief generation"},
        {"name": "qa", "description": "Quality assurance and provenance"},
        {"name": "exports", "description": "Export generation (JSON, Markdown, PDF, PPTX)"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://app:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(question_routes.router)
app.include_router(phenotype_routes.router)
app.include_router(fhir_routes.router)
app.include_router(cohort_routes.router)
app.include_router(evidence_routes.router)
app.include_router(terminology_routes.router)


# ── Response models ────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    """API health check response."""

    status: str
    timestamp: datetime
    version: str
    demo_mode: bool
    environment: str


class APIInfoResponse(BaseModel):
    """High-level API metadata."""

    name: str
    version: str
    description: str
    demo_mode: bool
    disclaimer: str
    endpoints: list[dict[str, Any]]


# ── Routes ─────────────────────────────────────────────────────────────────────


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    summary="Health check",
    description="Returns API status and runtime configuration. Use this to verify the service is running.",
)
async def health_check() -> HealthResponse:
    cfg = get_settings()
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(UTC),
        version=cfg.app_version,
        demo_mode=cfg.is_demo_mode,
        environment=cfg.app_env,
    )


@app.get(
    "/info",
    response_model=APIInfoResponse,
    tags=["system"],
    summary="API metadata",
    description="Returns descriptive metadata about the API and available endpoint groups.",
)
async def api_info() -> APIInfoResponse:
    cfg = get_settings()
    return APIInfoResponse(
        name=cfg.app_name,
        version=cfg.app_version,
        description=(
            "Educational clinical informatics prototype. "
            "Uses synthetic patient data. Not for clinical use."
        ),
        demo_mode=cfg.is_demo_mode,
        disclaimer=(
            "This project uses entirely synthetic patient data and publicly available evidence. "
            "It is an educational portfolio prototype, has not been clinically validated, "
            "and does not provide medical advice."
        ),
        endpoints=[
            {"path": "/health", "method": "GET", "phase": "1", "status": "implemented"},
            {"path": "/info", "method": "GET", "phase": "1", "status": "implemented"},
            {"path": "/questions/parse", "method": "POST", "phase": "2", "status": "implemented"},
            {"path": "/questions/curated", "method": "GET", "phase": "2", "status": "implemented"},
            {"path": "/phenotypes/build", "method": "POST", "phase": "2", "status": "implemented"},
            {"path": "/fhir/datasets", "method": "GET", "phase": "3", "status": "implemented"},
            {"path": "/fhir/ingest", "method": "POST", "phase": "3", "status": "implemented"},
            {"path": "/cohorts/run", "method": "POST", "phase": "3", "status": "implemented"},
            {
                "path": "/cohorts/runs/{run_id}",
                "method": "GET",
                "phase": "3",
                "status": "implemented",
            },
            {"path": "/evidence/search", "method": "POST", "phase": "4", "status": "implemented"},
            {"path": "/evidence/sources", "method": "GET", "phase": "4", "status": "implemented"},
            {
                "path": "/evidence/runs/{run_id}",
                "method": "GET",
                "phase": "4",
                "status": "implemented",
            },
            {
                "path": "/evidence/{evidence_id}",
                "method": "GET",
                "phase": "4",
                "status": "implemented",
            },
            {
                "path": "/terminology/rxnorm/verify",
                "method": "POST",
                "phase": "4",
                "status": "implemented",
            },
            {"path": "/briefs/generate", "method": "POST", "phase": "5", "status": "planned"},
            {"path": "/qa/{run_id}", "method": "GET", "phase": "5", "status": "planned"},
            {"path": "/exports", "method": "POST", "phase": "6", "status": "planned"},
            {"path": "/runs/{run_id}", "method": "GET", "phase": "6", "status": "planned"},
        ],
    )
