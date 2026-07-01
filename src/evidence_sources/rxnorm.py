"""RxNorm terminology verification adapter.

Offline fixture mode is the default. This adapter does NOT retrieve evidence records —
it verifies that a given RxCUI exists in RxNorm, captures the official concept name and
term type, and compares the name against the phenotype mapping's expected name.

IMPORTANT — the adapter NEVER updates TerminologyMapping.review_status automatically.
All verification results are stored as TerminologyVerificationResult records.  A human
reviewer must explicitly apply the result to update the mapping's status — see
TerminologyVerificationAuditRecord.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.schemas.terminology_verification import (
    TerminologyVerificationRequest,
    TerminologyVerificationResult,
)
from src.utils.exceptions import FixtureManifestError


class RxNormAdapter:
    """Offline-first RxNorm verification adapter."""

    def __init__(self, fixture_dir: Path) -> None:
        self._fixture_dir = Path(fixture_dir)
        self._fixture_cache: dict[str, dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # Verification (offline fixture)
    # ------------------------------------------------------------------

    def verify(self, request: TerminologyVerificationRequest) -> TerminologyVerificationResult:
        """Verify a RxCUI against the offline fixture (always offline in demo environment)."""
        index = self._load_fixture_index()
        manifest_version = index.get("_manifest_version", "unknown")
        rxcui_data: dict[str, Any] | None = index.get(request.rxcui)

        if rxcui_data is None:
            notes = [
                f"RxCUI {request.rxcui!r} not found in offline fixture index. "
                "This may mean the RxCUI is invalid, or the fixture does not yet cover it. "
                "Run the live verification adapter to check against the authoritative RxNorm API."
            ]
            return TerminologyVerificationResult(
                rxcui=request.rxcui,
                found=False,
                verified_name=None,
                source="rxnorm_fixture",
                verified_at=datetime.now(UTC),
                is_fixture_data=True,
                fixture_manifest_version=manifest_version,
                notes=notes,
            )

        verified_name: str | None = rxcui_data.get("name")
        term_type: str | None = rxcui_data.get("tty")
        is_active: bool | None = rxcui_data.get("is_active")
        raw_response: dict[str, Any] = rxcui_data.get("raw_response", rxcui_data)

        matches: bool | None = None
        notes_list: list[str] = []
        if request.expected_concept_name and verified_name:
            matches = verified_name.lower() == request.expected_concept_name.lower()
            if not matches:
                notes_list.append(
                    f"Name mismatch: expected {request.expected_concept_name!r}, "
                    f"RxNorm returned {verified_name!r}. "
                    "Review whether the phenotype mapping uses the correct concept level "
                    "(ingredient vs. clinical drug vs. branded drug)."
                )

        if is_active is False:
            notes_list.append(
                f"RxCUI {request.rxcui!r} is marked inactive in this fixture. "
                "Verify with the live RxNorm API and consider replacing with the current concept."
            )

        return TerminologyVerificationResult(
            rxcui=request.rxcui,
            found=True,
            verified_name=verified_name,
            term_type=term_type,
            is_active=is_active,
            matches_expected_name=matches,
            source="rxnorm_fixture",
            verified_at=datetime.now(UTC),
            raw_response=raw_response,
            is_fixture_data=True,
            fixture_manifest_version=manifest_version,
            notes=notes_list,
        )

    def ping(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Live verification (excluded from offline test suite)
    # ------------------------------------------------------------------

    def verify_live(self, request: TerminologyVerificationRequest) -> TerminologyVerificationResult:
        """Verify against the live RxNorm API. Mark tests @pytest.mark.live."""
        import httpx

        base = "https://rxnav.nlm.nih.gov/REST"
        notes: list[str] = []
        try:
            with httpx.Client(timeout=15) as client:
                # Check if concept exists
                props_resp = client.get(f"{base}/rxcui/{request.rxcui}/properties.json")
                if props_resp.status_code == 404:
                    return TerminologyVerificationResult(
                        rxcui=request.rxcui,
                        found=False,
                        source="rxnorm_api",
                        verified_at=datetime.now(UTC),
                        is_fixture_data=False,
                        notes=[f"RxCUI {request.rxcui!r} returned 404 from RxNorm API."],
                    )
                props_resp.raise_for_status()
                props = props_resp.json()
        except Exception as exc:
            from src.utils.exceptions import RetrievalParseError

            raise RetrievalParseError(
                f"RxNorm live verification failed for {request.rxcui}: {exc}"
            ) from exc

        concept_props = props.get("properties", {}) or props.get("propConceptGroup", {})
        name = concept_props.get("name")
        tty = concept_props.get("tty")

        matches: bool | None = None
        if request.expected_concept_name and name:
            matches = name.lower() == request.expected_concept_name.lower()
            if not matches:
                notes.append(
                    f"Name mismatch: expected {request.expected_concept_name!r}, "
                    f"RxNorm returned {name!r}."
                )

        return TerminologyVerificationResult(
            rxcui=request.rxcui,
            found=True,
            verified_name=name,
            term_type=tty,
            is_active=True,
            matches_expected_name=matches,
            source="rxnorm_api",
            verified_at=datetime.now(UTC),
            raw_response=props,
            is_fixture_data=False,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_fixture_index(self) -> dict[str, Any]:
        if self._fixture_cache is not None:
            return self._fixture_cache

        manifest_path = self._fixture_dir / "manifest.json"
        if not manifest_path.exists():
            raise FixtureManifestError(f"RxNorm fixture manifest not found: {manifest_path}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise FixtureManifestError(f"Cannot parse RxNorm manifest: {exc}") from exc

        manifest_version = manifest.get("version", "unknown")
        index_path = self._fixture_dir / manifest.get("index_file", "rxnorm_index.json")
        if not index_path.exists():
            raise FixtureManifestError(f"RxNorm index file not found: {index_path}")
        try:
            index: dict[str, Any] = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise FixtureManifestError(f"Cannot parse RxNorm index: {exc}") from exc

        index["_manifest_version"] = manifest_version
        self._fixture_cache = index
        return index
