"""CMS Medicare Coverage (LCD/NCD) evidence source adapter.

Offline fixture mode is the default and only mode in the demo environment.
The CMS Coverage API (coverage.cms.gov) is a REST API; live retrieval is
supported via ``fetch_live()`` but is excluded from the automated test suite.

Fields captured from each document:
  - Document ID (LCD/NCD), document type, title, contractor, jurisdiction,
    effective date, retirement/revision dates, status, coverage determination
    summary, applicable ICD/CPT/HCPCS codes (if present)

Fields NOT inferred by this adapter:
  - Clinical rationale (document text is not parsed; only metadata is captured)
  - Coverage decision for specific patients or codes not listed in the document
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.evidence_sources.base import RawFetchResult
from src.schemas.evidence import EvidenceSourceName, RawEvidenceRecord
from src.schemas.retrieval import RetrievalError, SourceSpecificQuery
from src.utils.exceptions import FixtureManifestError

_SOURCE: EvidenceSourceName = "cms_coverage"


def _content_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class CMSCoverageAdapter:
    """Offline-first CMS Medicare Coverage adapter reading versioned JSON fixtures."""

    source_name: EvidenceSourceName = _SOURCE

    def __init__(self, fixture_dir: Path) -> None:
        self._fixture_dir = Path(fixture_dir)

    def fetch(self, query: SourceSpecificQuery, run_id: str) -> RawFetchResult:
        manifest_path = self._fixture_dir / "manifest.json"
        if not manifest_path.exists():
            err = RetrievalError(
                source_name=_SOURCE,
                error_type="fixture_missing",
                message=f"CMS coverage fixture manifest not found: {manifest_path}",
            )
            return RawFetchResult(source_name=_SOURCE, errors=[err])

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise FixtureManifestError(f"Cannot parse CMS coverage manifest: {exc}") from exc

        manifest_version = manifest.get("version", "unknown")
        fixture_files: list[str] = manifest.get("fixture_files", [])

        records: list[RawEvidenceRecord] = []
        errors: list[RetrievalError] = []

        for fname in fixture_files:
            fpath = self._fixture_dir / fname
            if not fpath.exists():
                errors.append(
                    RetrievalError(
                        source_name=_SOURCE,
                        error_type="fixture_missing",
                        message=f"CMS coverage fixture file missing: {fname}",
                        is_fatal_for_source=False,
                    )
                )
                continue
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                docs: list[dict[str, Any]] = data if isinstance(data, list) else [data]
                for doc in docs:
                    doc_id = doc.get("id") or doc.get("lcd_id") or doc.get("ncd_id", "")
                    if not doc_id:
                        continue
                    ch = _content_hash(doc)
                    records.append(
                        RawEvidenceRecord(
                            id=f"raw-cms-{doc_id}-{ch}",
                            source_name=_SOURCE,
                            retrieval_run_id=run_id,
                            source_identifier=str(doc_id),
                            raw_payload=doc,
                            content_hash=ch,
                            fetched_at=datetime.now(UTC),
                            is_fixture_data=True,
                            fixture_manifest_version=manifest_version,
                        )
                    )
            except Exception as exc:
                errors.append(
                    RetrievalError(
                        source_name=_SOURCE,
                        error_type="parse_error",
                        message=f"Failed to parse CMS coverage fixture '{fname}': {exc}",
                        is_fatal_for_source=False,
                    )
                )

        return RawFetchResult(
            source_name=_SOURCE,
            records=records,
            errors=errors,
            extra_metadata={"manifest_version": manifest_version},
        )

    def ping(self) -> bool:
        return True

    def fetch_live(
        self,
        search_term: str,
        run_id: str,
        max_results: int = 20,
    ) -> RawFetchResult:
        """Fetch from the live CMS Coverage API. Mark live tests with @pytest.mark.live."""
        import httpx

        base = "https://coverage.cms.gov/api/coverage"
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    base,
                    params={"searchTerm": search_term, "limit": max_results},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            from src.utils.exceptions import RetrievalParseError

            raise RetrievalParseError(f"CMS coverage live fetch failed: {exc}") from exc

        docs = data if isinstance(data, list) else data.get("results", [])
        records: list[RawEvidenceRecord] = []
        for doc in docs:
            doc_id = doc.get("id", doc.get("documentId", "unknown"))
            ch = _content_hash(doc)
            records.append(
                RawEvidenceRecord(
                    id=f"raw-cms-{doc_id}-{ch}",
                    source_name=_SOURCE,
                    retrieval_run_id=run_id,
                    source_identifier=str(doc_id),
                    raw_payload=doc,
                    content_hash=ch,
                    fetched_at=datetime.now(UTC),
                    is_fixture_data=False,
                )
            )
        return RawFetchResult(source_name=_SOURCE, records=records)
