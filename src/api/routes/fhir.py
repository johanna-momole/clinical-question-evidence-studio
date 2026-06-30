"""FastAPI routes for FHIR dataset management.

All data served is synthetic only. Endpoints expose metadata and ingestion control.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.fhir.service import get_fhir_service
from src.fhir.service import list_datasets as _list_datasets
from src.schemas.fhir import FHIRIngestionResult, SyntheticDatasetInfo
from src.utils.exceptions import DatasetNotFoundError

router = APIRouter(prefix="/fhir", tags=["fhir"])


class DatasetListResponse(BaseModel):
    datasets: list[SyntheticDatasetInfo]
    note: str = (
        "All datasets contain synthetic (fictional) patient data generated "
        "from a seeded random process. No real patient information is present."
    )


@router.get("/datasets", response_model=DatasetListResponse)
def list_datasets() -> DatasetListResponse:
    """List available synthetic FHIR datasets."""
    datasets = _list_datasets()
    return DatasetListResponse(datasets=datasets)


class IngestRequest(BaseModel):
    dataset_id: str
    force_reload: bool = False


@router.post("/ingest", response_model=FHIRIngestionResult)
def ingest_dataset(request: IngestRequest) -> FHIRIngestionResult:
    """Ingest a synthetic FHIR dataset into the in-memory analytical store.

    Idempotent: re-ingesting the same dataset_id replaces all prior rows.
    """
    svc = get_fhir_service()
    try:
        result = svc.ingest(request.dataset_id, force_reload=request.force_reload)
    except DatasetNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Dataset '{request.dataset_id}' not found in the registered catalog.",
        ) from exc
    return result


@router.get("/datasets/{dataset_id}", response_model=FHIRIngestionResult | None)
def get_dataset_status(dataset_id: str) -> FHIRIngestionResult | None:
    """Return the most recent ingestion result for a dataset, or 404 if never ingested."""
    svc = get_fhir_service()
    result = svc.get_last_ingestion_result(dataset_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Dataset '{dataset_id}' has not been ingested in this session.",
        )
    return result
