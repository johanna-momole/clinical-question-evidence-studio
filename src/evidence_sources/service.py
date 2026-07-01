"""Evidence source service: dispatches retrieval requests to registered adapters.

Partial failure is isolated — if one source adapter fails, other sources still proceed.
Errors from each source are collected in ``RetrievalError`` records, never swallowed.
"""

from __future__ import annotations

import time

from src.evidence_sources.base import RawFetchResult
from src.evidence_sources.registry import get_adapter
from src.schemas.evidence import EvidenceSourceName, RawEvidenceRecord
from src.schemas.retrieval import EvidenceSourceStatus, RetrievalError, SourceSpecificQuery
from src.utils.exceptions import RetrievalSourceError


def fetch_all_sources(
    source_queries: list[SourceSpecificQuery],
    run_id: str,
    max_results_per_source: int = 50,
) -> tuple[list[RawEvidenceRecord], list[EvidenceSourceStatus]]:
    """Dispatch source-specific queries to each registered adapter.

    Returns (all_raw_records, source_status_list).  Partial failures are
    captured in EvidenceSourceStatus.errors — they never raise to the caller.
    """
    all_records: list[RawEvidenceRecord] = []
    statuses: list[EvidenceSourceStatus] = []

    for sq in source_queries:
        source_name: EvidenceSourceName = sq.source_name
        t0 = time.monotonic()
        errors: list[RetrievalError] = []
        records: list[RawEvidenceRecord] = []
        cache_hit = False

        try:
            adapter = get_adapter(source_name)
            result: RawFetchResult = adapter.fetch(sq, run_id)
            records = result.records[:max_results_per_source]
            errors = result.errors
            cache_hit = result.cache_hit
        except RetrievalSourceError as exc:
            errors.append(
                RetrievalError(
                    source_name=source_name,
                    error_type="network_error",
                    message=str(exc),
                    is_fatal_for_source=True,
                )
            )
        except Exception as exc:
            errors.append(
                RetrievalError(
                    source_name=source_name,
                    error_type="parse_error",
                    message=f"Unexpected error from {source_name} adapter: {exc}",
                    is_fatal_for_source=True,
                )
            )

        duration_ms = int((time.monotonic() - t0) * 1000)
        all_records.extend(records)
        statuses.append(
            EvidenceSourceStatus(
                source_name=source_name,
                records_retrieved=len(records),
                records_after_normalization=0,  # filled in by caller after normalization
                errors=errors,
                cache_hit=cache_hit,
                duration_ms=duration_ms,
            )
        )

    return all_records, statuses
