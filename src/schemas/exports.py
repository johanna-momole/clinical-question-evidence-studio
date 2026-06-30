"""Pydantic schemas for export manifest and output file tracking."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


ExportFormat = Literal["json", "markdown", "pdf", "pptx"]


class ExportManifest(BaseModel):
    """Tracks the requested and completed export outputs for a pipeline run."""

    run_id: str = Field(..., description="Pipeline run identifier")
    formats_requested: list[ExportFormat] = Field(
        default_factory=list, description="Export formats the user requested"
    )
    formats_completed: list[ExportFormat] = Field(
        default_factory=list, description="Export formats successfully generated"
    )
    export_timestamp: datetime = Field(default_factory=_utcnow)
    file_paths: dict[str, str] = Field(
        default_factory=dict, description="ExportFormat -> absolute file path mapping"
    )
    errors: list[str] = Field(default_factory=list, description="Errors encountered during export")
    total_size_bytes: int | None = Field(
        None, ge=0, description="Combined size of all exported files"
    )

    @property
    def all_succeeded(self) -> bool:
        """True when all requested formats were successfully generated."""
        return set(self.formats_requested) == set(self.formats_completed)
