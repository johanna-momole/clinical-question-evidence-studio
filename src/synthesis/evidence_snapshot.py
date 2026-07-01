"""Evidence snapshot: validated, immutable record set linking a brief to a retrieval run.

The snapshot is created before brief generation and is content-addressed via a stable
hash. Any change to the underlying retrieval run requires a new brief version.

Steps:
  1. Load evidence records from the repository (list[dict]).
  2. Validate each dict back into the appropriate EvidenceRecord subtype.
  3. Classify data origin per record.
  4. Reject records with critical provenance failures (missing content_hash when required).
  5. Build and hash the canonical snapshot.
"""

from __future__ import annotations

import uuid
from typing import Any

from src.schemas.brief import (
    DataOriginClass,
    EvidenceSnapshot,
    EvidenceSnapshotRecord,
)
from src.schemas.evidence import (
    ClinicalTrialRecord,
    CoverageRecord,
    EvidenceRecord,
    PublicationRecord,
)
from src.utils.exceptions import BriefGenerationError

# Fixture manifest versions that originated from captured public sources
# (PubMed / CT.gov / CMS articles served from versioned offline fixtures)
_CAPTURED_SOURCE_VERSIONS = frozenset(["1.0.0"])

# Manifest versions created for testing purposes only
_MANUAL_FIXTURE_VERSIONS: frozenset[str] = frozenset()


def _classify_origin(record: dict[str, Any]) -> DataOriginClass:
    """Classify a single record's data origin."""
    if not record.get("is_fixture_data", True):
        return "live_api"
    version = record.get("fixture_manifest_version")
    if version and version in _MANUAL_FIXTURE_VERSIONS:
        return "manually_constructed_fixture"
    return "captured_source_fixture"


def _aggregate_origin(origins: list[DataOriginClass]) -> DataOriginClass:
    unique = set(origins)
    if len(unique) == 1:
        return next(iter(unique))
    return "mixed"


def _reconstruct_record(raw: dict[str, Any]) -> EvidenceRecord:
    """Validate a raw dict back into the appropriate typed EvidenceRecord subclass."""
    source_type = raw.get("source_type", "")
    try:
        if source_type == "publication":
            return PublicationRecord.model_validate(raw)
        if source_type == "clinical_trial":
            return ClinicalTrialRecord.model_validate(raw)
        if source_type == "cms_coverage":
            return CoverageRecord.model_validate(raw)
        return EvidenceRecord.model_validate(raw)
    except Exception as exc:
        raise BriefGenerationError(
            f"Cannot validate evidence record id={raw.get('id')!r}: {exc}"
        ) from exc


def _check_critical_provenance(record: EvidenceRecord) -> list[str]:
    """Return a list of critical provenance failure messages (empty = OK)."""
    failures: list[str] = []
    if not record.id:
        failures.append("Missing record id")
    if not record.identifier:
        failures.append(f"Missing source identifier for record {record.id}")
    if record.is_fixture_data and not record.content_hash:
        failures.append(f"Fixture record {record.id} has no content_hash")
    return failures


def build_snapshot(
    raw_dicts: list[dict[str, Any]],
    retrieval_run_id: str,
    query_hash: str,
    source_statuses: dict[str, str] | None = None,
    qa_summary: dict[str, Any] | None = None,
) -> EvidenceSnapshot:
    """Build and return an immutable EvidenceSnapshot from repository-returned dicts.

    Raises BriefGenerationError if any record has critical provenance failures.
    """
    snapshot_records: list[EvidenceSnapshotRecord] = []
    origins: list[DataOriginClass] = []
    all_failures: list[str] = []

    for raw in raw_dicts:
        typed = _reconstruct_record(raw)
        failures = _check_critical_provenance(typed)
        if failures:
            all_failures.extend(failures)
            continue

        origin = _classify_origin(raw)
        origins.append(origin)

        warnings: list[str] = []
        if isinstance(typed, ClinicalTrialRecord) and not typed.has_results_posted:
            warnings.append("Trial results not yet posted — do not treat as efficacy evidence.")
        if isinstance(typed, CoverageRecord) and typed.document_type == "LCD":
            warnings.append(
                f"Local Coverage Determination: jurisdiction={typed.jurisdiction}. "
                "Not nationally applicable."
            )

        snapshot_records.append(
            EvidenceSnapshotRecord(
                evidence_id=typed.id,
                source_specific_id=typed.identifier,
                source_type=typed.source_type,
                source_name=typed.source_name,
                title=typed.title,
                content_hash=typed.content_hash,
                is_fixture_data=typed.is_fixture_data,
                fixture_manifest_version=getattr(typed, "fixture_manifest_version", None),
                data_origin=origin,
                retrieval_run_id=typed.retrieval_run_id,
                relevance_score=typed.relevance_score,
                tags=list(typed.tags),
                url=typed.url,
                warnings=warnings,
            )
        )

    if all_failures:
        raise BriefGenerationError(
            f"Cannot build snapshot: {len(all_failures)} critical provenance failure(s): "
            + "; ".join(all_failures[:5])
        )

    aggregate = _aggregate_origin(origins) if origins else "captured_source_fixture"

    return EvidenceSnapshot(
        snapshot_id=f"snap-{uuid.uuid4().hex[:8]}",
        retrieval_run_id=retrieval_run_id,
        query_hash=query_hash,
        records=snapshot_records,
        source_statuses=source_statuses or {},
        qa_summary=qa_summary or {},
        data_origin=aggregate,
    )


def get_snapshot_record_map(snapshot: EvidenceSnapshot) -> dict[str, EvidenceSnapshotRecord]:
    """Return a dict keyed by evidence_id for fast citation lookup."""
    return {r.evidence_id: r for r in snapshot.records}


def validate_source_ids(
    source_ids: list[str],
    snapshot: EvidenceSnapshot,
) -> list[str]:
    """Return list of source_ids that do NOT exist in the snapshot (BQ-002)."""
    valid_ids = {r.evidence_id for r in snapshot.records}
    return [sid for sid in source_ids if sid not in valid_ids]
