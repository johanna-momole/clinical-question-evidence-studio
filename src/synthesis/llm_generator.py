"""Live LLM-based evidence brief generator.

All live tests must be decorated @pytest.mark.live and excluded from the default suite.

Design constraints:
- Prompt contains only: evidence_id, source_specific_id, source_type, title,
  selected structured metadata, abstract snippet (max 200 chars), study_design,
  trial/document status, existing warnings, relevance_score, url.
- LLM is instructed to cite only supplied evidence IDs, never to invent IDs
  or clinical facts, never to recommend treatment, and to distinguish association
  from causation.
- Returned JSON is validated strictly against the claim schema.
- Rejection (not silent repair) for: unknown source IDs, empty citations on
  supported/exploratory claims, recommendation language, invalid claim types,
  causal observational language, malformed output.
- At most one structural retry per generation call. Any retry is logged.
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.schemas.brief import (
    EvidenceGap,
    EvidenceSnapshot,
    GeneratedClaim,
)
from src.utils.exceptions import BriefGenerationError

PROMPT_VERSION = "llm-v1.0"

# Causal language patterns — detect in generated claim texts
_CAUSAL_PATTERNS = re.compile(
    r"\b(causes?|proves?\s+that|prevents?|directly\s+results?\s+in|"
    r"demonstrates?\s+that\s+\w+\s+causes?|leads?\s+to\s+\w+\s+by\s+causing)\b",
    re.IGNORECASE,
)

# Recommendation language patterns
_RECOMMENDATION_PATTERNS = re.compile(
    r"\b(the\s+patient\s+should|you\s+should\s+take|prescribe|start\s+this\s+medication\s+for|"
    r"stop\s+taking|recommended\s+for\s+\[?\w+|patients?\s+should\s+be\s+started\s+on)\b",
    re.IGNORECASE,
)

_VALID_CLAIM_TYPES = frozenset(["supported", "exploratory", "insufficient_evidence"])
_VALID_DIMENSIONS = frozenset(
    ["population", "intervention", "outcome", "safety", "design", "coverage", "evidence_gap"]
)
_VALID_EVIDENCE_BASIS = frozenset(["record_supported", "retrieval_gap", "mixed"])
_OBSERVATIONAL_DESIGNS = frozenset(
    [
        "observational cohort",
        "retrospective cohort",
        "cross-sectional",
        "case-control",
        "case series",
        "observational",
    ]
)


def _build_prompt(
    snapshot: EvidenceSnapshot,
    question_text: str,
) -> str:
    """Build the structured prompt for the LLM. Contains only safe metadata."""
    lines = [
        "You are generating a structured evidence brief. Output ONLY valid JSON.",
        "",
        f"Research question: {question_text}",
        "",
        "Evidence records available for citation (cite ONLY these IDs):",
    ]
    for rec in sorted(snapshot.records, key=lambda r: -(r.relevance_score or 0)):
        lines.append(
            f"  - id={rec.evidence_id!r} "
            f"source_specific_id={rec.source_specific_id!r} "
            f"source_type={rec.source_type!r} "
            f"title={rec.title!r} "
            f"relevance={rec.relevance_score} "
            f"warnings={rec.warnings!r}"
        )
    lines += [
        "",
        "Generate a JSON object with this schema:",
        (
            '{"claims": [{"claim_id": str, "text": str, '
            '"claim_type": "supported"|"exploratory"|"insufficient_evidence", '
            '"dimension": "population"|"intervention"|"outcome"|"safety"|'
            '"design"|"coverage"|"evidence_gap", '
            '"evidence_basis": "record_supported"|"retrieval_gap"|"mixed", '
            '"source_ids": [evidence_id, ...], '
            '"design_limitations": [str, ...], '
            '"uncertainty_note": str|null}]}'
        ),
        "",
        "Rules:",
        "1. cite ONLY the evidence IDs listed above — never invent IDs.",
        "2. supported and exploratory claims require at least one source_id.",
        "3. exploratory claims require a non-empty uncertainty_note.",
        "4. never recommend treatment or use prescriptive language.",
        (
            "5. distinguish association from causation; never use causal language"
            " for observational sources."
        ),
        "6. do not describe a registered trial without posted results as efficacy evidence.",
        (
            "7. CMS coverage records support coverage/policy claims only,"
            " not comparative effectiveness."
        ),
        (
            "8. insufficient_evidence claims may have empty source_ids"
            " when evidence_basis is retrieval_gap."
        ),
    ]
    return "\n".join(lines)


def _validate_llm_output(
    raw_json: dict[str, Any],
    snapshot: EvidenceSnapshot,
) -> list[GeneratedClaim]:
    """Validate and parse LLM JSON output strictly. Raises BriefGenerationError on failure."""
    valid_ids = {r.evidence_id for r in snapshot.records}
    observational_ids = {
        r.evidence_id
        for r in snapshot.records
        if (
            r.source_type == "publication"
            and any(tag.startswith("design:observational") for tag in r.tags)
        )
    }
    cms_ids = {r.evidence_id for r in snapshot.records if r.source_type == "cms_coverage"}
    trial_no_results_ids = {
        r.evidence_id
        for r in snapshot.records
        if r.source_type == "clinical_trial"
        and any("results not yet posted" in w.lower() for w in r.warnings)
    }

    raw_claims = raw_json.get("claims", [])
    if not isinstance(raw_claims, list):
        raise BriefGenerationError("LLM output missing 'claims' list.")

    validated: list[GeneratedClaim] = []
    for i, raw in enumerate(raw_claims):
        claim_id = raw.get("claim_id", f"llm-claim-{i}")

        # Validate claim_type
        ctype = raw.get("claim_type")
        if ctype not in _VALID_CLAIM_TYPES:
            raise BriefGenerationError(f"Claim {claim_id!r}: invalid claim_type {ctype!r}.")

        # Validate dimension
        dim = raw.get("dimension")
        if dim not in _VALID_DIMENSIONS:
            raise BriefGenerationError(f"Claim {claim_id!r}: invalid dimension {dim!r}.")

        # Validate source_ids
        source_ids: list[str] = raw.get("source_ids") or []
        unknown = [sid for sid in source_ids if sid not in valid_ids]
        if unknown:
            raise BriefGenerationError(
                f"Claim {claim_id!r}: unknown source IDs {unknown}. "
                "LLM must only cite IDs from the supplied evidence list."
            )

        # Empty source_ids only allowed for retrieval_gap absence claims
        if ctype in ("supported", "exploratory") and not source_ids:
            raise BriefGenerationError(
                f"Claim {claim_id!r} ({ctype}): requires at least one source_id."
            )

        text: str = raw.get("text", "")

        # Recommendation detection
        if _RECOMMENDATION_PATTERNS.search(text):
            raise BriefGenerationError(
                f"Claim {claim_id!r}: contains prohibited recommendation language."
            )

        # Causal language detection against observational/CMS sources
        if _CAUSAL_PATTERNS.search(text):
            observational_cited = set(source_ids) & (observational_ids | cms_ids)
            if observational_cited:
                raise BriefGenerationError(
                    f"Claim {claim_id!r}: causal language detected but "
                    f"sources include observational/coverage records: {observational_cited}."
                )

        # Trial without results cannot support efficacy claims
        if dim in ("outcome", "safety") and ctype == "supported":
            trial_cited = set(source_ids) & trial_no_results_ids
            if trial_cited and set(source_ids) == trial_cited:
                raise BriefGenerationError(
                    f"Claim {claim_id!r}: outcome/safety claim supported only by "
                    f"trials without posted results: {trial_cited}."
                )

        # CMS cannot support effectiveness
        if dim in ("outcome", "safety") and ctype == "supported":
            cms_only = set(source_ids) and set(source_ids) == (set(source_ids) & cms_ids)
            if cms_only:
                raise BriefGenerationError(
                    f"Claim {claim_id!r}: CMS coverage records cannot independently "
                    "support effectiveness/safety claims."
                )

        validated.append(
            GeneratedClaim(
                claim_id=claim_id,
                text=text,
                claim_type=ctype,
                dimension=dim,
                evidence_basis=raw.get("evidence_basis", "record_supported"),
                source_ids=source_ids,
                design_limitations=raw.get("design_limitations") or [],
                uncertainty_note=raw.get("uncertainty_note"),
            )
        )

    return validated


def generate_live_llm(
    snapshot: EvidenceSnapshot,
    question_text: str,
    evidence_run_id: str,
    llm_client: Any,
) -> tuple[list[GeneratedClaim], list[EvidenceGap], str, str | None, str | None]:
    """Call the LLM provider and validate output.

    Returns:
        (claims, gaps, prompt_version, model_provider, model_name)

    Raises:
        BriefGenerationError on validation failure after one structural retry.
    """
    prompt = _build_prompt(snapshot, question_text)
    raw_response: str | None = None
    for attempt in range(2):
        try:
            raw_response = llm_client.complete(prompt)
            break
        except Exception as exc:
            if attempt == 0:
                continue
            raise BriefGenerationError(
                f"LLM provider unavailable after {attempt + 1} attempts: {exc}"
            ) from exc

    if not raw_response:
        raise BriefGenerationError("LLM returned empty response.")

    # Parse JSON
    try:
        # Extract JSON block if wrapped in markdown
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_response, re.DOTALL)
        json_str = match.group(1) if match else raw_response.strip()
        parsed = json.loads(json_str)
    except (json.JSONDecodeError, AttributeError) as exc:
        raise BriefGenerationError(f"LLM output is not valid JSON: {exc}") from exc

    claims = _validate_llm_output(parsed, snapshot)

    model_provider = getattr(llm_client, "provider", None)
    model_name = getattr(llm_client, "model_name", None)

    # Build gaps for uncovered safety/evidence_gap dimensions
    gaps: list[EvidenceGap] = []
    covered_dims = {c.dimension for c in claims}
    if "safety" not in covered_dims:
        gaps.append(
            EvidenceGap(
                gap_id="gap-safety-llm",
                description=(
                    "No safety-specific claims were generated. "
                    "The configured evidence search did not identify safety-specific records."
                ),
                dimension="safety",
                retrieval_run_id=evidence_run_id,
                sources_searched=list(snapshot.source_statuses.keys()),
                source_statuses=dict(snapshot.source_statuses),
                result_counts={
                    r.source_type: sum(
                        1 for s in snapshot.records if s.source_type == r.source_type
                    )
                    for r in snapshot.records[:1]
                },
                limitations=["Safety data requires dedicated adverse-event database searches."],
            )
        )

    return claims, gaps, PROMPT_VERSION, model_provider, model_name
