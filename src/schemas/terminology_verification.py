"""Pydantic schemas for RxNorm terminology verification requests, results, and audit records.

Verification results document what the RxNorm API (or offline fixture) returned for a
given RxCUI. Applying a verification result to update a TerminologyMapping's review_status
ALWAYS requires an explicit human reviewer action — the system never auto-approves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TerminologyVerificationRequest(BaseModel):
    """A request to verify one RxCUI against the RxNorm API (or offline fixture)."""

    rxcui: str = Field(..., description="RxNorm concept unique identifier to verify")
    expected_concept_name: str | None = Field(
        None, description="Expected concept name from the phenotype mapping, for comparison"
    )
    phenotype_id: str | None = Field(
        None, description="Phenotype ID this mapping belongs to, for audit context"
    )
    concept_id: str | None = Field(
        None, description="Phenotype concept_id this mapping belongs to, for audit context"
    )
    offline_only: bool = Field(
        default=True,
        description="If True, use only versioned fixtures — never call the live RxNorm API",
    )


class TerminologyVerificationResult(BaseModel):
    """What the RxNorm API (or offline fixture) said about a given RxCUI."""

    rxcui: str
    found: bool = Field(..., description="True if the RxCUI exists in RxNorm")
    verified_name: str | None = Field(
        None, description="Official concept name returned by RxNorm, if found"
    )
    term_type: str | None = Field(
        None,
        description="RxNorm term type (TTY), e.g., 'IN' (ingredient), 'SCD' (clinical drug)",
    )
    is_active: bool | None = Field(
        None, description="True if the concept is active in the current RxNorm version"
    )
    matches_expected_name: bool | None = Field(
        None,
        description="True if verified_name matches expected_concept_name (case-insensitive). "
        "None if no expected name was provided.",
    )
    source: Literal["rxnorm_api", "rxnorm_fixture"] = Field(
        "rxnorm_fixture",
        description="Whether this result came from the live RxNorm API or an offline fixture",
    )
    verified_at: datetime = Field(default_factory=_utcnow)
    raw_response: dict[str, Any] | None = Field(
        None, description="Raw RxNorm API response payload, for audit"
    )
    is_fixture_data: bool = Field(
        default=True, description="True if this result was loaded from a versioned offline fixture"
    )
    fixture_manifest_version: str | None = None
    notes: list[str] = Field(
        default_factory=list,
        description="Human-readable notes about this verification (e.g., mismatch details)",
    )


class TerminologyVerificationAuditRecord(BaseModel):
    """Audit trail entry created when a human reviewer applies a verification result.

    Applying a verification outcome to update TerminologyMapping.review_status always
    requires an explicit human-reviewer action — the adapter never auto-approves.
    """

    id: str = Field(..., description="Audit record identifier")
    mapping_concept_id: str = Field(..., description="Phenotype concept_id of the updated mapping")
    rxcui: str
    previous_review_status: Literal["candidate", "approved", "rejected"]
    new_review_status: Literal["candidate", "approved", "rejected"]
    verification_result_rxcui: str | None = Field(
        None, description="RxCUI from the TerminologyVerificationResult that informed this decision"
    )
    actor: str = Field(
        default="human_reviewer",
        description="Who applied this change. Must be a human reviewer — "
        "the system never auto-promotes a mapping to 'approved'.",
    )
    applied_at: datetime = Field(default_factory=_utcnow)
    notes: str | None = None
