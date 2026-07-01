"""DuckDB persistence for export artifacts and manifests."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import duckdb

from src.schemas.exports import ExportBundle, ExportManifest

_DDL = """
CREATE TABLE IF NOT EXISTS export_manifests (
    manifest_id       TEXT PRIMARY KEY,
    brief_id          TEXT NOT NULL,
    brief_version     INTEGER NOT NULL,
    bundle_name       TEXT NOT NULL,
    review_status     TEXT NOT NULL,
    origin_class      TEXT NOT NULL,
    manifest_sha256   TEXT NOT NULL,
    zip_sha256        TEXT,
    zip_byte_size     INTEGER,
    zip_filename      TEXT,
    created_at        TIMESTAMP NOT NULL,
    full_manifest_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS export_artifacts (
    artifact_id       TEXT PRIMARY KEY,
    manifest_id       TEXT NOT NULL,
    brief_id          TEXT NOT NULL,
    brief_version     INTEGER NOT NULL,
    export_format     TEXT NOT NULL,
    filename          TEXT NOT NULL,
    mime_type         TEXT NOT NULL,
    byte_size         INTEGER NOT NULL,
    sha256            TEXT NOT NULL,
    origin_class      TEXT NOT NULL,
    review_status     TEXT NOT NULL,
    created_at        TIMESTAMP NOT NULL,
    warnings_json     TEXT NOT NULL
);
"""


class ExportRepository:
    def __init__(self, db_path: str = "data/exports.duckdb") -> None:
        self._conn = duckdb.connect(db_path)
        self._conn.execute(_DDL)

    def save_bundle(self, bundle: ExportBundle) -> None:
        m = bundle.manifest
        self._conn.execute(
            "INSERT OR IGNORE INTO export_manifests VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                m.manifest_id,
                m.brief_id,
                m.brief_version,
                m.bundle_name,
                m.review_status,
                m.origin_classification,
                m.manifest_sha256,
                bundle.zip_sha256,
                bundle.zip_byte_size,
                bundle.zip_filename,
                m.created_at.isoformat(),
                m.model_dump_json(),
            ],
        )
        for artifact in m.artifacts:
            self._conn.execute(
                "INSERT OR IGNORE INTO export_artifacts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    artifact.artifact_id,
                    m.manifest_id,
                    artifact.brief_id,
                    artifact.brief_version,
                    artifact.export_format,
                    artifact.filename,
                    artifact.mime_type,
                    artifact.byte_size,
                    artifact.sha256,
                    artifact.origin_classification,
                    artifact.review_status,
                    artifact.created_at.isoformat(),
                    json.dumps(artifact.warnings),
                ],
            )

    def get_manifest(self, manifest_id: str) -> ExportManifest | None:
        row = self._conn.execute(
            "SELECT full_manifest_json FROM export_manifests WHERE manifest_id = ?",
            [manifest_id],
        ).fetchone()
        if row is None:
            return None
        return ExportManifest.model_validate_json(row[0])

    def list_manifests_for_brief(self, brief_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT manifest_id, bundle_name, review_status, created_at, manifest_sha256 "
            "FROM export_manifests WHERE brief_id = ? ORDER BY created_at DESC",
            [brief_id],
        ).fetchall()
        return [
            {
                "manifest_id": r[0],
                "bundle_name": r[1],
                "review_status": r[2],
                "created_at": r[3],
                "manifest_sha256": r[4],
            }
            for r in rows
        ]


@lru_cache(maxsize=1)
def get_export_repository() -> ExportRepository:
    return ExportRepository()
