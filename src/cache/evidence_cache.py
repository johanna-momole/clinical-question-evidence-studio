"""Evidence retrieval cache backed by DuckDB.

Cache keys are composed of: source_name + query_hash + max_results.
Stored values are lists of serialized RawEvidenceRecord dicts.

Time injection: ``_now_fn`` is injectable (defaults to ``datetime.now(UTC)``) so tests
can freeze time without monkey-patching the stdlib — pass a callable returning a
fixed ``datetime`` to make TTL expiry deterministic in tests.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import duckdb

from src.schemas.evidence import EvidenceSourceName, RawEvidenceRecord

_DEFAULT_TTL_HOURS = 24

_DDL = """
CREATE TABLE IF NOT EXISTS evidence_cache (
    cache_key       VARCHAR PRIMARY KEY,
    source_name     VARCHAR NOT NULL,
    query_hash      VARCHAR NOT NULL,
    max_results     INTEGER NOT NULL,
    records_json    TEXT NOT NULL,
    cached_at       VARCHAR NOT NULL,
    expires_at      VARCHAR NOT NULL,
    hit_count       INTEGER NOT NULL DEFAULT 0
);
"""


def _ts(dt: datetime) -> str:
    """Serialize datetime to ISO8601 UTC string for VARCHAR storage (avoids pytz dependency)."""
    # Ensure UTC then strip tzinfo so DuckDB doesn't need pytz
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.isoformat()


def _utcnow() -> datetime:
    return datetime.now(UTC)


class EvidenceCache:
    """DuckDB-backed, TTL-aware cache for raw evidence records.

    Injecting ``now_fn`` overrides the clock — useful for deterministic tests.
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        ttl_hours: int = _DEFAULT_TTL_HOURS,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._conn = duckdb.connect(db_path)
        self._conn.execute(_DDL)
        self._ttl = timedelta(hours=ttl_hours)
        self._now = now_fn or _utcnow

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(
        self,
        source_name: EvidenceSourceName,
        query_hash: str,
        max_results: int,
    ) -> list[RawEvidenceRecord] | None:
        """Return cached records if present and not expired; else None."""
        key = self._cache_key(source_name, query_hash, max_results)
        now_str = _ts(self._now())
        rows = self._conn.execute(
            "SELECT records_json, expires_at FROM evidence_cache WHERE cache_key = ?",
            [key],
        ).fetchall()
        if not rows:
            return None
        records_json, expires_at_str = rows[0]
        if now_str > expires_at_str:
            self._conn.execute("DELETE FROM evidence_cache WHERE cache_key = ?", [key])
            return None
        self._conn.execute(
            "UPDATE evidence_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
            [key],
        )
        raw_list: list[dict[str, Any]] = json.loads(records_json)
        return [RawEvidenceRecord.model_validate(r) for r in raw_list]

    def put(
        self,
        source_name: EvidenceSourceName,
        query_hash: str,
        max_results: int,
        records: list[RawEvidenceRecord],
    ) -> None:
        """Store records in the cache, overwriting any existing entry for this key."""
        key = self._cache_key(source_name, query_hash, max_results)
        now = self._now()
        expires_at = now + self._ttl
        records_json = json.dumps([r.model_dump(mode="json") for r in records], ensure_ascii=False)
        self._conn.execute(
            """
            INSERT INTO evidence_cache
                (cache_key, source_name, query_hash, max_results, records_json, cached_at, expires_at, hit_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT (cache_key) DO UPDATE SET
                records_json = excluded.records_json,
                cached_at    = excluded.cached_at,
                expires_at   = excluded.expires_at,
                hit_count    = 0
            """,
            [key, source_name, query_hash, max_results, records_json, _ts(now), _ts(expires_at)],
        )

    def evict_expired(self) -> int:
        """Delete all expired cache entries. Returns the count deleted."""
        now_str = _ts(self._now())
        before_row = self._conn.execute("SELECT COUNT(*) FROM evidence_cache").fetchone()
        before: int = before_row[0] if before_row else 0
        self._conn.execute("DELETE FROM evidence_cache WHERE expires_at < ?", [now_str])
        after_row = self._conn.execute("SELECT COUNT(*) FROM evidence_cache").fetchone()
        after: int = after_row[0] if after_row else 0
        return before - after

    def clear(self) -> None:
        self._conn.execute("DELETE FROM evidence_cache")

    def stats(self) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT source_name, COUNT(*), SUM(hit_count) FROM evidence_cache GROUP BY source_name"
        ).fetchall()
        return {r[0]: {"entries": r[1], "total_hits": r[2]} for r in rows}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(source_name: str, query_hash: str, max_results: int) -> str:
        return f"{source_name}|{query_hash}|{max_results}"
