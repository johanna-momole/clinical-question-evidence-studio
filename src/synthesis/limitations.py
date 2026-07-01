"""Deterministic limitations generator for evidence briefs.

Limitations are derived solely from structured metadata — never from LLM output.
"""

from __future__ import annotations

from src.schemas.brief import EvidenceSnapshot
from src.schemas.retrieval import EvidenceSourceStatus


def generate_limitations(
    snapshot: EvidenceSnapshot,
    source_statuses: list[EvidenceSourceStatus] | None = None,
    cohort_is_synthetic: bool = True,
    has_candidate_terminology: bool = True,
) -> list[str]:
    """Return a deterministic list of limitation statements for this brief."""
    lims: list[str] = []

    # Cohort data limitation
    if cohort_is_synthetic:
        lims.append(
            "The patient cohort used in this study is entirely synthetic "
            "(generated from fictional data). Results do not reflect real-world epidemiology."
        )

    # Offline fixture limitation
    has_fixture = any(r.is_fixture_data for r in snapshot.records)
    has_live = any(not r.is_fixture_data for r in snapshot.records)
    if has_fixture and not has_live:
        lims.append(
            "Evidence records were served from versioned offline fixtures "
            "rather than live API calls. "
            "Fixture content may not reflect the most recent publications or policy updates."
        )
    elif has_fixture and has_live:
        lims.append(
            "Evidence records include a mix of offline fixture content and live API records. "
            "See record-level provenance for data origin details."
        )

    # Source failures and partial retrieval
    if source_statuses:
        for ss in source_statuses:
            for err in ss.errors:
                if err.is_fatal_for_source:
                    lims.append(
                        f"Source '{ss.source_name}' encountered a fatal error during retrieval "
                        f"and contributed zero records. Findings may be incomplete."
                    )
                else:
                    lims.append(
                        f"Source '{ss.source_name}' reported a non-fatal retrieval error: "
                        f"{err.message}"
                    )

    # Trials without results
    trial_no_results = [
        r
        for r in snapshot.records
        if r.source_type == "clinical_trial"
        and any("results not yet posted" in w.lower() for w in r.warnings)
    ]
    if trial_no_results:
        lims.append(
            f"{len(trial_no_results)} registered trial(s) have not yet posted results to "
            "ClinicalTrials.gov. These records describe study design and eligibility only, "
            "not outcomes."
        )

    # Local CMS jurisdiction
    local_cms = [
        r
        for r in snapshot.records
        if r.source_type == "cms_coverage"
        and any("local coverage determination" in w.lower() for w in r.warnings)
    ]
    if local_cms:
        lims.append(
            f"{len(local_cms)} CMS Local Coverage Determination(s) (LCDs) are included. "
            "LCDs apply to specific Medicare jurisdictions and are not nationally applicable."
        )

    # Candidate terminology mapping warning
    if has_candidate_terminology:
        lims.append(
            "Some phenotype concept mappings are candidate RxNorm codes that have not been "
            "independently verified against the live RxNorm API. "
            "SGLT2 inhibitor coverage in the search may be incomplete."
        )

    # Search scope
    lims.append(
        "Evidence search was limited to PubMed, ClinicalTrials.gov, and CMS Coverage. "
        "Other relevant sources (Cochrane, EMBASE, grey literature) were not searched."
    )

    # Language filter
    lims.append(
        "This search did not apply explicit language filters. "
        "Non-English records may be present in the fixture set."
    )

    return lims
