"""DuckDB persistence repository for Phase 5 evidence briefs and review workflow.

Tables:
  1. evidence_snapshots       — one row per EvidenceSnapshot
  2. snapshot_records         — one row per EvidenceSnapshotRecord
  3. evidence_briefs          — one row per EvidenceBrief version
  4. generated_claims         — one row per GeneratedClaim
  5. claim_citations          — one row per ClaimCitation
  6. evidence_gaps            — one row per EvidenceGap
  7. brief_qa_results         — one row per BQ check result
  8. brief_reviews            — one row per BriefReviewRecord
  9. brief_audit_log          — one row per BriefAuditRecord

All timestamp columns are VARCHAR with ISO 8601 UTC strings (project convention).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import duckdb

from src.schemas.brief import (
    BriefReviewRecord,
    BriefReviewStatus,
    EvidenceBrief,
    EvidenceGap,
    EvidenceSnapshot,
    EvidenceSnapshotRecord,
    GeneratedClaim,
)
from src.utils.exceptions import BriefNotFoundError


def _ts(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.isoformat()


_DDL = """
CREATE TABLE IF NOT EXISTS evidence_snapshots (
    snapshot_id         VARCHAR PRIMARY KEY,
    retrieval_run_id    VARCHAR NOT NULL,
    query_hash          VARCHAR NOT NULL,
    data_origin         VARCHAR NOT NULL,
    snapshot_hash       VARCHAR NOT NULL,
    source_statuses_json TEXT NOT NULL,
    qa_summary_json     TEXT NOT NULL,
    created_at          VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshot_records (
    snapshot_id             VARCHAR NOT NULL,
    evidence_id             VARCHAR NOT NULL,
    source_specific_id      VARCHAR NOT NULL,
    source_type             VARCHAR NOT NULL,
    source_name             VARCHAR,
    title                   TEXT NOT NULL,
    content_hash            VARCHAR,
    is_fixture_data         BOOLEAN NOT NULL,
    fixture_manifest_version VARCHAR,
    data_origin             VARCHAR NOT NULL,
    retrieval_run_id        VARCHAR,
    relevance_score         DOUBLE,
    tags_json               TEXT NOT NULL,
    url                     TEXT,
    warnings_json           TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS evidence_briefs (
    brief_id                VARCHAR NOT NULL,
    version                 INTEGER NOT NULL,
    schema_version          VARCHAR NOT NULL,
    question_id             VARCHAR NOT NULL,
    phenotype_id            VARCHAR NOT NULL,
    phenotype_version       VARCHAR NOT NULL,
    cohort_run_id           VARCHAR,
    evidence_run_id         VARCHAR NOT NULL,
    evidence_snapshot_id    VARCHAR NOT NULL,
    evidence_snapshot_hash  VARCHAR NOT NULL,
    generated_at            VARCHAR NOT NULL,
    generation_mode         VARCHAR NOT NULL,
    model_provider          VARCHAR,
    model_name              VARCHAR,
    prompt_version          VARCHAR,
    model_parameters_json   TEXT NOT NULL,
    data_origin             VARCHAR NOT NULL,
    data_notice             TEXT NOT NULL,
    limitations_json        TEXT NOT NULL,
    disclaimer              TEXT NOT NULL,
    qa_summary_json         TEXT NOT NULL,
    human_review_status     VARCHAR NOT NULL,
    content_hash            VARCHAR NOT NULL,
    provenance_json         TEXT,
    full_brief_json         TEXT NOT NULL,
    PRIMARY KEY (brief_id, version)
);

CREATE TABLE IF NOT EXISTS generated_claims (
    brief_id        VARCHAR NOT NULL,
    brief_version   INTEGER NOT NULL,
    claim_id        VARCHAR NOT NULL,
    text            TEXT NOT NULL,
    claim_type      VARCHAR NOT NULL,
    dimension       VARCHAR NOT NULL,
    evidence_basis  VARCHAR NOT NULL,
    source_ids_json TEXT NOT NULL,
    design_limitations_json TEXT NOT NULL,
    uncertainty_note TEXT,
    PRIMARY KEY (brief_id, brief_version, claim_id)
);

CREATE TABLE IF NOT EXISTS claim_citations (
    brief_id            VARCHAR NOT NULL,
    brief_version       INTEGER NOT NULL,
    claim_id            VARCHAR NOT NULL,
    citation_number     INTEGER NOT NULL,
    source_id           VARCHAR NOT NULL,
    source_specific_id  VARCHAR NOT NULL,
    source_type         VARCHAR NOT NULL,
    title               TEXT NOT NULL,
    url                 TEXT,
    support_type        VARCHAR NOT NULL,
    locator             TEXT,
    review_status       VARCHAR NOT NULL,
    PRIMARY KEY (brief_id, brief_version, claim_id, source_id)
);

CREATE TABLE IF NOT EXISTS evidence_gaps (
    brief_id            VARCHAR NOT NULL,
    brief_version       INTEGER NOT NULL,
    gap_id              VARCHAR NOT NULL,
    description         TEXT NOT NULL,
    dimension           VARCHAR NOT NULL,
    retrieval_run_id    VARCHAR NOT NULL,
    sources_searched_json TEXT NOT NULL,
    source_statuses_json TEXT NOT NULL,
    query_strings_json  TEXT NOT NULL,
    filters_json        TEXT NOT NULL,
    date_range          VARCHAR,
    result_counts_json  TEXT NOT NULL,
    failed_sources_json TEXT NOT NULL,
    limitations_json    TEXT NOT NULL,
    generated_at        VARCHAR NOT NULL,
    PRIMARY KEY (brief_id, brief_version, gap_id)
);

CREATE TABLE IF NOT EXISTS brief_qa_results (
    brief_id    VARCHAR NOT NULL,
    brief_version INTEGER NOT NULL,
    check_id    VARCHAR NOT NULL,
    check_name  TEXT NOT NULL,
    status      VARCHAR NOT NULL,
    severity    VARCHAR NOT NULL,
    description TEXT NOT NULL,
    details     TEXT,
    affected    TEXT,
    PRIMARY KEY (brief_id, brief_version, check_id)
);

CREATE TABLE IF NOT EXISTS brief_reviews (
    review_id               VARCHAR PRIMARY KEY,
    brief_id                VARCHAR NOT NULL,
    brief_version           INTEGER NOT NULL,
    previous_status         VARCHAR NOT NULL,
    new_status              VARCHAR NOT NULL,
    reviewer_id             VARCHAR NOT NULL,
    reviewer_label          VARCHAR NOT NULL,
    timestamp               VARCHAR NOT NULL,
    note                    TEXT,
    content_hash_reviewed   VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS brief_audit_log (
    audit_id    VARCHAR PRIMARY KEY,
    brief_id    VARCHAR NOT NULL,
    event_type  VARCHAR NOT NULL,
    actor       VARCHAR NOT NULL,
    timestamp   VARCHAR NOT NULL,
    detail      TEXT,
    metadata_json TEXT NOT NULL
);
"""


class SynthesisRepository:
    """DuckDB persistence for Phase 5 synthesis artifacts."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = duckdb.connect(db_path)
        self._conn.execute(_DDL)

    # ------------------------------------------------------------------
    # Snapshot persistence
    # ------------------------------------------------------------------

    def save_snapshot(self, snapshot: EvidenceSnapshot) -> None:
        self._conn.execute(
            "INSERT INTO evidence_snapshots VALUES (?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            [
                snapshot.snapshot_id,
                snapshot.retrieval_run_id,
                snapshot.query_hash,
                snapshot.data_origin,
                snapshot.snapshot_hash,
                json.dumps(snapshot.source_statuses),
                json.dumps(snapshot.qa_summary),
                _ts(snapshot.created_at),
            ],
        )
        for r in snapshot.records:
            self._conn.execute(
                "INSERT INTO snapshot_records "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                [
                    snapshot.snapshot_id,
                    r.evidence_id,
                    r.source_specific_id,
                    r.source_type,
                    r.source_name,
                    r.title,
                    r.content_hash,
                    r.is_fixture_data,
                    r.fixture_manifest_version,
                    r.data_origin,
                    r.retrieval_run_id,
                    r.relevance_score,
                    json.dumps(r.tags),
                    r.url,
                    json.dumps(r.warnings),
                ],
            )

    def get_snapshot(self, snapshot_id: str) -> EvidenceSnapshot | None:
        result = self._conn.execute(
            "SELECT * FROM evidence_snapshots WHERE snapshot_id = ?", [snapshot_id]
        )
        cols = [d[0] for d in result.description]
        row = result.fetchone()
        if row is None:
            return None
        meta = dict(zip(cols, row, strict=False))
        recs = self._load_snapshot_records(snapshot_id)
        return EvidenceSnapshot(
            snapshot_id=meta["snapshot_id"],
            retrieval_run_id=meta["retrieval_run_id"],
            query_hash=meta["query_hash"],
            data_origin=meta["data_origin"],
            snapshot_hash=meta["snapshot_hash"],
            source_statuses=json.loads(meta["source_statuses_json"]),
            qa_summary=json.loads(meta["qa_summary_json"]),
            records=recs,
        )

    def _load_snapshot_records(self, snapshot_id: str) -> list[EvidenceSnapshotRecord]:
        result = self._conn.execute(
            "SELECT * FROM snapshot_records WHERE snapshot_id = ?", [snapshot_id]
        )
        cols = [d[0] for d in result.description]
        rows = result.fetchall()
        records = []
        for row in rows:
            d = dict(zip(cols, row, strict=False))
            records.append(
                EvidenceSnapshotRecord(
                    evidence_id=d["evidence_id"],
                    source_specific_id=d["source_specific_id"],
                    source_type=d["source_type"],
                    source_name=d["source_name"],
                    title=d["title"],
                    content_hash=d["content_hash"],
                    is_fixture_data=d["is_fixture_data"],
                    fixture_manifest_version=d["fixture_manifest_version"],
                    data_origin=d["data_origin"],
                    retrieval_run_id=d["retrieval_run_id"],
                    relevance_score=d["relevance_score"],
                    tags=json.loads(d["tags_json"]),
                    url=d["url"],
                    warnings=json.loads(d["warnings_json"]),
                )
            )
        return records

    # ------------------------------------------------------------------
    # Brief persistence
    # ------------------------------------------------------------------

    def save_brief(self, brief: EvidenceBrief) -> None:
        """Persist a brief. Idempotent on (brief_id, version)."""
        full_json = json.dumps(brief.model_dump(mode="json"), ensure_ascii=False)
        self._conn.execute(
            "INSERT INTO evidence_briefs "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT DO NOTHING",
            [
                brief.brief_id,
                brief.version,
                brief.schema_version,
                brief.question_id,
                brief.phenotype_id,
                brief.phenotype_version,
                brief.cohort_run_id,
                brief.evidence_run_id,
                brief.evidence_snapshot_id,
                brief.evidence_snapshot_hash,
                _ts(brief.generated_at),
                brief.generation_mode,
                brief.model_provider,
                brief.model_name,
                brief.prompt_version,
                json.dumps(brief.model_parameters),
                brief.data_origin,
                brief.data_notice,
                json.dumps(brief.limitations),
                brief.disclaimer,
                json.dumps(brief.qa_summary),
                brief.human_review_status,
                brief.content_hash,
                json.dumps(brief.provenance.model_dump(mode="json")) if brief.provenance else None,
                full_json,
            ],
        )
        for claim in brief.claims:
            self._save_claim(brief.brief_id, brief.version, claim)
        for gap in brief.evidence_gaps:
            self._save_gap(brief.brief_id, brief.version, gap)

    def _save_claim(self, brief_id: str, version: int, claim: GeneratedClaim) -> None:
        self._conn.execute(
            """INSERT INTO generated_claims VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT DO NOTHING""",
            [
                brief_id,
                version,
                claim.claim_id,
                claim.text,
                claim.claim_type,
                claim.dimension,
                claim.evidence_basis,
                json.dumps(claim.source_ids),
                json.dumps(claim.design_limitations),
                claim.uncertainty_note,
            ],
        )
        for cit in claim.citations:
            self._conn.execute(
                """INSERT INTO claim_citations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT DO NOTHING""",
                [
                    brief_id,
                    version,
                    claim.claim_id,
                    cit.citation_number,
                    cit.source_id,
                    cit.source_specific_id,
                    cit.source_type,
                    cit.title,
                    cit.url,
                    cit.support_type,
                    cit.locator,
                    cit.review_status,
                ],
            )

    def _save_gap(self, brief_id: str, version: int, gap: EvidenceGap) -> None:
        self._conn.execute(
            """INSERT INTO evidence_gaps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT DO NOTHING""",
            [
                brief_id,
                version,
                gap.gap_id,
                gap.description,
                gap.dimension,
                gap.retrieval_run_id,
                json.dumps(gap.sources_searched),
                json.dumps(gap.source_statuses),
                json.dumps(gap.query_strings),
                json.dumps(gap.filters_applied),
                gap.date_range,
                json.dumps(gap.result_counts),
                json.dumps(gap.failed_sources),
                json.dumps(gap.limitations),
                _ts(gap.generated_at),
            ],
        )

    def save_qa_results(
        self, brief_id: str, qa_results: list[dict[str, Any]], version: int = 1
    ) -> None:
        for r in qa_results:
            self._conn.execute(
                """INSERT INTO brief_qa_results VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT DO NOTHING""",
                [
                    brief_id,
                    version,
                    r["check_id"],
                    r["check_name"],
                    r["status"],
                    r["severity"],
                    r["description"],
                    r.get("details"),
                    json.dumps(r.get("affected", [])),
                ],
            )

    def get_brief(self, brief_id: str, version: int | None = None) -> EvidenceBrief:
        """Return the latest version (or specified version) of a brief."""
        if version is None:
            row = self._conn.execute(
                "SELECT full_brief_json FROM evidence_briefs "
                "WHERE brief_id = ? ORDER BY version DESC LIMIT 1",
                [brief_id],
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT full_brief_json FROM evidence_briefs WHERE brief_id = ? AND version = ?",
                [brief_id, version],
            ).fetchone()
        if row is None:
            raise BriefNotFoundError(f"No brief found with brief_id={brief_id!r}")
        return EvidenceBrief.model_validate(json.loads(row[0]))

    def list_brief_ids(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT brief_id FROM evidence_briefs ORDER BY brief_id"
        ).fetchall()
        return [r[0] for r in rows]

    def get_brief_qa(self, brief_id: str, version: int | None = None) -> list[dict[str, Any]]:
        if version is None:
            v_row = self._conn.execute(
                "SELECT MAX(version) FROM evidence_briefs WHERE brief_id = ?", [brief_id]
            ).fetchone()
            version = v_row[0] if v_row else 1
        result = self._conn.execute(
            "SELECT check_id, check_name, status, severity, description, details, affected "
            "FROM brief_qa_results WHERE brief_id = ? AND brief_version = ?",
            [brief_id, version],
        )
        cols = [d[0] for d in result.description]
        return [dict(zip(cols, row, strict=False)) for row in result.fetchall()]

    def update_brief_review_status(self, brief_id: str, new_status: BriefReviewStatus) -> None:
        """Update human_review_status and full_brief_json for the latest brief version."""
        ver_row = self._conn.execute(
            "SELECT MAX(version) FROM evidence_briefs WHERE brief_id = ?",
            [brief_id],
        ).fetchone()
        if ver_row is None or ver_row[0] is None:
            raise BriefNotFoundError(f"No brief found with brief_id={brief_id!r}")
        version = ver_row[0]
        json_row = self._conn.execute(
            "SELECT full_brief_json FROM evidence_briefs WHERE brief_id = ? AND version = ?",
            [brief_id, version],
        ).fetchone()
        if json_row is None:
            raise BriefNotFoundError(f"No brief found with brief_id={brief_id!r}")
        brief_dict = json.loads(json_row[0])
        brief_dict["human_review_status"] = new_status
        self._conn.execute(
            "UPDATE evidence_briefs SET human_review_status = ?, full_brief_json = ? "
            "WHERE brief_id = ? AND version = ?",
            [new_status, json.dumps(brief_dict), brief_id, version],
        )

    # ------------------------------------------------------------------
    # Review persistence
    # ------------------------------------------------------------------

    def save_review(self, review: BriefReviewRecord) -> None:
        self._conn.execute(
            "INSERT INTO brief_reviews VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            [
                review.review_id,
                review.brief_id,
                review.brief_version,
                review.previous_status,
                review.new_status,
                review.reviewer_id,
                review.reviewer_label,
                _ts(review.timestamp),
                review.note,
                review.content_hash_reviewed,
            ],
        )

    def get_review_history(self, brief_id: str) -> list[dict[str, Any]]:
        result = self._conn.execute(
            "SELECT * FROM brief_reviews WHERE brief_id = ? ORDER BY timestamp ASC",
            [brief_id],
        )
        cols = [d[0] for d in result.description]
        return [dict(zip(cols, row, strict=False)) for row in result.fetchall()]

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def log_audit(
        self,
        brief_id: str,
        event_type: str,
        actor: str,
        detail: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO brief_audit_log VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            [
                f"audit-{uuid.uuid4().hex[:12]}",
                brief_id,
                event_type,
                actor,
                _ts(datetime.now(UTC)),
                detail,
                json.dumps(metadata or {}),
            ],
        )

    def get_audit_log(self, brief_id: str) -> list[dict[str, Any]]:
        result = self._conn.execute(
            "SELECT * FROM brief_audit_log WHERE brief_id = ? ORDER BY timestamp ASC",
            [brief_id],
        )
        cols = [d[0] for d in result.description]
        return [dict(zip(cols, row, strict=False)) for row in result.fetchall()]


@lru_cache(maxsize=1)
def get_synthesis_repository() -> SynthesisRepository:
    return SynthesisRepository(db_path=":memory:")
