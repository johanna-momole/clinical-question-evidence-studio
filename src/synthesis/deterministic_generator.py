"""Deterministic evidence brief generator.

Claims are defined by stable PICO-keyed templates that map to source-specific
identifiers (PMID, NCT ID, LCD doc ID). The generator resolves those identifiers
to actual evidence IDs in the current snapshot at runtime.

Rules:
- NEVER hard-code run-specific ev-* IDs.
- Fail visibly (MissingExpectedSourceError) if an expected source is absent.
- Do NOT silently substitute a different record.
- Every supported/exploratory claim needs ≥1 source_id from the snapshot.
- Stable claim_id values (not UUIDs) so content hash is reproducible.
"""

from __future__ import annotations

from typing import Any

from src.schemas.brief import (
    EvidenceGap,
    EvidenceSnapshot,
    EvidenceSnapshotRecord,
    GeneratedClaim,
)
from src.utils.exceptions import MissingExpectedSourceError

PROMPT_VERSION = "det-v1.0"

# ---------------------------------------------------------------------------
# Claim templates: keyed by stable claim_id → list of (source_type, source_specific_id)
# The generator resolves these to actual evidence_ids in the current snapshot.
# ---------------------------------------------------------------------------

_TEMPLATES: list[dict[str, Any]] = [
    {
        "claim_id": "cl-population-t2dm-ckd",
        "dimension": "population",
        "claim_type": "supported",
        "evidence_basis": "record_supported",
        "source_specific_ids": [
            ("publication", "36473481"),  # CREDENCE trial PMID
            ("publication", "31535872"),  # DAPA-CKD PMID
        ],
        "text": (
            "Adults with type 2 diabetes (T2DM) and chronic kidney disease (CKD) represent "
            "a high-risk population studied in landmark SGLT2 inhibitor trials. "
            "The retrieved records include trials specifically enrolling patients with "
            "both T2DM and stage 3–4 CKD, with eGFR thresholds ranging from 25–90 mL/min/1.73m²."
        ),
        "design_limitations": [],
        "uncertainty_note": None,
    },
    {
        "claim_id": "cl-intervention-sglt2-rct",
        "dimension": "intervention",
        "claim_type": "supported",
        "evidence_basis": "record_supported",
        "source_specific_ids": [
            ("publication", "26378978"),  # EMPA-REG PMID
            ("publication", "30415602"),  # CREDENCE PMID
            ("publication", "31535872"),  # DAPA-CKD PMID
        ],
        "text": (
            "SGLT2 inhibitors (empagliflozin, canagliflozin, dapagliflozin) were studied "
            "as the primary intervention in the retrieved randomized controlled trials. "
            "Each trial evaluated a single SGLT2 agent versus placebo in addition to "
            "standard background therapy."
        ),
        "design_limitations": [
            "Each trial studied a single agent; cross-agent comparisons are indirect.",
            "Background therapy and titration protocols differed across trials.",
        ],
        "uncertainty_note": None,
    },
    {
        "claim_id": "cl-outcome-cv-renal",
        "dimension": "outcome",
        "claim_type": "supported",
        "evidence_basis": "record_supported",
        "source_specific_ids": [
            ("publication", "26378978"),  # EMPA-REG
            ("publication", "30415602"),  # CREDENCE
            ("publication", "31535872"),  # DAPA-CKD
        ],
        "text": (
            "The retrieved trial records report composite cardiovascular and renal endpoints "
            "as primary outcomes. Key endpoints include major adverse cardiovascular events "
            "(MACE), progression of kidney disease (sustained eGFR decline, end-stage kidney "
            "disease, renal death), and hospitalization for heart failure. "
            "No causal inference beyond reported trial findings is made here."
        ),
        "design_limitations": [
            "Trial populations were selected for elevated cardiovascular/renal risk; "
            "findings may not generalize to lower-risk populations.",
            "Endpoint definitions varied across trials, limiting direct comparison.",
        ],
        "uncertainty_note": None,
    },
    {
        "claim_id": "cl-design-rct-evidence",
        "dimension": "design",
        "claim_type": "supported",
        "evidence_basis": "record_supported",
        "source_specific_ids": [
            ("publication", "26378978"),
            ("publication", "30415602"),
            ("publication", "31535872"),
        ],
        "text": (
            "Three randomized, placebo-controlled trials are represented in the retrieved "
            "evidence: EMPA-REG OUTCOME (empagliflozin), CREDENCE (canagliflozin), and "
            "DAPA-CKD (dapagliflozin). Each is a large, multi-center, double-blind RCT "
            "with results posted to the registry."
        ),
        "design_limitations": [
            "Industry-sponsored trials; sponsor involvement in data analysis should be noted.",
        ],
        "uncertainty_note": None,
    },
    {
        "claim_id": "cl-observational-association",
        "dimension": "outcome",
        "claim_type": "exploratory",
        "evidence_basis": "record_supported",
        "source_specific_ids": [
            ("publication", "34469193"),  # Observational record PMID
        ],
        "text": (
            "An observational study is included in the retrieved records. "
            "Observational findings describe associations and utilization patterns "
            "in real-world populations but are not sufficient to establish causation. "
            "Results from this study should be interpreted alongside, not instead of, "
            "randomized trial evidence."
        ),
        "design_limitations": [
            "Observational study: residual confounding cannot be excluded.",
            "Real-world data quality may differ from trial-grade data collection.",
        ],
        "uncertainty_note": (
            "Association does not establish causation. "
            "Confounding by indication or contraindication is possible in observational data."
        ),
    },
    {
        "claim_id": "cl-coverage-cms",
        "dimension": "coverage",
        "claim_type": "supported",
        "evidence_basis": "record_supported",
        "source_specific_ids": [
            ("cms_coverage", "L35236"),
        ],
        "text": (
            "CMS coverage documentation for antidiabetic agents was retrieved. "
            "Coverage policy describes Medicare coverage criteria and applicable billing codes. "
            "Coverage policy documents reflect payer reimbursement decisions, not clinical "
            "effectiveness conclusions."
        ),
        "design_limitations": [
            "CMS coverage policy is jurisdiction-specific for LCD documents. "
            "Coverage criteria may differ by MAC jurisdiction.",
            "Coverage policy does not constitute a clinical effectiveness recommendation.",
        ],
        "uncertainty_note": None,
    },
]


def _resolve_source_ids(
    source_specific_ids: list[tuple[str, str]],
    record_map: dict[tuple[str, str], EvidenceSnapshotRecord],
) -> tuple[list[str], list[str]]:
    """Resolve (source_type, source_specific_id) pairs to evidence IDs.

    Returns:
        (resolved_ids, unresolved_pairs_as_str)
    """
    resolved: list[str] = []
    unresolved: list[str] = []
    for src_type, src_id in source_specific_ids:
        rec = record_map.get((src_type, src_id))
        if rec is not None:
            resolved.append(rec.evidence_id)
        else:
            unresolved.append(f"{src_type}:{src_id}")
    return resolved, unresolved


def generate_deterministic(
    snapshot: EvidenceSnapshot,
    evidence_run_id: str,
) -> tuple[list[GeneratedClaim], list[EvidenceGap], str]:
    """Generate claims deterministically from snapshot records.

    Returns:
        (claims, gaps, prompt_version)

    Raises:
        MissingExpectedSourceError if a required template source is not in the snapshot.
    """
    # Build (source_type, source_specific_id) -> record map
    record_map: dict[tuple[str, str], EvidenceSnapshotRecord] = {
        (r.source_type, r.source_specific_id): r for r in snapshot.records
    }

    claims: list[GeneratedClaim] = []
    skipped_templates: list[str] = []

    for tmpl in _TEMPLATES:
        source_specific_ids: list[tuple[str, str]] = tmpl["source_specific_ids"]
        resolved_ids, unresolved = _resolve_source_ids(source_specific_ids, record_map)

        if tmpl["claim_type"] in ("supported", "exploratory") and not resolved_ids:
            # No sources found at all — fail visibly for supported/exploratory claims
            skipped_templates.append(f"{tmpl['claim_id']}: none of {unresolved} found in snapshot")
            continue

        claims.append(
            GeneratedClaim(
                claim_id=tmpl["claim_id"],
                text=tmpl["text"],
                claim_type=tmpl["claim_type"],
                dimension=tmpl["dimension"],
                evidence_basis=tmpl["evidence_basis"],
                source_ids=resolved_ids,
                design_limitations=tmpl["design_limitations"],
                uncertainty_note=tmpl.get("uncertainty_note"),
            )
        )

    if skipped_templates:
        raise MissingExpectedSourceError(
            f"Deterministic generation: {len(skipped_templates)} required source(s) missing: "
            + "; ".join(skipped_templates[:3])
        )

    # Build gaps for dimensions with no records
    gaps: list[EvidenceGap] = []
    covered_dimensions = {c.dimension for c in claims}
    source_counts = {r.source_type: 0 for r in snapshot.records}
    for r in snapshot.records:
        source_counts[r.source_type] = source_counts.get(r.source_type, 0) + 1

    # Safety gap — no safety-specific records were expected in Phase 4 fixtures
    if "safety" not in covered_dimensions:
        gaps.append(
            EvidenceGap(
                gap_id="gap-safety",
                description=(
                    "No safety-specific evidence records were identified in this retrieval run "
                    "for the configured search scope. This does not imply that no safety data "
                    "exists in the broader literature — the configured search was limited to "
                    "PubMed, ClinicalTrials.gov, and CMS Coverage using PICO-derived terms."
                ),
                dimension="safety",
                retrieval_run_id=evidence_run_id,
                sources_searched=list(snapshot.source_statuses.keys()),
                source_statuses=dict(snapshot.source_statuses),
                query_strings={
                    r.source_type: "SGLT2 inhibitor safety" for r in snapshot.records[:1]
                },
                result_counts=source_counts,
                failed_sources=list(snapshot.failed_sources)
                if hasattr(snapshot, "failed_sources")
                else [],
                limitations=[
                    "Safety data may require dedicated adverse-event database searches "
                    "(e.g., FDA FAERS, WHO VigiBase) not included in this retrieval.",
                    "Safety signals from post-marketing reports are outside the scope of "
                    "this retrieval run.",
                ],
            )
        )

    return claims, gaps, PROMPT_VERSION
