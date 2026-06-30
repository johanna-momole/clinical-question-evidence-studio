"""Pure functions for grouping and filtering TerminologyMapping collections.

All functions are stateless and operate on lists — testable without any I/O.
"""

from src.schemas.phenotype import TerminologyMapping


def group_by_concept(
    mappings: list[TerminologyMapping],
) -> dict[str, list[TerminologyMapping]]:
    """Group mappings by concept_id. Preserves original ordering within each group."""
    result: dict[str, list[TerminologyMapping]] = {}
    for m in mappings:
        result.setdefault(m.concept_id, []).append(m)
    return result


def group_by_system(
    mappings: list[TerminologyMapping],
) -> dict[str, list[TerminologyMapping]]:
    """Group mappings by terminology_system (e.g., 'ICD-10-CM', 'RxNorm', 'LOINC')."""
    result: dict[str, list[TerminologyMapping]] = {}
    for m in mappings:
        result.setdefault(m.terminology_system, []).append(m)
    return result


def filter_by_system(mappings: list[TerminologyMapping], system: str) -> list[TerminologyMapping]:
    """Return only mappings from the specified terminology system."""
    return [m for m in mappings if m.terminology_system == system]


def filter_by_review_status(
    mappings: list[TerminologyMapping], status: str
) -> list[TerminologyMapping]:
    """Return only mappings with the given review_status ('candidate'|'approved'|'rejected')."""
    return [m for m in mappings if m.review_status == status]


def filter_unverified(mappings: list[TerminologyMapping]) -> list[TerminologyMapping]:
    """Return mappings where verification_date is None (not yet checked against authoritative source)."""
    return [m for m in mappings if m.verification_date is None]


def filter_llm_suggested(
    mappings: list[TerminologyMapping],
) -> list[TerminologyMapping]:
    """Return only mappings that were produced by an LLM and require human review."""
    return [m for m in mappings if m.is_llm_suggested]


def candidate_count(mappings: list[TerminologyMapping]) -> int:
    return sum(1 for m in mappings if m.review_status == "candidate")


def approved_count(mappings: list[TerminologyMapping]) -> int:
    return sum(1 for m in mappings if m.review_status == "approved")


def review_completeness_pct(mappings: list[TerminologyMapping]) -> float:
    """Percentage of mappings that have been reviewed (approved or rejected)."""
    if not mappings:
        return 0.0
    reviewed = sum(1 for m in mappings if m.review_status in {"approved", "rejected"})
    return round(reviewed / len(mappings) * 100, 1)
