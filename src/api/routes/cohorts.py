"""FastAPI routes for synthetic cohort construction.

All patient data is synthetic. Results are labeled accordingly.
Phenotype must be approved (review_status='approved') before a cohort run is accepted.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.cohorts.service import get_cohort_service
from src.phenotypes.repository import PhenotypeRepository
from src.schemas.cohort import CohortConfiguration, CohortRun
from src.schemas.qa import QASummary
from src.utils.exceptions import (
    CohortRunNotFoundError,
    UnapprovedPhenotypeError,
    UnresolvedConceptError,
)

router = APIRouter(prefix="/cohorts", tags=["cohorts"])

_FIXTURE_DIR = Path("data/fixtures")


class CohortRunRequest(BaseModel):
    phenotype_id: str
    dataset_id: str = "synthetic-cohort-v1"
    reference_date: date = date(2025, 6, 1)
    min_age_years: int = 18
    observation_lookback_days: int = 365
    include_medication_exposure_filter: bool = False
    medication_lookback_days: int = 365
    require_lab_availability: bool = False
    lab_lookback_days: int = 365
    approve_for_demo: bool = False


class CohortRunResponse(BaseModel):
    cohort_run: CohortRun
    fhir_qa: QASummary
    cohort_qa: QASummary
    synthetic_data_notice: str = (
        "NOTICE: All results are derived from bundled synthetic (fictional) patient data. "
        "This application has NOT been clinically validated and must NOT be used for "
        "real patient care, treatment recommendations, or clinical decisions."
    )


@router.post("/run", response_model=CohortRunResponse)
def run_cohort(request: CohortRunRequest) -> CohortRunResponse:
    """Execute a synthetic cohort run against a registered FHIR dataset.

    The phenotype must have review_status='approved'. Set approve_for_demo=true
    to approve the phenotype structure for demonstration purposes only.
    Returns attrition steps, QA summary, and cohort demographics.
    """
    repo = PhenotypeRepository(_FIXTURE_DIR)
    try:
        phenotype = repo.load(request.phenotype_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Phenotype not found: {exc}") from exc

    svc = get_cohort_service()

    if request.approve_for_demo:
        phenotype = svc.approve_phenotype_for_demo(phenotype)

    config = CohortConfiguration(
        reference_date=request.reference_date,
        min_age_years=request.min_age_years,
        observation_lookback_days=request.observation_lookback_days,
        include_medication_exposure_filter=request.include_medication_exposure_filter,
        medication_lookback_days=request.medication_lookback_days,
        require_lab_availability=request.require_lab_availability,
        lab_lookback_days=request.lab_lookback_days,
        dataset_id=request.dataset_id,
    )

    try:
        cohort_run, fhir_qa, cohort_qa = svc.run(phenotype, config)
    except UnapprovedPhenotypeError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Phenotype is not approved for cohort execution: {exc}. "
                "Set approve_for_demo=true to approve for synthetic demo use."
            ),
        ) from exc
    except UnresolvedConceptError as exc:
        raise HTTPException(status_code=422, detail=f"Phenotype concept error: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cohort execution failed: {exc}") from exc

    return CohortRunResponse(
        cohort_run=cohort_run,
        fhir_qa=fhir_qa,
        cohort_qa=cohort_qa,
    )


@router.get("/runs/{run_id}", response_model=CohortRun)
def get_cohort_run(run_id: str) -> CohortRun:
    """Retrieve a previously executed cohort run by run_id."""
    svc = get_cohort_service()
    try:
        return svc.get_run(run_id)
    except CohortRunNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"No cohort run found with run_id='{run_id}' in this session.",
        ) from exc


@router.get("/runs", response_model=list[str])
def list_cohort_runs() -> list[str]:
    """List run IDs of all cohort runs executed in this session."""
    return get_cohort_service().list_run_ids()
