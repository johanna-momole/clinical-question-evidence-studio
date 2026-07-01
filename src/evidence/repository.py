"""DuckDB persistence repository for evidence retrieval runs.

Tables (all idempotent — re-inserting the same run_id replaces prior data):
  1. retrieval_runs       — one row per RetrievalRun
  2. retrieval_provenance — one row per run (RetrievalProvenance)
  3. source_statuses      — one row per (run_id, source_name)
  4. retrieval_errors     — one row per error
  5. raw_evidence_records — one row per RawEvidenceRecord
  6. evidence_records     — one row per normalized EvidenceRecord
  7. evidence_tags        — one row per EvidenceTag (keyed to evidence_id)
  8. dedup_results        — one row per run
  9. evidence_qa_results  — one row per QAResult from evidence_checks
  10. retrieval_qa_results — one row per QAResult from retrieval_checks

Stable IDs: evidence_id = ev-{source}-{identifier}-{content_hash}.
The same run_id always maps to the same evidence_id values (idempotent).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from functools import lru_cache

import duckdb

from src.schemas.evidence import EvidenceDeduplicationResult, EvidenceRecord, RawEvidenceRecord
from src.schemas.qa import QASummary
from src.schemas.retrieval import RetrievalRun
from src.utils.exceptions import EvidenceNotFoundError, RetrievalRunNotFoundError


def _ts(dt: datetime | None) -> str | None:
    """Serialize datetime to ISO8601 UTC string (avoids pytz dependency in DuckDB)."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.isoformat()


_DDL = """
CREATE TABLE IF NOT EXISTS retrieval_runs (
    run_id              VARCHAR PRIMARY KEY,
    query_id            VARCHAR NOT NULL,
    question_id         VARCHAR NOT NULL,
    phenotype_id        VARCHAR NOT NULL,
    phenotype_version   VARCHAR NOT NULL,
    query_hash          VARCHAR NOT NULL,
    retrieval_mode      VARCHAR NOT NULL,
    started_at          VARCHAR NOT NULL,
    completed_at        VARCHAR,
    total_retrieved     INTEGER NOT NULL DEFAULT 0,
    total_after_dedup   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS retrieval_provenance (
    run_id                    VARCHAR PRIMARY KEY,
    query_hash                VARCHAR NOT NULL,
    retrieval_mode            VARCHAR NOT NULL,
    sources_queried           TEXT NOT NULL,
    fixture_manifest_versions TEXT NOT NULL,
    data_authenticity_note    TEXT NOT NULL,
    retrieved_at              VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS source_statuses (
    run_id                      VARCHAR NOT NULL,
    source_name                 VARCHAR NOT NULL,
    records_retrieved           INTEGER NOT NULL,
    records_after_normalization INTEGER NOT NULL,
    cache_hit                   BOOLEAN NOT NULL,
    duration_ms                 INTEGER,
    PRIMARY KEY (run_id, source_name)
);

CREATE TABLE IF NOT EXISTS retrieval_errors (
    id          VARCHAR NOT NULL,
    run_id      VARCHAR NOT NULL,
    source_name VARCHAR NOT NULL,
    error_type  VARCHAR NOT NULL,
    message     TEXT NOT NULL,
    is_fatal    BOOLEAN NOT NULL,
    occurred_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_evidence_records (
    id                       VARCHAR PRIMARY KEY,
    run_id                   VARCHAR NOT NULL,
    source_name              VARCHAR NOT NULL,
    source_identifier        VARCHAR NOT NULL,
    content_hash             VARCHAR NOT NULL,
    fetched_at               VARCHAR NOT NULL,
    is_fixture_data          BOOLEAN NOT NULL,
    fixture_manifest_version VARCHAR,
    raw_payload_json         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_records (
    id                         VARCHAR PRIMARY KEY,
    run_id                     VARCHAR NOT NULL,
    source_type                VARCHAR NOT NULL,
    source_name                VARCHAR,
    title                      TEXT NOT NULL,
    identifier                 VARCHAR NOT NULL,
    url                        TEXT,
    publication_or_update_date DATE,
    date_precision             VARCHAR,
    study_design               VARCHAR,
    status                     VARCHAR,
    relevance_score            DOUBLE,
    review_status              VARCHAR NOT NULL DEFAULT 'pending',
    content_hash               VARCHAR,
    is_fixture_data            BOOLEAN NOT NULL DEFAULT TRUE,
    duplicate_of               VARCHAR,
    full_record_json           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_tags (
    evidence_id VARCHAR NOT NULL,
    tag         VARCHAR NOT NULL,
    dimension   VARCHAR NOT NULL,
    rule_id     VARCHAR NOT NULL,
    PRIMARY KEY (evidence_id, tag)
);

CREATE TABLE IF NOT EXISTS dedup_results (
    run_id              VARCHAR PRIMARY KEY,
    total_records       INTEGER NOT NULL,
    duplicates_removed  INTEGER NOT NULL,
    groups_json         TEXT NOT NULL,
    relationships_json  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_qa_results (
    run_id      VARCHAR NOT NULL,
    check_id    VARCHAR NOT NULL,
    check_name  VARCHAR NOT NULL,
    category    VARCHAR NOT NULL,
    status      VARCHAR NOT NULL,
    severity    VARCHAR NOT NULL,
    description TEXT NOT NULL,
    details     TEXT,
    affected    TEXT,
    PRIMARY KEY (run_id, check_id)
);

CREATE TABLE IF NOT EXISTS retrieval_qa_results (
    run_id      VARCHAR NOT NULL,
    check_id    VARCHAR NOT NULL,
    check_name  VARCHAR NOT NULL,
    category    VARCHAR NOT NULL,
    status      VARCHAR NOT NULL,
    severity    VARCHAR NOT NULL,
    description TEXT NOT NULL,
    details     TEXT,
    affected    TEXT,
    PRIMARY KEY (run_id, check_id)
);
"""

# DuckDB INSERT_OR_IGNORE equivalent: ON CONFLICT DO NOTHING
_INS_RAW = """
INSERT INTO raw_evidence_records
    (id, run_id, source_name, source_identifier, content_hash,
     fetched_at, is_fixture_data, fixture_manifest_version, raw_payload_json)
VALUES (?,?,?,?,?,?,?,?,?)
ON CONFLICT DO NOTHING
"""

_INS_REC = """
INSERT INTO evidence_records
    (id, run_id, source_type, source_name, title, identifier, url,
     publication_or_update_date, date_precision, study_design, status,
     relevance_score, review_status, content_hash, is_fixture_data,
     duplicate_of, full_record_json)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT DO NOTHING
"""

_INS_TAG = """
INSERT INTO evidence_tags (evidence_id, tag, dimension, rule_id)
VALUES (?,?,?,?)
ON CONFLICT DO NOTHING
"""

_INS_QA = """
INSERT INTO {table}
    (run_id, check_id, check_name, category, status, severity, description, details, affected)
VALUES (?,?,?,?,?,?,?,?,?)
ON CONFLICT DO NOTHING
"""


class EvidenceRepository:
    """DuckDB-backed persistence for evidence retrieval pipeline outputs."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = duckdb.connect(db_path)
        self._conn.execute(_DDL)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def save_run(
        self,
        run: RetrievalRun,
        raw_records: list[RawEvidenceRecord],
        normalized_records: list[EvidenceRecord],
        dedup_result: EvidenceDeduplicationResult,
        evidence_qa: QASummary,
        retrieval_qa: QASummary,
    ) -> None:
        """Persist a complete retrieval run. Idempotent: re-saving the same run_id replaces data."""
        run_id = run.run_id
        self._delete_run(run_id)

        # retrieval_runs (11 columns)
        self._conn.execute(
            "INSERT INTO retrieval_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                run_id,
                run.query.id,
                run.query.question_id,
                run.query.phenotype_id,
                run.query.phenotype_version,
                run.query.query_hash,
                run.provenance.retrieval_mode,
                _ts(run.started_at),
                _ts(run.completed_at),
                run.total_records_retrieved,
                run.total_records_after_dedup,
            ],
        )

        # retrieval_provenance (7 columns)
        self._conn.execute(
            "INSERT INTO retrieval_provenance VALUES (?,?,?,?,?,?,?)",
            [
                run_id,
                run.provenance.query_hash,
                run.provenance.retrieval_mode,
                json.dumps(run.provenance.sources_queried),
                json.dumps(run.provenance.fixture_manifest_versions),
                run.provenance.data_authenticity_note,
                _ts(run.provenance.retrieved_at),
            ],
        )

        # source_statuses + retrieval_errors (6 + 7 columns)
        for ss in run.source_statuses:
            self._conn.execute(
                "INSERT INTO source_statuses VALUES (?,?,?,?,?,?)",
                [
                    run_id,
                    ss.source_name,
                    ss.records_retrieved,
                    ss.records_after_normalization,
                    ss.cache_hit,
                    ss.duration_ms,
                ],
            )
            for err in ss.errors:
                self._conn.execute(
                    "INSERT INTO retrieval_errors (id, run_id, source_name, error_type, "
                    "message, is_fatal, occurred_at) VALUES (?,?,?,?,?,?,?)",
                    [
                        str(uuid.uuid4()),
                        run_id,
                        err.source_name,
                        err.error_type,
                        err.message,
                        err.is_fatal_for_source,
                        _ts(err.occurred_at),
                    ],
                )

        # raw_evidence_records (9 columns)
        for raw in raw_records:
            self._conn.execute(
                _INS_RAW,
                [
                    raw.id,
                    run_id,
                    raw.source_name,
                    raw.source_identifier,
                    raw.content_hash,
                    _ts(raw.fetched_at),
                    raw.is_fixture_data,
                    raw.fixture_manifest_version,
                    json.dumps(raw.raw_payload, ensure_ascii=False),
                ],
            )

        # evidence_records (17 columns) + evidence_tags (4 columns)
        for rec in normalized_records:
            full_json = json.dumps(rec.model_dump(mode="json"), ensure_ascii=False)
            self._conn.execute(
                _INS_REC,
                [
                    rec.id,
                    run_id,
                    rec.source_type,
                    rec.source_name,
                    rec.title,
                    rec.identifier,
                    rec.url,
                    rec.publication_or_update_date,
                    rec.date_precision,
                    rec.study_design,
                    rec.status,
                    rec.relevance_score,
                    rec.review_status,
                    rec.content_hash,
                    rec.is_fixture_data,
                    rec.duplicate_of,
                    full_json,
                ],
            )
            for tag in rec.structured_tags:
                self._conn.execute(_INS_TAG, [rec.id, tag.tag, tag.dimension, tag.rule_id])

        # dedup_results (5 columns)
        self._conn.execute(
            "INSERT INTO dedup_results VALUES (?,?,?,?,?)",
            [
                run_id,
                dedup_result.total_records,
                dedup_result.duplicates_removed,
                json.dumps(dedup_result.duplicate_groups),
                json.dumps(dedup_result.cross_source_relationships),
            ],
        )

        # QA results (9 columns each table)
        for qa_summary, table in [
            (evidence_qa, "evidence_qa_results"),
            (retrieval_qa, "retrieval_qa_results"),
        ]:
            for r in qa_summary.results:
                self._conn.execute(
                    _INS_QA.format(table=table),
                    [
                        run_id,
                        r.check_id,
                        r.check_name,
                        r.category,
                        r.status,
                        r.severity,
                        r.description,
                        r.details,
                        json.dumps(r.affected_records),
                    ],
                )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_run(self, run_id: str) -> dict:
        result = self._conn.execute("SELECT * FROM retrieval_runs WHERE run_id = ?", [run_id])
        row = result.fetchone()
        if row is None:
            raise RetrievalRunNotFoundError(f"No retrieval run found with run_id='{run_id}'")
        cols = [d[0] for d in result.description]
        return dict(zip(cols, row, strict=False))

    def list_run_ids(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT run_id FROM retrieval_runs ORDER BY started_at DESC"
        ).fetchall()
        return [r[0] for r in rows]

    def get_evidence_record(self, evidence_id: str) -> dict:
        result = self._conn.execute(
            "SELECT full_record_json FROM evidence_records WHERE id = ?", [evidence_id]
        )
        row = result.fetchone()
        if row is None:
            raise EvidenceNotFoundError(f"No evidence record found with id='{evidence_id}'")
        return json.loads(row[0])  # type: ignore[no-any-return]

    def list_evidence_for_run(
        self,
        run_id: str,
        source_type: str | None = None,
        min_score: float | None = None,
        tags: list[str] | None = None,
    ) -> list[dict]:
        conditions = ["run_id = ?"]
        params: list = [run_id]
        if source_type:
            conditions.append("source_type = ?")
            params.append(source_type)
        if min_score is not None:
            conditions.append("relevance_score >= ?")
            params.append(min_score)
        where = " AND ".join(conditions)
        rows = self._conn.execute(
            f"SELECT full_record_json FROM evidence_records WHERE {where} "
            "ORDER BY relevance_score DESC NULLS LAST",
            params,
        ).fetchall()
        records = [json.loads(r[0]) for r in rows]

        if tags:
            tag_set = set(tags)
            return [rec for rec in records if set(rec.get("tags", [])) & tag_set]
        return records

    def get_evidence_qa(self, run_id: str) -> list[dict]:
        return self._query_qa("evidence_qa_results", run_id)

    def get_retrieval_qa(self, run_id: str) -> list[dict]:
        return self._query_qa("retrieval_qa_results", run_id)

    def source_coverage(self, run_id: str) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT source_name, records_retrieved FROM source_statuses WHERE run_id = ?",
            [run_id],
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _query_qa(self, table: str, run_id: str) -> list[dict]:
        result = self._conn.execute(
            f"SELECT check_id, check_name, category, status, severity, description, details, affected "
            f"FROM {table} WHERE run_id = ?",
            [run_id],
        )
        cols = [d[0] for d in result.description]
        return [dict(zip(cols, row, strict=False)) for row in result.fetchall()]

    def _delete_run(self, run_id: str) -> None:
        tables_with_run_id = [
            "retrieval_runs",
            "retrieval_provenance",
            "source_statuses",
            "retrieval_errors",
            "raw_evidence_records",
            "dedup_results",
            "evidence_qa_results",
            "retrieval_qa_results",
        ]
        for table in tables_with_run_id:
            self._conn.execute(f"DELETE FROM {table} WHERE run_id = ?", [run_id])
        # evidence_records and evidence_tags use different join
        self._conn.execute("DELETE FROM evidence_records WHERE run_id = ?", [run_id])
        self._conn.execute(
            "DELETE FROM evidence_tags WHERE evidence_id NOT IN (SELECT id FROM evidence_records)"
        )


@lru_cache(maxsize=1)
def get_evidence_repository() -> EvidenceRepository:
    """Return the singleton in-process evidence repository."""
    return EvidenceRepository(db_path=":memory:")
