"""FHIR resource loader: reads individual resources, Bundles, and directories.

Designed for offline use — no network access. All resources processed are synthetic.
Errors are captured and returned rather than raised, to allow partial-load scenarios.
Processing order is deterministic (alphabetical by file name, by resource.id within file).
"""

from __future__ import annotations

import json
from pathlib import Path

from src.schemas.fhir import FHIRIngestionError

_SUPPORTED_TYPES = frozenset(
    [
        "Patient",
        "Condition",
        "Encounter",
        "Observation",
        "MedicationRequest",
        "MedicationStatement",
        "Procedure",
    ]
)


class LoadedResource:
    """A raw FHIR resource dict plus its provenance metadata."""

    __slots__ = ("resource", "source_file", "resource_type", "resource_id")

    def __init__(self, resource: dict, source_file: str) -> None:
        self.resource = resource
        self.source_file = source_file
        self.resource_type: str = resource.get("resourceType", "")
        self.resource_id: str = resource.get("id", "")


class LoadResult:
    """Collected outcome of a FHIR load operation."""

    def __init__(self) -> None:
        self.resources: list[LoadedResource] = []
        self.errors: list[FHIRIngestionError] = []
        self._seen_ids: dict[str, str] = {}  # "Type/id" → source_file

    def add_resource(self, res: LoadedResource) -> None:
        """Register a resource, detecting duplicates across files."""
        key = f"{res.resource_type}/{res.resource_id}"
        if key in self._seen_ids:
            self.errors.append(
                FHIRIngestionError(
                    file_name=res.source_file,
                    resource_id=res.resource_id,
                    resource_type=res.resource_type,
                    error_type="duplicate_resource_id",
                    message=(
                        f"Duplicate resource id '{key}' already seen in "
                        f"{self._seen_ids[key]}; skipping this occurrence"
                    ),
                    is_fatal=True,  # fatal = dropped
                )
            )
        else:
            self._seen_ids[key] = res.source_file
            self.resources.append(res)

    def add_error(self, err: FHIRIngestionError) -> None:
        self.errors.append(err)


def _extract_resources_from_object(obj: dict, source_file: str, result: LoadResult) -> None:
    """Extract resources from a parsed JSON object (either a resource or a Bundle)."""
    resource_type = obj.get("resourceType", "")

    if resource_type == "Bundle":
        entries = obj.get("entry", [])
        for entry in entries:
            child = entry.get("resource") if isinstance(entry, dict) else None
            if child and isinstance(child, dict):
                _extract_resources_from_object(child, source_file, result)
        return

    # Single resource
    if not resource_type:
        result.add_error(
            FHIRIngestionError(
                file_name=source_file,
                resource_type=None,
                error_type="other",
                message="JSON object has no 'resourceType' field — not a FHIR resource",
                is_fatal=True,
            )
        )
        return

    if resource_type not in _SUPPORTED_TYPES:
        result.add_error(
            FHIRIngestionError(
                file_name=source_file,
                resource_type=resource_type,
                error_type="unsupported_resource_type",
                message=f"Resource type '{resource_type}' is not supported; resource skipped",
                is_fatal=True,
            )
        )
        return

    resource_id = obj.get("id")
    if not resource_id:
        result.add_error(
            FHIRIngestionError(
                file_name=source_file,
                resource_type=resource_type,
                error_type="missing_resource_id",
                message=f"'{resource_type}' resource has no 'id' field; resource skipped",
                is_fatal=True,
            )
        )
        return

    result.add_resource(LoadedResource(obj, source_file))


def load_file(path: Path) -> LoadResult:
    """Load all FHIR resources from a single JSON file (resource or Bundle)."""
    result = LoadResult()
    file_name = path.name
    try:
        text = path.read_text(encoding="utf-8")
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        result.add_error(
            FHIRIngestionError(
                file_name=file_name,
                error_type="malformed_json",
                message=f"JSON parse error: {exc}",
                is_fatal=True,
            )
        )
        return result
    except Exception as exc:
        result.add_error(
            FHIRIngestionError(
                file_name=file_name,
                error_type="other",
                message=f"File read error: {exc}",
                is_fatal=True,
            )
        )
        return result

    if isinstance(obj, dict):
        _extract_resources_from_object(obj, file_name, result)
    else:
        result.add_error(
            FHIRIngestionError(
                file_name=file_name,
                error_type="other",
                message="Top-level JSON is not an object — not a valid FHIR resource or Bundle",
                is_fatal=True,
            )
        )

    return result


def load_directory(directory: Path) -> LoadResult:
    """Load all *.json files from a directory, sorted alphabetically for determinism."""
    combined = LoadResult()
    json_files = sorted(directory.glob("*.json"))
    for path in json_files:
        if path.name == "dataset_info.json":
            continue  # skip the metadata manifest
        file_result = load_file(path)
        for res in file_result.resources:
            combined.add_resource(res)
        for err in file_result.errors:
            combined.add_error(err)
    return combined
