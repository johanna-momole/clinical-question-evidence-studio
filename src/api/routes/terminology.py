"""FastAPI routes for terminology verification (RxNorm).

Phase 4 endpoint:
  POST /terminology/rxnorm/verify — verify one or more RxCUIs against offline fixture

The adapter NEVER auto-promotes a mapping to 'approved'. Verification results document
what was found; a human reviewer must apply the result to update TerminologyMapping.review_status.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.evidence_sources.registry import get_rxnorm_adapter
from src.schemas.terminology_verification import (
    TerminologyVerificationRequest,
    TerminologyVerificationResult,
)
from src.utils.exceptions import FixtureManifestError

router = APIRouter(prefix="/terminology", tags=["qa"])

_FIXTURE_DIR = Path("data/fixtures")


class RxNormVerifyRequest(BaseModel):
    rxcuis: list[str]
    phenotype_id: str | None = "pheno-sglt2-ckd-t2dm-001"


class RxNormVerifyResponse(BaseModel):
    results: list[TerminologyVerificationResult]
    data_notice: str = (
        "Verification results are served from versioned offline fixtures. "
        "They are NOT guaranteed to reflect the current live RxNorm database. "
        "Always verify against the live RxNorm API before clinical use. "
        "Applying a verification result to update a mapping REQUIRES explicit human-reviewer action."
    )


@router.post("/rxnorm/verify", response_model=RxNormVerifyResponse)
def verify_rxcuis(request: RxNormVerifyRequest) -> RxNormVerifyResponse:
    """Verify one or more RxCUIs against the offline RxNorm fixture.

    Returns verification results for each RxCUI. Results are informational only —
    no mapping status is changed automatically.
    """
    adapter = get_rxnorm_adapter()
    results: list[TerminologyVerificationResult] = []

    for rxcui in request.rxcuis:
        req = TerminologyVerificationRequest(
            rxcui=rxcui.strip(),
            phenotype_id=request.phenotype_id,
            offline_only=True,
        )
        try:
            result = adapter.verify(req)
            results.append(result)
        except FixtureManifestError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"RxNorm fixture unavailable: {exc}",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"RxNorm verification failed for {rxcui}: {exc}"
            ) from exc

    return RxNormVerifyResponse(results=results)
