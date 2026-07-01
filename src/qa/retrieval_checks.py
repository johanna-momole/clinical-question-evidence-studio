"""Retrieval-level QA checks for an evidence retrieval run.

Checks operate on run-level metadata (source statuses, error counts, record counts)
rather than on individual evidence record content — those are covered by evidence_checks.py.
"""

from __future__ import annotations

from typing import Literal

from src.schemas.qa import QAResult, QASummary
from src.schemas.retrieval import EvidenceSourceStatus, RetrievalRun


def _qa(
    check_id: str,
    check_name: str,
    status: Literal["passed", "warning", "failed", "not_applicable"],
    description: str,
    severity: Literal["critical", "major", "minor", "info"],
    details: str | None = None,
    affected: list[str] | None = None,
) -> QAResult:
    return QAResult(
        check_id=check_id,
        check_name=check_name,
        category="evidence_quality",
        status=status,
        description=description,
        severity=severity,
        details=details,
        affected_records=affected or [],
    )


def run_retrieval_checks(run: RetrievalRun) -> QASummary:
    """Run QA checks on a completed RetrievalRun and return a QASummary."""
    results: list[QAResult] = []
    statuses: list[EvidenceSourceStatus] = run.source_statuses

    # ------------------------------------------------------------------
    # RQ-001: At least one source returned records
    # ------------------------------------------------------------------
    total_retrieved = sum(s.records_retrieved for s in statuses)
    if total_retrieved == 0:
        results.append(
            _qa(
                "rq-001",
                "At least one record retrieved",
                "failed",
                "At least one source must return at least one record for the run to be usable",
                "critical",
                details="Zero records retrieved across all sources. "
                "Check fixture files and manifest, or enable additional sources.",
            )
        )
    else:
        results.append(
            _qa(
                "rq-001",
                "At least one record retrieved",
                "passed",
                "At least one source must return at least one record",
                "info",
                details=f"Total records retrieved: {total_retrieved}",
            )
        )

    # ------------------------------------------------------------------
    # RQ-002: No source returned a fatal error
    # ------------------------------------------------------------------
    fatal_sources: list[str] = [
        s.source_name for s in statuses if any(e.is_fatal_for_source for e in s.errors)
    ]
    if fatal_sources:
        results.append(
            _qa(
                "rq-002",
                "No fatal source errors",
                "warning",
                "A fatal adapter error caused a source to contribute zero records",
                "major",
                details=f"Sources with fatal errors: {fatal_sources}",
                affected=fatal_sources,
            )
        )
    else:
        results.append(
            _qa(
                "rq-002",
                "No fatal source errors",
                "passed",
                "A fatal adapter error caused a source to contribute zero records",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # RQ-003: All requested sources were queried
    # ------------------------------------------------------------------
    requested = set(run.request.sources)
    queried = {s.source_name for s in statuses}
    missing = requested - queried
    if missing:
        results.append(
            _qa(
                "rq-003",
                "All requested sources were queried",
                "failed",
                "Every source listed in the request must have a status entry",
                "major",
                details=f"Sources not queried: {sorted(missing)}",
                affected=sorted(str(s) for s in missing),
            )
        )
    else:
        results.append(
            _qa(
                "rq-003",
                "All requested sources were queried",
                "passed",
                "Every source listed in the request must have a status entry",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # RQ-004: Query provenance hash matches run's embedded query hash
    # ------------------------------------------------------------------
    if run.provenance.query_hash != run.query.query_hash:
        results.append(
            _qa(
                "rq-004",
                "Provenance hash matches query hash",
                "failed",
                "The query_hash in RetrievalProvenance must match the EvidenceQuery.query_hash",
                "critical",
                details=(
                    f"Provenance hash: {run.provenance.query_hash}, "
                    f"Query hash: {run.query.query_hash}. "
                    "This indicates a mismatch between the query used and what was logged."
                ),
            )
        )
    else:
        results.append(
            _qa(
                "rq-004",
                "Provenance hash matches query hash",
                "passed",
                "The query_hash in RetrievalProvenance must match the EvidenceQuery.query_hash",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # RQ-005: Retrieval mode is 'offline_fixture' in demo environment
    # ------------------------------------------------------------------
    if run.provenance.retrieval_mode != "offline_fixture":
        results.append(
            _qa(
                "rq-005",
                "Demo environment uses offline fixtures",
                "warning",
                "This application's test suite runs in offline_fixture mode only. "
                "Live mode is supported but should be explicitly enabled.",
                "minor",
                details=f"retrieval_mode='{run.provenance.retrieval_mode}' — "
                "expected 'offline_fixture' for demo/test runs.",
            )
        )
    else:
        results.append(
            _qa(
                "rq-005",
                "Demo environment uses offline fixtures",
                "passed",
                "retrieval_mode is 'offline_fixture' as expected",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # RQ-006: Record counts after dedup are not higher than retrieved
    # ------------------------------------------------------------------
    if run.total_records_after_dedup > run.total_records_retrieved:
        results.append(
            _qa(
                "rq-006",
                "Post-dedup count <= retrieved count",
                "failed",
                "Records after deduplication cannot exceed total records retrieved",
                "critical",
                details=(
                    f"after_dedup={run.total_records_after_dedup} > "
                    f"retrieved={run.total_records_retrieved}"
                ),
            )
        )
    else:
        results.append(
            _qa(
                "rq-006",
                "Post-dedup count <= retrieved count",
                "passed",
                "Records after deduplication cannot exceed total records retrieved",
                "info",
                details=(
                    f"retrieved={run.total_records_retrieved}, "
                    f"after_dedup={run.total_records_after_dedup}"
                ),
            )
        )

    return QASummary(run_id=run.run_id, results=results)
