"""ClinicalTrials.gov (v2 REST API) evidence source adapter.

Offline fixture mode is the default and only mode in the demo environment.

Fields captured from each study:
  - NCT ID, official title, status (overall, results posted), phase,
    enrollment, primary completion date, sponsor, conditions, interventions,
    study type, brief summary, start date

Fields NOT inferred or claimed by this adapter:
  - Endpoint results (fetched separately via results endpoint — not in scope)
  - Blinding, randomization detail (schema has no dedicated field; recorded in study_design)
  - Efficacy claims (never generated — only structured metadata is captured)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.evidence_sources.base import RawFetchResult
from src.schemas.evidence import EvidenceSourceName, RawEvidenceRecord
from src.schemas.retrieval import RetrievalError, SourceSpecificQuery
from src.utils.exceptions import FixtureManifestError

_SOURCE: EvidenceSourceName = "clinical_trials_gov"


def _content_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class ClinicalTrialsAdapter:
    """Offline-first ClinicalTrials.gov adapter reading versioned JSON fixtures."""

    source_name: EvidenceSourceName = _SOURCE

    def __init__(self, fixture_dir: Path) -> None:
        self._fixture_dir = Path(fixture_dir)

    def fetch(self, query: SourceSpecificQuery, run_id: str) -> RawFetchResult:
        manifest_path = self._fixture_dir / "manifest.json"
        if not manifest_path.exists():
            err = RetrievalError(
                source_name=_SOURCE,
                error_type="fixture_missing",
                message=f"ClinicalTrials fixture manifest not found: {manifest_path}",
            )
            return RawFetchResult(source_name=_SOURCE, errors=[err])

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise FixtureManifestError(f"Cannot parse ClinicalTrials manifest: {exc}") from exc

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
                        message=f"ClinicalTrials fixture file missing: {fname}",
                        is_fatal_for_source=False,
                    )
                )
                continue
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                studies: list[dict[str, Any]] = data if isinstance(data, list) else [data]
                for study in studies:
                    nct_id = study.get("protocolSection", {}).get("identificationModule", {}).get(
                        "nctId", ""
                    ) or study.get("nct_id", "")
                    if not nct_id:
                        continue
                    ch = _content_hash(study)
                    records.append(
                        RawEvidenceRecord(
                            id=f"raw-ct-{nct_id}-{ch}",
                            source_name=_SOURCE,
                            retrieval_run_id=run_id,
                            source_identifier=nct_id,
                            raw_payload=study,
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
                        message=f"Failed to parse ClinicalTrials fixture '{fname}': {exc}",
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
        query_string: str,
        run_id: str,
        max_results: int = 50,
    ) -> RawFetchResult:
        """Fetch from the live ClinicalTrials.gov v2 REST API.

        Mark tests with ``@pytest.mark.live`` and skip by default.
        """
        import httpx

        base = "https://clinicaltrials.gov/api/v2/studies"
        params: dict[str, str | int] = {
            "query.term": query_string,
            "pageSize": min(max_results, 100),
            "format": "json",
        }
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(base, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            from src.utils.exceptions import RetrievalParseError

            raise RetrievalParseError(f"ClinicalTrials live fetch failed: {exc}") from exc

        studies = data.get("studies", [])
        records: list[RawEvidenceRecord] = []
        for study in studies:
            nct_id = (
                study.get("protocolSection", {})
                .get("identificationModule", {})
                .get("nctId", f"NCTUNK-{uuid.uuid4().hex[:6]}")
            )
            ch = _content_hash(study)
            records.append(
                RawEvidenceRecord(
                    id=f"raw-ct-{nct_id}-{ch}",
                    source_name=_SOURCE,
                    retrieval_run_id=run_id,
                    source_identifier=nct_id,
                    raw_payload=study,
                    content_hash=ch,
                    fetched_at=datetime.now(UTC),
                    is_fixture_data=False,
                )
            )
        return RawFetchResult(source_name=_SOURCE, records=records)
