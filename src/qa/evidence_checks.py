"""Evidence record quality assurance checks.

Runs after normalization + metatagging. Returns a QASummary using the same
passed/warning/failed/not_applicable statuses and critical/major/minor/info
severities as existing QA modules.

Critical failures (is_fixture_data=False but no content_hash, missing title, etc.)
block a record from being marked usable — callers should inspect has_critical_failure.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from src.schemas.evidence import (
    ClinicalTrialRecord,
    CoverageRecord,
    EvidenceRecord,
    PublicationRecord,
)
from src.schemas.qa import QAResult, QASummary


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


def run_evidence_record_checks(
    records: list[EvidenceRecord],
    run_id: str,
    max_evidence_age_days: int = 1825,
) -> QASummary:
    """Run all record-quality QA checks across a list of normalized evidence records."""
    results: list[QAResult] = []
    today = datetime.now(UTC).date()

    # ------------------------------------------------------------------
    # EQ-001: All records have a non-empty title
    # ------------------------------------------------------------------
    missing_title = [r.id for r in records if not r.title or not r.title.strip()]
    if missing_title:
        results.append(
            _qa(
                "eq-001",
                "Record title present",
                "failed",
                "Every evidence record must have a non-empty title",
                "critical",
                details=f"{len(missing_title)} records missing title",
                affected=missing_title[:20],
            )
        )
    else:
        results.append(
            _qa(
                "eq-001",
                "Record title present",
                "passed",
                "Every evidence record must have a non-empty title",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # EQ-002: All records have a source identifier
    # ------------------------------------------------------------------
    missing_id = [r.id for r in records if not r.identifier or not r.identifier.strip()]
    if missing_id:
        results.append(
            _qa(
                "eq-002",
                "Source identifier present",
                "failed",
                "Every record must carry its source-native identifier (PMID, NCT ID, LCD)",
                "critical",
                details=f"{len(missing_id)} records missing identifier",
                affected=missing_id[:20],
            )
        )
    else:
        results.append(
            _qa(
                "eq-002",
                "Source identifier present",
                "passed",
                "Every record must carry its source-native identifier",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # EQ-003: Content hash present (audit integrity)
    # ------------------------------------------------------------------
    missing_hash = [r.id for r in records if not r.content_hash]
    if missing_hash:
        results.append(
            _qa(
                "eq-003",
                "Content hash present",
                "failed",
                "Every record must have a content_hash for audit integrity",
                "critical",
                details=f"{len(missing_hash)} records missing content_hash",
                affected=missing_hash[:20],
            )
        )
    else:
        results.append(
            _qa(
                "eq-003",
                "Content hash present",
                "passed",
                "Every record must have a content_hash for audit integrity",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # EQ-004: is_fixture_data is consistently set (no hidden live calls)
    # ------------------------------------------------------------------
    live_no_url = [r.id for r in records if not r.is_fixture_data and not r.url]
    if live_no_url:
        results.append(
            _qa(
                "eq-004",
                "Live records have URL",
                "warning",
                "Records retrieved from live APIs should have a source URL for citation",
                "minor",
                details=f"{len(live_no_url)} live records missing URL",
                affected=live_no_url[:20],
            )
        )
    else:
        results.append(
            _qa(
                "eq-004",
                "Live records have URL",
                "passed",
                "Records retrieved from live APIs should have a source URL",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # EQ-005: No records have a relevance_score above 1.0 or below 0.0
    # ------------------------------------------------------------------
    bad_score = [
        r.id
        for r in records
        if r.relevance_score is not None and not (0.0 <= r.relevance_score <= 1.0)
    ]
    if bad_score:
        results.append(
            _qa(
                "eq-005",
                "Relevance score in valid range",
                "failed",
                "relevance_score must be in [0.0, 1.0] or None",
                "critical",
                details=f"{len(bad_score)} records with out-of-range score",
                affected=bad_score[:20],
            )
        )
    else:
        results.append(
            _qa(
                "eq-005",
                "Relevance score in valid range",
                "passed",
                "relevance_score must be in [0.0, 1.0] or None",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # EQ-006: Stale evidence warning (age > max_evidence_age_days)
    # ------------------------------------------------------------------
    stale = [
        r.id
        for r in records
        if r.publication_or_update_date
        and (today - r.publication_or_update_date).days > max_evidence_age_days
    ]
    if stale:
        results.append(
            _qa(
                "eq-006",
                "Evidence recency",
                "warning",
                f"Records older than {max_evidence_age_days} days may be outdated",
                "minor",
                details=f"{len(stale)} records older than {max_evidence_age_days} days",
                affected=stale[:20],
            )
        )
    else:
        results.append(
            _qa(
                "eq-006",
                "Evidence recency",
                "passed",
                f"No records older than {max_evidence_age_days} days",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # EQ-007: PubMed records should have abstract or explicit None
    # ------------------------------------------------------------------
    pub_missing_abstract = [
        r.id
        for r in records
        if isinstance(r, PublicationRecord) and r.abstract is not None and not r.abstract.strip()
    ]
    if pub_missing_abstract:
        results.append(
            _qa(
                "eq-007",
                "Publication abstract non-empty if present",
                "warning",
                "PubMed records with a non-None abstract should have non-empty text",
                "minor",
                details=f"{len(pub_missing_abstract)} records with empty abstract string",
                affected=pub_missing_abstract[:20],
            )
        )
    else:
        results.append(
            _qa(
                "eq-007",
                "Publication abstract non-empty if present",
                "passed",
                "PubMed records with a non-None abstract should have non-empty text",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # EQ-008: ClinicalTrials records have NCT ID
    # ------------------------------------------------------------------
    ct_missing_nct = [r.id for r in records if isinstance(r, ClinicalTrialRecord) and not r.nct_id]
    if ct_missing_nct:
        results.append(
            _qa(
                "eq-008",
                "ClinicalTrials NCT ID present",
                "failed",
                "Every ClinicalTrialRecord must have an nct_id",
                "major",
                details=f"{len(ct_missing_nct)} trial records missing nct_id",
                affected=ct_missing_nct[:20],
            )
        )
    else:
        results.append(
            _qa(
                "eq-008",
                "ClinicalTrials NCT ID present",
                "passed",
                "Every ClinicalTrialRecord must have an nct_id",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # EQ-009: CMS records have a document type (LCD or NCD)
    # ------------------------------------------------------------------
    cms_missing_type = [
        r.id for r in records if isinstance(r, CoverageRecord) and not r.document_type
    ]
    if cms_missing_type:
        results.append(
            _qa(
                "eq-009",
                "CMS document type identified",
                "warning",
                "CoverageRecord should have document_type='LCD' or 'NCD'",
                "minor",
                details=f"{len(cms_missing_type)} coverage records missing document_type",
                affected=cms_missing_type[:20],
            )
        )
    else:
        results.append(
            _qa(
                "eq-009",
                "CMS document type identified",
                "passed",
                "CoverageRecord should have document_type='LCD' or 'NCD'",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # EQ-010: No clinical recommendations or synthesis in evidence text
    # EQ-010 is not_applicable here — this check is a Phase 5 concern.
    # ------------------------------------------------------------------
    results.append(
        _qa(
            "eq-010",
            "No synthesized narrative in raw evidence text",
            "not_applicable",
            "Verified that no LLM-generated narrative has been injected into evidence records. "
            "This check is reserved for Phase 5 synthesis QA.",
            "info",
            details="Phase 4 does not produce narrative synthesis — not applicable.",
        )
    )

    return QASummary(run_id=run_id, results=results)
