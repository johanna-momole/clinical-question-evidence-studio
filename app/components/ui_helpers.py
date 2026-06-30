"""Pure helper functions shared across Streamlit pages.

These functions contain no Streamlit imports so they can be unit-tested without
a running Streamlit session. They operate on domain objects and return plain values.
"""

import uuid
from datetime import UTC, datetime

from src.schemas.cohort import CohortAttrition, CohortRun
from src.schemas.phenotype import PhenotypeDefinition, TerminologyMapping
from src.schemas.qa import QASummary
from src.schemas.question import ClinicalQuestion

# Session state keys ― centralised to avoid typos across pages
SESSION_KEY_QUESTION = "approved_question"
SESSION_KEY_RUN_ID = "question_run_id"
SESSION_KEY_PHENOTYPE = "reviewed_phenotype"
SESSION_KEY_PHENOTYPE_AUDIT = "phenotype_audit_trail"


# ------------------------------------------------------------------
# Run ID helpers
# ------------------------------------------------------------------


def new_run_id() -> str:
    """Return a new stable run ID."""
    return str(uuid.uuid4())


# ------------------------------------------------------------------
# Question helpers
# ------------------------------------------------------------------


def validate_pico_completeness(pico_dict: dict) -> list[str]:
    """Return a list of validation errors for a PICO dict.

    Checks only fields that the spec requires to be non-empty.
    """
    errors: list[str] = []
    required_fields = {"population", "intervention"}
    for field in required_fields:
        val = pico_dict.get(field, "")
        if not val or not str(val).strip():
            errors.append(f"PICO field '{field}' must not be empty.")
        if val and str(val).startswith("[DEMO MODE]"):
            errors.append(
                f"PICO field '{field}' still contains a demo placeholder — "
                "please enter a real value before approving."
            )
    outcomes = pico_dict.get("outcomes", [])
    if not outcomes:
        errors.append("At least one outcome must be specified in PICO.")
    if outcomes and all(str(o).startswith("[DEMO MODE]") for o in outcomes):
        errors.append(
            "All outcomes still contain demo placeholders — "
            "please enter real outcomes before approving."
        )
    return errors


def question_to_json_bytes(question: ClinicalQuestion) -> bytes:
    """Serialise a ClinicalQuestion to UTF-8 JSON bytes for st.download_button."""
    return question.model_dump_json(indent=2).encode("utf-8")


def ambiguity_severity_order(severity: str) -> int:
    """Return sort key for ambiguity flags (high → first)."""
    return {"high": 0, "medium": 1, "low": 2}.get(severity, 3)


def format_ambiguity_label(severity: str) -> str:
    """Return a text badge for the given severity level."""
    return {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}.get(
        severity.lower(), severity.upper()
    )


# ------------------------------------------------------------------
# Phenotype helpers
# ------------------------------------------------------------------


def calculate_review_stats(phenotype: PhenotypeDefinition) -> dict:
    """Return review statistics for a phenotype's terminology mappings."""
    all_mappings: list[TerminologyMapping] = [m for c in phenotype.concepts for m in c.mappings]
    total = len(all_mappings)
    candidate = sum(1 for m in all_mappings if m.review_status == "candidate")
    approved = sum(1 for m in all_mappings if m.review_status == "approved")
    rejected = sum(1 for m in all_mappings if m.review_status == "rejected")
    llm_suggested = sum(1 for m in all_mappings if m.is_llm_suggested)
    unverified = sum(1 for m in all_mappings if m.verification_date is None)
    pct_reviewed = round((approved + rejected) / total * 100, 1) if total else 0.0
    return {
        "total": total,
        "candidate": candidate,
        "approved": approved,
        "rejected": rejected,
        "llm_suggested": llm_suggested,
        "unverified": unverified,
        "pct_reviewed": pct_reviewed,
    }


def phenotype_to_json_bytes(phenotype: PhenotypeDefinition) -> bytes:
    """Serialise a PhenotypeDefinition to UTF-8 JSON bytes for st.download_button."""
    return phenotype.model_dump_json(indent=2).encode("utf-8")


def concept_display_name(concept_id: str, phenotype: PhenotypeDefinition) -> str:
    """Return the concept name for a given concept_id, or the id if not found."""
    for c in phenotype.concepts:
        if c.concept_id == concept_id:
            return c.name
    return concept_id


def mapping_review_summary(mappings: list[TerminologyMapping]) -> str:
    """One-line summary of mapping review status for a concept."""
    total = len(mappings)
    approved = sum(1 for m in mappings if m.review_status == "approved")
    candidate = sum(1 for m in mappings if m.review_status == "candidate")
    if total == 0:
        return "No mappings"
    if approved == total:
        return f"All {total} approved"
    return f"{candidate}/{total} pending review"


# ------------------------------------------------------------------
# Timestamp helpers
# ------------------------------------------------------------------


def utcnow_iso() -> str:
    """Return current UTC datetime as ISO 8601 string."""
    return datetime.now(UTC).isoformat()


# ------------------------------------------------------------------
# Cohort helpers
# ------------------------------------------------------------------

SESSION_KEY_COHORT_RUN = "cohort_run"
SESSION_KEY_FHIR_QA = "fhir_qa_summary"
SESSION_KEY_COHORT_QA = "cohort_qa_summary"


def attrition_table_rows(attrition: CohortAttrition) -> list[dict]:
    """Convert CohortAttrition into display rows for st.dataframe."""
    return [
        {
            "Step": s.step_number,
            "Label": s.label,
            "Records In": s.records_in,
            "Excluded": s.records_excluded,
            "Records Out": s.records_out,
            "Exclusion Reason": s.exclusion_reason or "",
        }
        for s in attrition.steps
    ]


def qa_summary_rows(summary: QASummary) -> list[dict]:
    """Convert QASummary into display rows for st.dataframe."""
    return [
        {
            "ID": r.check_id,
            "Check": r.check_name,
            "Status": r.status.upper(),
            "Severity": r.severity,
            "Details": r.details or "",
        }
        for r in summary.results
    ]


def cohort_run_to_json_bytes(run: CohortRun) -> bytes:
    """Serialise a CohortRun to UTF-8 JSON bytes for st.download_button."""
    return run.model_dump_json(indent=2).encode("utf-8")


def format_attrition_pct(records_in: int, records_out: int) -> str:
    """Return '74.0% retained' string for attrition display."""
    if records_in == 0:
        return "N/A"
    pct = round(records_out / records_in * 100, 1)
    return f"{pct}% retained"


def qa_status_color(status: str) -> str:
    """Map a QA status to a Streamlit colour-compatible word."""
    return {
        "passed": "green",
        "warning": "orange",
        "failed": "red",
        "not_applicable": "gray",
    }.get(status.lower(), "gray")
