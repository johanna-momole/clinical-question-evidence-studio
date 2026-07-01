"""Deterministic, non-LLM evidence metatagging.

Tags are assigned by explicit rule matching against:
  - publication_types, mesh_terms (PubMed)
  - conditions, interventions, study_type (ClinicalTrials.gov)
  - applicable_codes, coverage_determination (CMS Coverage)
  - common cross-source fields: title, study_design

Rules are identified by rule_id strings; the same (record, rule_set) always produces
the same tags — there is no randomness, no LLM, and no network access in this module.

Tag dimensions:
  - population    : patient population (e.g., 'population:ckd', 'population:t2dm')
  - intervention  : drug/class (e.g., 'intervention:sglt2', 'intervention:canagliflozin')
  - comparator    : comparator class ('comparator:glp1')
  - design        : study design ('design:rct', 'design:meta_analysis', etc.)
  - outcome       : outcome domain ('outcome:renal', 'outcome:cardiovascular', 'outcome:mortality')
  - source        : source type ('source:publication', 'source:clinical_trial', 'source:cms_coverage')
  - temporal      : recency flag ('temporal:recent_5yr', 'temporal:older')
"""

from __future__ import annotations

from datetime import date

from src.schemas.evidence import EvidenceRecord, EvidenceTag

_SGLT2_TERMS = {
    "empagliflozin",
    "dapagliflozin",
    "canagliflozin",
    "ertugliflozin",
    "sglt2",
    "sglt-2",
    "sodium-glucose cotransporter",
    "sodium glucose cotransporter",
}
_CKD_TERMS = {
    "chronic kidney disease",
    "ckd",
    "diabetic nephropathy",
    "diabetic nephropathies",
    "renal insufficiency",
    "nephropathy",
    "glomerular filtration",
}
_T2DM_TERMS = {
    "type 2 diabetes",
    "type 2 diabetes mellitus",
    "t2dm",
    "t2d",
}
_HF_TERMS = {"heart failure", "cardiac failure"}
_CV_TERMS = {
    "cardiovascular",
    "myocardial infarction",
    "stroke",
    "mace",
    "major adverse cardiovascular events",
    "cardiac",
}
_RENAL_OUTCOME_TERMS = {
    "kidney failure",
    "end-stage kidney disease",
    "eskd",
    "esrd",
    "dialysis",
    "creatinine doubling",
    "egfr",
    "renal outcomes",
    "kidney outcomes",
    "nephropathy progression",
    "albuminuria",
}
_MORTALITY_TERMS = {"mortality", "death", "all-cause death"}
_GLP1_TERMS = {"glp-1", "glp1", "semaglutide", "liraglutide", "glucagon-like peptide"}
_METFORMIN_TERMS = {"metformin", "biguanide"}
_REFERENCE_DATE = date(2020, 1, 1)  # records on/after this are 'recent'


def tag_records(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    """Apply deterministic tags to each record in-place and return the same list."""
    for rec in records:
        tags, structured = _tag_record(rec)
        rec.tags = tags
        rec.structured_tags = structured
    return records


def _tag_record(rec: EvidenceRecord) -> tuple[list[str], list[EvidenceTag]]:
    structured: list[EvidenceTag] = []

    # Source dimension
    structured.append(
        EvidenceTag(tag=f"source:{rec.source_type}", dimension="source", rule_id="tag-src-001")
    )

    # Combined searchable text
    text_blob = _text_blob(rec)

    # Population tags
    if _any_in(text_blob, _CKD_TERMS):
        structured.append(
            EvidenceTag(tag="population:ckd", dimension="population", rule_id="tag-pop-001")
        )
    if _any_in(text_blob, _T2DM_TERMS):
        structured.append(
            EvidenceTag(tag="population:t2dm", dimension="population", rule_id="tag-pop-002")
        )
    if _any_in(text_blob, _HF_TERMS):
        structured.append(
            EvidenceTag(
                tag="population:heart_failure", dimension="population", rule_id="tag-pop-003"
            )
        )

    # Intervention tags
    if _any_in(text_blob, _SGLT2_TERMS):
        structured.append(
            EvidenceTag(
                tag="intervention:sglt2_class", dimension="intervention", rule_id="tag-int-001"
            )
        )
    for drug, rule_id in [
        ("empagliflozin", "tag-int-002"),
        ("dapagliflozin", "tag-int-003"),
        ("canagliflozin", "tag-int-004"),
        ("ertugliflozin", "tag-int-005"),
    ]:
        if drug in text_blob:
            structured.append(
                EvidenceTag(tag=f"intervention:{drug}", dimension="intervention", rule_id=rule_id)
            )
    if _any_in(text_blob, _GLP1_TERMS):
        structured.append(
            EvidenceTag(tag="comparator:glp1_class", dimension="comparator", rule_id="tag-cmp-001")
        )
    if _any_in(text_blob, _METFORMIN_TERMS):
        structured.append(
            EvidenceTag(tag="comparator:metformin", dimension="comparator", rule_id="tag-cmp-002")
        )

    # Design tags
    design_lower = (rec.study_design or "").lower()
    if "meta" in design_lower:
        structured.append(
            EvidenceTag(tag="design:meta_analysis", dimension="design", rule_id="tag-des-001")
        )
    elif "systematic" in design_lower:
        structured.append(
            EvidenceTag(tag="design:systematic_review", dimension="design", rule_id="tag-des-002")
        )
    elif "rct" in design_lower or "randomized" in design_lower or "randomised" in design_lower:
        structured.append(EvidenceTag(tag="design:rct", dimension="design", rule_id="tag-des-003"))
    elif "observational" in design_lower or "cohort" in design_lower:
        structured.append(
            EvidenceTag(tag="design:observational", dimension="design", rule_id="tag-des-004")
        )
    elif "review" in design_lower:
        structured.append(
            EvidenceTag(tag="design:review", dimension="design", rule_id="tag-des-005")
        )
    # Also check pub types (PubMed)
    from src.schemas.evidence import PublicationRecord

    if isinstance(rec, PublicationRecord):
        pt_lower = {t.lower() for t in rec.publication_types}
        if "meta-analysis" in pt_lower and not any(
            t.tag == "design:meta_analysis" for t in structured
        ):
            structured.append(
                EvidenceTag(tag="design:meta_analysis", dimension="design", rule_id="tag-des-006")
            )
        elif "randomized controlled trial" in pt_lower and not any(
            "design:rct" == t.tag for t in structured
        ):
            structured.append(
                EvidenceTag(tag="design:rct", dimension="design", rule_id="tag-des-007")
            )

    # Outcome tags
    if _any_in(text_blob, _RENAL_OUTCOME_TERMS):
        structured.append(
            EvidenceTag(tag="outcome:renal", dimension="outcome", rule_id="tag-out-001")
        )
    if _any_in(text_blob, _CV_TERMS):
        structured.append(
            EvidenceTag(tag="outcome:cardiovascular", dimension="outcome", rule_id="tag-out-002")
        )
    if _any_in(text_blob, _MORTALITY_TERMS):
        structured.append(
            EvidenceTag(tag="outcome:mortality", dimension="outcome", rule_id="tag-out-003")
        )

    # Temporal tag
    pub_date = rec.publication_or_update_date
    if pub_date and pub_date >= _REFERENCE_DATE:
        structured.append(
            EvidenceTag(tag="temporal:recent_5yr", dimension="temporal", rule_id="tag-tmp-001")
        )
    elif pub_date:
        structured.append(
            EvidenceTag(tag="temporal:older", dimension="temporal", rule_id="tag-tmp-002")
        )

    flat_tags = _dedup_tags([st.tag for st in structured])
    return flat_tags, _dedup_structured(structured)


def _text_blob(rec: EvidenceRecord) -> str:
    from src.schemas.evidence import ClinicalTrialRecord, CoverageRecord, PublicationRecord

    parts: list[str] = [
        (rec.title or ""),
        (rec.study_design or ""),
        (rec.population or ""),
        (rec.intervention or ""),
        (rec.comparator or ""),
        " ".join(rec.outcomes),
    ]
    if isinstance(rec, PublicationRecord):
        parts.extend(
            [
                rec.abstract or "",
                " ".join(rec.mesh_terms),
                " ".join(rec.publication_types),
            ]
        )
    elif isinstance(rec, ClinicalTrialRecord):
        parts.extend(
            [
                " ".join(rec.conditions),
                " ".join(rec.interventions),
            ]
        )
    elif isinstance(rec, CoverageRecord):
        parts.extend(
            [
                " ".join(rec.applicable_codes),
                rec.coverage_determination or "",
            ]
        )
    return " ".join(parts).lower()


def _any_in(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)


def _dedup_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


def _dedup_structured(tags: list[EvidenceTag]) -> list[EvidenceTag]:
    seen: set[str] = set()
    result: list[EvidenceTag] = []
    for t in tags:
        if t.tag not in seen:
            seen.add(t.tag)
            result.append(t)
    return result
