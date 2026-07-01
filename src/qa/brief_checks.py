"""Brief QA checks BQ-001 through BQ-016.

All checks operate on a completed EvidenceBrief and its immutable EvidenceSnapshot.
Results are returned as a list of dicts compatible with the brief_qa_results table.
"""

from __future__ import annotations

import re
from typing import Any

from src.schemas.brief import (
    _REQUIRED_DISCLAIMER_FRAGMENT,
    EvidenceBrief,
    EvidenceSnapshot,
)

_RECOMMENDATION_RE = re.compile(
    r"\b(the\s+patient\s+should|you\s+should\s+take|prescribe|"
    r"start\s+this\s+medication\s+for|stop\s+taking|"
    r"recommended\s+for\s+\[?\w+|"
    r"patients?\s+should\s+be\s+started\s+on|"
    r"initiat\w+\s+treatment\s+for\s+\w+\s+patient)\b",
    re.IGNORECASE,
)

_CAUSAL_RE = re.compile(
    r"\b(causes?|proves?\s+that|prevents?\s+(?!the\s+risk)|directly\s+results?\s+in|"
    r"demonstrates?\s+that\s+\w+\s+causes?|leads?\s+to\s+\w+\s+by\s+causing)\b",
    re.IGNORECASE,
)

_ASSOCIATED_OK_RE = re.compile(
    r"\b(associated\s+with|observed\s+in|reported\s+among|the\s+study\s+found|"
    r"was\s+linked\s+to|showed\s+an\s+association)\b",
    re.IGNORECASE,
)


def _qa(
    check_id: str,
    check_name: str,
    status: str,
    description: str,
    severity: str,
    details: str | None = None,
    affected: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "check_name": check_name,
        "status": status,
        "description": description,
        "severity": severity,
        "details": details,
        "affected": affected or [],
    }


def run_brief_checks(
    brief: EvidenceBrief,
    snapshot: EvidenceSnapshot,
) -> list[dict[str, Any]]:
    """Run all BQ-001 through BQ-016 checks. Return list of result dicts."""
    results: list[dict[str, Any]] = []
    valid_ids = {r.evidence_id for r in snapshot.records}
    cms_ids = {r.evidence_id for r in snapshot.records if r.source_type == "cms_coverage"}
    trial_no_results_ids = {
        r.evidence_id
        for r in snapshot.records
        if r.source_type == "clinical_trial"
        and any("results not yet posted" in w.lower() for w in r.warnings)
    }
    obs_ids = {
        r.evidence_id
        for r in snapshot.records
        if r.source_type == "publication"
        and any(t.startswith("design:observational") for t in r.tags)
    }
    local_cms_ids = {
        r.evidence_id
        for r in snapshot.records
        if r.source_type == "cms_coverage"
        and any("local coverage determination" in w.lower() for w in r.warnings)
    }
    # BQ-001: Required citations
    missing_cits = []
    for c in brief.claims:
        if c.claim_type in ("supported", "exploratory") and not c.source_ids:
            missing_cits.append(c.claim_id)
    if missing_cits:
        results.append(
            _qa(
                "bq-001",
                "Required citations",
                "failed",
                "Every supported or exploratory claim requires at least one source_id.",
                "critical",
                affected=missing_cits,
                details=f"{len(missing_cits)} claim(s) missing citations.",
            )
        )
    else:
        results.append(
            _qa(
                "bq-001",
                "Required citations",
                "passed",
                "Every supported or exploratory claim has at least one source_id.",
                "info",
            )
        )

    # BQ-002: Citation existence
    ghost_cits = []
    for c in brief.claims:
        for sid in c.source_ids:
            if sid not in valid_ids:
                ghost_cits.append(f"{c.claim_id}:{sid}")
    if ghost_cits:
        results.append(
            _qa(
                "bq-002",
                "Citation existence",
                "failed",
                "Every source_id must exist in the immutable evidence snapshot.",
                "critical",
                affected=ghost_cits[:10],
                details=f"{len(ghost_cits)} unknown source_id(s) detected.",
            )
        )
    else:
        results.append(
            _qa(
                "bq-002",
                "Citation existence",
                "passed",
                "All source_ids exist in the evidence snapshot.",
                "info",
            )
        )

    # BQ-003: Disclaimer integrity
    disc = brief.disclaimer
    if not disc or _REQUIRED_DISCLAIMER_FRAGMENT not in disc:
        results.append(
            _qa(
                "bq-003",
                "Disclaimer integrity",
                "failed",
                "Required safety language must be present in the disclaimer.",
                "critical",
                details="Disclaimer missing required fragment.",
            )
        )
    else:
        results.append(
            _qa(
                "bq-003",
                "Disclaimer integrity",
                "passed",
                "Disclaimer contains required safety language.",
                "info",
            )
        )

    # BQ-004: Source-to-claim compatibility
    incompatible = []
    for c in brief.claims:
        if c.dimension in ("outcome", "safety") and c.claim_type == "supported":
            cited = set(c.source_ids)
            # CMS only for effectiveness
            if cited and cited.issubset(cms_ids):
                incompatible.append(f"{c.claim_id}:cms-as-effectiveness")
            # Trial without results only for outcome claim
            if cited and cited.issubset(trial_no_results_ids):
                incompatible.append(f"{c.claim_id}:trial-no-results-as-outcome")
        if c.dimension == "coverage" and c.claim_type == "supported":
            # CMS for coverage claim is fine
            pass
    if incompatible:
        results.append(
            _qa(
                "bq-004",
                "Source-to-claim compatibility",
                "failed",
                "Source types must be appropriate for claim dimension.",
                "critical",
                affected=incompatible,
                details=f"{len(incompatible)} incompatible source-to-claim pairing(s).",
            )
        )
    else:
        results.append(
            _qa(
                "bq-004",
                "Source-to-claim compatibility",
                "passed",
                "Source types are compatible with their claim dimensions.",
                "info",
            )
        )

    # BQ-005: Patient-specific recommendation detection
    rec_claims = []
    for c in brief.claims:
        if _RECOMMENDATION_RE.search(c.text):
            rec_claims.append(c.claim_id)
    if rec_claims:
        results.append(
            _qa(
                "bq-005",
                "Patient-specific recommendation detection",
                "failed",
                "Patient-specific recommendations are prohibited.",
                "critical",
                affected=rec_claims,
                details=f"{len(rec_claims)} claim(s) contain prohibited recommendation language.",
            )
        )
    else:
        results.append(
            _qa(
                "bq-005",
                "Patient-specific recommendation detection",
                "passed",
                "No patient-specific recommendation language detected.",
                "info",
            )
        )

    # BQ-006: Causal-language detection
    causal_violations = []
    for c in brief.claims:
        if _CAUSAL_RE.search(c.text) and not _ASSOCIATED_OK_RE.search(c.text):
            cited_obs_or_cms = set(c.source_ids) & (obs_ids | cms_ids)
            if cited_obs_or_cms:
                causal_violations.append(c.claim_id)
    if causal_violations:
        results.append(
            _qa(
                "bq-006",
                "Causal-language detection",
                "warning",
                "Causal language detected with observational or CMS sources.",
                "major",
                affected=causal_violations,
                details=(
                    f"{len(causal_violations)} claim(s) use causal language with non-RCT sources."
                ),
            )
        )
    else:
        results.append(
            _qa(
                "bq-006",
                "Causal-language detection",
                "passed",
                "No causal language detected with observational/CMS sources.",
                "info",
            )
        )

    # BQ-007: Generation provenance
    prov = brief.provenance
    prov_missing = []
    if not brief.generation_mode:
        prov_missing.append("generation_mode")
    if brief.generation_mode == "live_llm":
        if not (prov and prov.model_provider):
            prov_missing.append("model_provider")
        if not (prov and prov.model_name):
            prov_missing.append("model_name")
        if not (prov and prov.prompt_version):
            prov_missing.append("prompt_version")
    if not brief.evidence_snapshot_hash:
        prov_missing.append("evidence_snapshot_hash")
    if not brief.schema_version:
        prov_missing.append("schema_version")
    if prov_missing:
        results.append(
            _qa(
                "bq-007",
                "Generation provenance",
                "failed",
                "Complete provenance metadata is required.",
                "critical",
                details=f"Missing: {prov_missing}",
            )
        )
    else:
        results.append(
            _qa(
                "bq-007",
                "Generation provenance",
                "passed",
                "All required provenance fields are present.",
                "info",
            )
        )

    # BQ-008: Generation-mode accuracy
    if brief.generation_mode == "live_llm" and (not prov or not prov.model_name):
        results.append(
            _qa(
                "bq-008",
                "Generation-mode accuracy",
                "failed",
                "Brief claims live_llm mode but no model_name recorded.",
                "critical",
                details="model_name must be set when generation_mode='live_llm'.",
            )
        )
    elif brief.generation_mode == "deterministic" and prov and prov.model_name:
        results.append(
            _qa(
                "bq-008",
                "Generation-mode accuracy",
                "warning",
                "Brief claims deterministic mode but model_name is set.",
                "major",
                details="model_name should be None for deterministic mode.",
            )
        )
    else:
        results.append(
            _qa(
                "bq-008",
                "Generation-mode accuracy",
                "passed",
                "Generation mode is consistent with provenance metadata.",
                "info",
            )
        )

    # BQ-009: Evidence-run integrity
    if not brief.evidence_run_id:
        results.append(
            _qa(
                "bq-009",
                "Evidence-run integrity",
                "failed",
                "Brief must be linked to a valid evidence retrieval run.",
                "critical",
                details="evidence_run_id is missing.",
            )
        )
    elif not brief.evidence_snapshot_id or not brief.evidence_snapshot_hash:
        results.append(
            _qa(
                "bq-009",
                "Evidence-run integrity",
                "failed",
                "Brief must be linked to an immutable evidence snapshot.",
                "critical",
                details="evidence_snapshot_id or evidence_snapshot_hash is missing.",
            )
        )
    else:
        results.append(
            _qa(
                "bq-009",
                "Evidence-run integrity",
                "passed",
                "Brief is linked to a valid evidence run and snapshot.",
                "info",
            )
        )

    # BQ-010: Partial-source disclosure
    failed_sources = [sn for sn, st in snapshot.source_statuses.items() if st == "failed"]
    if failed_sources:
        lim_text = " ".join(brief.limitations).lower()
        disclosed = any(src in lim_text for src in failed_sources)
        if not disclosed:
            results.append(
                _qa(
                    "bq-010",
                    "Partial-source disclosure",
                    "warning",
                    "Failed sources must be disclosed in the brief limitations.",
                    "major",
                    affected=failed_sources,
                    details=f"Sources not disclosed in limitations: {failed_sources}",
                )
            )
        else:
            results.append(
                _qa(
                    "bq-010",
                    "Partial-source disclosure",
                    "passed",
                    "Failed sources are disclosed in the brief limitations.",
                    "info",
                )
            )
    else:
        results.append(
            _qa(
                "bq-010",
                "Partial-source disclosure",
                "not_applicable",
                "No failed sources in this run.",
                "info",
            )
        )

    # BQ-011: Claim citation coverage
    total_factual = sum(1 for c in brief.claims if c.claim_type in ("supported", "exploratory"))
    cited_factual = sum(
        1 for c in brief.claims if c.claim_type in ("supported", "exploratory") and c.source_ids
    )
    coverage_pct = (cited_factual / total_factual * 100) if total_factual > 0 else 100.0
    if coverage_pct < 100.0:
        results.append(
            _qa(
                "bq-011",
                "Claim citation coverage",
                "failed",
                "All factual claims must have valid citations.",
                "critical",
                details=f"Citation coverage: {coverage_pct:.0f}% ({cited_factual}/{total_factual})",
            )
        )
    else:
        results.append(
            _qa(
                "bq-011",
                "Claim citation coverage",
                "passed",
                "All factual claims have citations.",
                "info",
                details=f"Citation coverage: 100% ({cited_factual}/{total_factual})",
            )
        )

    # BQ-012: Data-origin accuracy
    origin_map = {
        "live_api": "live API records",
        "captured_source_fixture": "captured public-source records",
        "manually_constructed_fixture": "demonstration fixtures",
        "mixed": "combination of sources",
    }
    expected_notice_fragment = origin_map.get(brief.data_origin, "")
    notice_ok = expected_notice_fragment.lower() in brief.data_notice.lower()
    if not notice_ok:
        results.append(
            _qa(
                "bq-012",
                "Data-origin accuracy",
                "failed",
                "Data notice must accurately reflect the origin classification.",
                "critical",
                details=f"data_origin={brief.data_origin!r} but notice may not match.",
            )
        )
    else:
        results.append(
            _qa(
                "bq-012",
                "Data-origin accuracy",
                "passed",
                "Data notice is consistent with data_origin classification.",
                "info",
            )
        )

    # BQ-013: Trial-status accuracy
    trial_violations = []
    for c in brief.claims:
        if c.dimension in ("outcome", "safety") and c.claim_type == "supported":
            for sid in c.source_ids:
                if sid in trial_no_results_ids:
                    trial_violations.append(f"{c.claim_id}:{sid}")
    if trial_violations:
        results.append(
            _qa(
                "bq-013",
                "Trial-status accuracy",
                "warning",
                "Registered trials without posted results must not support outcome claims.",
                "major",
                affected=trial_violations[:10],
                details=f"{len(trial_violations)} outcome claim(s) cite unresulted trials.",
            )
        )
    else:
        results.append(
            _qa(
                "bq-013",
                "Trial-status accuracy",
                "passed",
                "No outcome claims rely solely on unresulted trial registrations.",
                "info",
            )
        )

    # BQ-014: Coverage-jurisdiction accuracy
    jurisdiction_violations = []
    for c in brief.claims:
        if c.dimension == "coverage":
            for sid in c.source_ids:
                if sid in local_cms_ids:
                    # Check if text incorrectly says "nationally"
                    if re.search(r"\bnational\w*\b", c.text, re.IGNORECASE):
                        jurisdiction_violations.append(c.claim_id)
    if jurisdiction_violations:
        results.append(
            _qa(
                "bq-014",
                "Coverage-jurisdiction accuracy",
                "warning",
                "Local CMS policies must not be described as nationally applicable.",
                "major",
                affected=jurisdiction_violations,
                details=(
                    f"{len(jurisdiction_violations)} coverage claim(s) may "
                    "misrepresent jurisdiction."
                ),
            )
        )
    else:
        results.append(
            _qa(
                "bq-014",
                "Coverage-jurisdiction accuracy",
                "passed",
                "Coverage claims correctly represent CMS jurisdiction scope.",
                "info",
            )
        )

    # BQ-015: Unsupported numeric claim
    # Check that numbers in claim text can be traced to structured fields
    # (In deterministic mode, all templates are pre-validated; in LLM mode, flag for review)
    if brief.generation_mode == "live_llm":
        numeric_claims = [
            c.claim_id for c in brief.claims if re.search(r"\d+(\.\d+)?\s*%|\d{3,}", c.text)
        ]
        if numeric_claims:
            results.append(
                _qa(
                    "bq-015",
                    "Unsupported numeric claim",
                    "warning",
                    "Numeric values in LLM-generated claims require human review "
                    "for source traceability.",
                    "critical",
                    affected=numeric_claims[:10],
                    details=(
                        f"{len(numeric_claims)} claim(s) contain numeric values. "
                        "Verify each number traces to a structured field in the source record."
                    ),
                )
            )
        else:
            results.append(
                _qa(
                    "bq-015",
                    "Unsupported numeric claim",
                    "passed",
                    "No complex numeric values detected in LLM-generated claims.",
                    "info",
                )
            )
    else:
        results.append(
            _qa(
                "bq-015",
                "Unsupported numeric claim",
                "not_applicable",
                "Deterministic mode: claim templates are pre-validated.",
                "info",
            )
        )

    # BQ-016: Review and audit integrity
    if brief.human_review_status == "approved":
        # Reviews should have at least one record
        # (checked at service level; here just report the status)
        results.append(
            _qa(
                "bq-016",
                "Review and audit integrity",
                "passed",
                "Brief has been approved; review record is expected in the audit log.",
                "info",
            )
        )
    else:
        results.append(
            _qa(
                "bq-016",
                "Review and audit integrity",
                "not_applicable",
                "Brief has not been approved; no review audit required yet.",
                "info",
            )
        )

    return results


def has_critical_failures(qa_results: list[dict[str, Any]]) -> bool:
    return any(r["status"] == "failed" and r["severity"] == "critical" for r in qa_results)


def citation_coverage_pct(qa_results: list[dict[str, Any]]) -> float:
    for r in qa_results:
        if r["check_id"] == "bq-011" and r["details"]:
            import re as _re

            m = _re.search(r"(\d+(?:\.\d+)?)\s*%", r["details"])
            if m:
                return float(m.group(1))
    return 100.0
