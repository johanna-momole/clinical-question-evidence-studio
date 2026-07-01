"""Citation resolver: maps evidence IDs to numbered ClaimCitation objects.

Citation numbering is stable within a brief version:
  - Numbers are assigned in the order claims appear (by claim_id alphabetical sort).
  - Each unique source_id gets exactly one citation number; subsequent references
    reuse the same number.
"""

from __future__ import annotations

from src.schemas.brief import (
    ClaimCitation,
    EvidenceSnapshot,
    EvidenceSnapshotRecord,
    GeneratedClaim,
)


def resolve_citations(
    claims: list[GeneratedClaim],
    snapshot: EvidenceSnapshot,
) -> tuple[list[GeneratedClaim], list[ClaimCitation]]:
    """Attach ClaimCitation objects to claims and build a numbered bibliography.

    Returns:
        claims_with_citations: the updated claim list (same objects, citations populated)
        bibliography: ordered list of unique citations for the full brief
    """
    record_map: dict[str, EvidenceSnapshotRecord] = {r.evidence_id: r for r in snapshot.records}

    # Assign stable citation numbers: walk claims in stable order, number by first occurrence
    number_map: dict[str, int] = {}
    next_num = 1

    # Sort claims by claim_id for stable ordering
    sorted_claims = sorted(claims, key=lambda c: c.claim_id)

    for claim in sorted_claims:
        for sid in claim.source_ids:
            if sid not in number_map and sid in record_map:
                number_map[sid] = next_num
                next_num += 1

    # Build citations for each claim
    updated_claims: list[GeneratedClaim] = []
    for claim in claims:
        cits: list[ClaimCitation] = []
        for sid in claim.source_ids:
            if sid not in record_map:
                continue
            rec = record_map[sid]
            support_type = _infer_support_type(claim, rec)
            cit = ClaimCitation(
                citation_number=number_map.get(sid, 0),
                source_id=sid,
                source_specific_id=rec.source_specific_id,
                source_type=rec.source_type,
                title=rec.title,
                url=rec.url,
                support_type=support_type,
                locator=_infer_locator(claim, rec),
                review_status="pending",
            )
            cits.append(cit)
        # Sort citations by number for display
        cits.sort(key=lambda c: c.citation_number)
        updated_claims.append(claim.model_copy(update={"citations": cits}))

    # Build bibliography in citation-number order
    bibliography: list[ClaimCitation] = []
    seen_ids: set[str] = set()
    # Collect all citations from all claims, deduplicated by source_id
    all_cits: list[ClaimCitation] = [cit for claim in updated_claims for cit in claim.citations]
    all_cits.sort(key=lambda c: c.citation_number)
    for cit in all_cits:
        if cit.source_id not in seen_ids:
            seen_ids.add(cit.source_id)
            bibliography.append(cit)

    return updated_claims, bibliography


def _infer_support_type(claim: GeneratedClaim, rec: EvidenceSnapshotRecord) -> str:
    if claim.claim_type == "insufficient_evidence":
        return "contextual"
    if rec.source_type == "cms_coverage" and claim.dimension != "coverage":
        return "contextual"
    return "direct"


def _infer_locator(claim: GeneratedClaim, rec: EvidenceSnapshotRecord) -> str | None:
    if rec.source_type == "clinical_trial":
        return "trial registration record"
    if rec.source_type == "cms_coverage":
        return "coverage policy document"
    return None
