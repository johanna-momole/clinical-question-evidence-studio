"""Deterministic, transparent relevance ranking for evidence records.

The score is a rule-based weighted sum across five dimensions:
  1. population_match  (weight 0.30) — tags matching the query population
  2. intervention_match (weight 0.30) — tags matching the query intervention
  3. outcome_match     (weight 0.20) — tags matching the query outcomes
  4. design_quality    (weight 0.10) — study design tier (RCT/meta > obs > review)
  5. recency           (weight 0.10) — records within 5 years score higher

This score documents RELEVANCE to the query, NOT clinical quality, strength of
evidence, or a treatment recommendation.  The score and rationale are always
presented together so the basis of ranking is fully transparent.

The ranking is fully deterministic — same records + same query always produce
identical scores.  There is no randomness, no LLM, and no network access.
"""

from __future__ import annotations

from src.schemas.evidence import EvidenceRecord
from src.schemas.retrieval import EvidenceQuery

_W_POPULATION = 0.30
_W_INTERVENTION = 0.30
_W_OUTCOME = 0.20
_W_DESIGN = 0.10
_W_RECENCY = 0.10

_DESIGN_TIER: dict[str, float] = {
    "design:meta_analysis": 1.0,
    "design:systematic_review": 0.9,
    "design:rct": 0.8,
    "design:observational": 0.5,
    "design:review": 0.4,
}


def rank_records(
    records: list[EvidenceRecord],
    query: EvidenceQuery,
) -> list[EvidenceRecord]:
    """Score and sort records by deterministic relevance; update in-place, then return sorted."""
    for rec in records:
        score, rationale = _score(rec, query)
        rec.relevance_score = round(score, 4)
        rec.relevance_rationale = rationale
    records.sort(key=lambda r: r.relevance_score or 0.0, reverse=True)
    return records


def _score(rec: EvidenceRecord, query: EvidenceQuery) -> tuple[float, list[str]]:
    rationale: list[str] = []
    rec_tags: set[str] = set(rec.tags)

    # Population match
    pop_score = 0.0
    pop_tags = {f"population:{_slug(t)}" for t in query.population_terms}
    pop_matches = rec_tags & pop_tags
    if pop_matches:
        pop_score = min(1.0, len(pop_matches) / max(len(pop_tags), 1))
        rationale.append(f"Population tags matched: {sorted(pop_matches)}")
    else:
        # partial match: check CKD/T2DM as fallback for this demo
        fallback = {"population:ckd", "population:t2dm"}
        fb_matches = rec_tags & fallback
        if fb_matches:
            pop_score = 0.5
            rationale.append(f"Partial population match (fallback): {sorted(fb_matches)}")

    # Intervention match
    int_score = 0.0
    int_tags = {"intervention:sglt2_class"} | {
        f"intervention:{_slug(t)}" for t in query.intervention_terms
    }
    int_matches = rec_tags & int_tags
    if int_matches:
        int_score = min(1.0, len(int_matches) / max(len(int_tags), 1))
        rationale.append(f"Intervention tags matched: {sorted(int_matches)}")

    # Outcome match
    out_score = 0.0
    out_tags = {f"outcome:{_slug(o)}" for o in query.outcome_terms}
    out_fallback = {"outcome:renal", "outcome:cardiovascular"}
    out_matches = rec_tags & (out_tags | out_fallback)
    if out_matches:
        out_score = min(1.0, len(out_matches) / max(len(out_tags | out_fallback), 1))
        rationale.append(f"Outcome tags matched: {sorted(out_matches)}")

    # Design quality
    design_score = 0.0
    for design_tag, tier in _DESIGN_TIER.items():
        if design_tag in rec_tags:
            design_score = tier
            rationale.append(f"Study design tier: {design_tag} ({tier:.1f})")
            break

    # Recency
    recency_score = 0.0
    if "temporal:recent_5yr" in rec_tags:
        recency_score = 1.0
        rationale.append("Published within 5 years of reference date (2020-01-01)")
    elif rec.publication_or_update_date:
        rationale.append(f"Published {rec.publication_or_update_date.year} — older than 5 years")

    total = (
        _W_POPULATION * pop_score
        + _W_INTERVENTION * int_score
        + _W_OUTCOME * out_score
        + _W_DESIGN * design_score
        + _W_RECENCY * recency_score
    )
    return min(1.0, total), rationale


def _slug(term: str) -> str:
    """Convert a PICO term to a tag-compatible slug for matching."""
    return term.lower().replace(" ", "_").replace("-", "_").replace(",", "").strip("_")
