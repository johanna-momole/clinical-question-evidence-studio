"""Evidence normalizer: converts RawEvidenceRecord payloads into typed EvidenceRecord subclasses.

Rules:
- Preserve the raw content hash — never re-hash or alter it.
- Capture partial dates accurately using date_precision; default missing date to None.
- Never invent values for missing fields — leave them as None.
- Distinguish None (not reported) from structurally not-applicable via not_applicable_fields.
- is_fixture_data is always propagated from the raw record.
"""

from __future__ import annotations

from datetime import date

from src.schemas.evidence import (
    ClinicalTrialRecord,
    CoverageRecord,
    DatePrecision,
    EvidenceRecord,
    PublicationRecord,
    RawEvidenceRecord,
)


def normalize_records(
    raw_records: list[RawEvidenceRecord],
    run_id: str,
) -> list[EvidenceRecord]:
    """Normalize a batch of raw records into typed EvidenceRecord instances."""
    normalized: list[EvidenceRecord] = []
    for raw in raw_records:
        record = _dispatch(raw, run_id)
        if record is not None:
            normalized.append(record)
    return normalized


def _dispatch(raw: RawEvidenceRecord, run_id: str) -> EvidenceRecord | None:
    if raw.source_name == "pubmed":
        return _normalize_pubmed(raw, run_id)
    if raw.source_name == "clinical_trials_gov":
        return _normalize_clinical_trial(raw, run_id)
    if raw.source_name == "cms_coverage":
        return _normalize_cms_coverage(raw, run_id)
    return None


# ---------------------------------------------------------------------------
# PubMed normalizer
# ---------------------------------------------------------------------------


def _normalize_pubmed(raw: RawEvidenceRecord, run_id: str) -> PublicationRecord:
    p = raw.raw_payload
    pmid = str(p.get("pmid", raw.source_identifier))
    pub_date, precision = _parse_pubmed_date(p.get("pub_date"))
    authors: list[str] = p.get("authors") or []
    mesh_terms: list[str] = p.get("mesh_terms") or []
    publication_types: list[str] = p.get("publication_types") or []
    study_design = _infer_study_design_from_types(publication_types)
    return PublicationRecord(  # type: ignore[call-arg]
        id=f"ev-pubmed-{pmid}-{raw.content_hash}",
        source_type="publication",
        source_name="pubmed",
        title=str(p.get("title", "")),
        identifier=pmid,
        url=p.get("url"),
        authors_or_sponsor=authors,
        publication_or_update_date=pub_date,
        date_precision=precision,
        study_design=study_design,
        publication_types=publication_types,
        language=p.get("language"),
        journal=p.get("journal"),
        doi=p.get("doi"),
        abstract=p.get("abstract"),
        pmid=pmid,
        mesh_terms=mesh_terms,
        retrieval_run_id=run_id,
        raw_record_id=raw.id,
        content_hash=raw.content_hash,
        is_fixture_data=raw.is_fixture_data,
        not_applicable_fields=[
            "enrollment",
            "nct_id",
            "trial_status",
            "phase",
            "lcd_or_ncd_id",
            "jurisdiction",
            "coverage_determination",
        ],
    )


def _parse_pubmed_date(pub_date: object) -> tuple[date | None, DatePrecision]:
    if not pub_date or not isinstance(pub_date, dict):
        return None, "unknown"
    year = pub_date.get("year")
    month = pub_date.get("month")
    day = pub_date.get("day")
    if year and month and day:
        try:
            return date(int(year), int(month), int(day)), "day"
        except ValueError:
            pass
    if year and month:
        try:
            return date(int(year), int(month), 1), "month"
        except ValueError:
            pass
    if year:
        try:
            return date(int(year), 1, 1), "year"
        except ValueError:
            pass
    return None, "unknown"


def _infer_study_design_from_types(pub_types: list[str]) -> str | None:
    """Map PubMed publication type labels to a study-design string.

    This is rule-based mapping, not inference — only established type labels are mapped.
    Unknown types are left unmapped (returns None).
    """
    pt_lower = {t.lower() for t in pub_types}
    if "meta-analysis" in pt_lower:
        return "Meta-analysis"
    if "systematic review" in pt_lower:
        return "Systematic review"
    if "randomized controlled trial" in pt_lower:
        return "RCT"
    if "observational study" in pt_lower:
        return "Observational cohort"
    if "review" in pt_lower:
        return "Review"
    return None


# ---------------------------------------------------------------------------
# ClinicalTrials.gov normalizer
# ---------------------------------------------------------------------------


def _normalize_clinical_trial(raw: RawEvidenceRecord, run_id: str) -> ClinicalTrialRecord:
    p = raw.raw_payload
    proto = p.get("protocolSection", p)
    id_mod = proto.get("identificationModule", {})
    status_mod = proto.get("statusModule", {})
    design_mod = proto.get("designModule", {})
    cond_mod = proto.get("conditionsModule", {})
    int_mod = proto.get("interventionsModule", {})
    sponsor_mod = proto.get("sponsorCollaboratorsModule", {})

    nct_id = id_mod.get("nctId") or p.get("nct_id", raw.source_identifier)
    title = id_mod.get("officialTitle") or id_mod.get("briefTitle", "")
    overall_status = status_mod.get("overallStatus") or p.get("status")
    has_results = bool(status_mod.get("hasResultsSection", False))
    phases: list[str] = design_mod.get("phases") or []
    phase = phases[0] if phases else None
    enrollment_info = design_mod.get("enrollmentInfo", {})
    enrollment = enrollment_info.get("count")
    study_type = design_mod.get("studyType")
    conditions: list[str] = cond_mod.get("conditions") or []
    interventions_raw: list[dict] = int_mod.get("interventions") or []
    intervention_names = [i.get("name", "") for i in interventions_raw if i.get("name")]
    sponsor = sponsor_mod.get("leadSponsor", {}).get("name")
    primary_completion_str = (
        status_mod.get("primaryCompletionDate", {}).get("date")
        if isinstance(status_mod.get("primaryCompletionDate"), dict)
        else status_mod.get("primaryCompletionDate")
    )
    primary_completion_date = _parse_date_str(primary_completion_str)
    design_info = design_mod.get("designInfo", {})
    design_label = _infer_trial_design(design_info, study_type)

    return ClinicalTrialRecord(  # type: ignore[call-arg]
        id=f"ev-ct-{nct_id}-{raw.content_hash}",
        source_type="clinical_trial",
        source_name="clinical_trials_gov",
        title=title,
        identifier=nct_id,
        url=f"https://clinicaltrials.gov/study/{nct_id}",
        status=overall_status,
        study_design=design_label,
        population="; ".join(conditions) if conditions else None,
        intervention="; ".join(intervention_names) if intervention_names else None,
        nct_id=nct_id,
        phase=phase,
        enrollment=enrollment,
        trial_status=overall_status,
        primary_completion_date=primary_completion_date,
        sponsor=sponsor,
        conditions=conditions,
        interventions=intervention_names,
        has_results_posted=has_results,
        study_type=study_type,
        evidence_limitations=[]
        if has_results
        else ["Results have not been posted to ClinicalTrials.gov as of the fixture date."],
        retrieval_run_id=run_id,
        raw_record_id=raw.id,
        content_hash=raw.content_hash,
        is_fixture_data=raw.is_fixture_data,
        not_applicable_fields=[
            "pmid",
            "abstract",
            "journal",
            "doi",
            "mesh_terms",
            "lcd_or_ncd_id",
            "jurisdiction",
            "coverage_determination",
        ],
    )


def _infer_trial_design(design_info: dict, study_type: str | None) -> str | None:
    if study_type == "Observational":
        model = design_info.get("observationalModel", "")
        perspective = design_info.get("timePerspective", "")
        return f"Observational {perspective} {model}".strip() or "Observational"
    if study_type == "Interventional":
        allocation = design_info.get("allocation", "")
        masking = design_info.get("maskingInfo", {}).get("masking", "")
        if allocation == "Randomized" and "Double" in masking:
            return "Randomized, double-blind"
        if allocation == "Randomized":
            return "Randomized"
        return "Interventional"
    return None


def _parse_date_str(date_str: str | None) -> date | None:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            import datetime as dt_module

            return dt_module.datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# CMS Coverage normalizer
# ---------------------------------------------------------------------------


def _normalize_cms_coverage(raw: RawEvidenceRecord, run_id: str) -> CoverageRecord:
    p = raw.raw_payload
    doc_id = p.get("id") or p.get("lcd_id") or p.get("ncd_id") or raw.source_identifier
    doc_type_str = p.get("document_type", "")
    doc_type = doc_type_str if doc_type_str in ("LCD", "NCD") else None
    codes: list[str] = p.get("applicable_codes") or []
    effective_date = _parse_date_str(p.get("effective_date"))
    retirement_date = _parse_date_str(p.get("retirement_date"))

    return CoverageRecord(  # type: ignore[call-arg]
        id=f"ev-cms-{doc_id}-{raw.content_hash}",
        source_type="cms_coverage",
        source_name="cms_coverage",
        title=str(p.get("title", "")),
        identifier=str(doc_id),
        url=p.get("url"),
        status=p.get("status"),
        lcd_or_ncd_id=str(doc_id),
        document_type=doc_type,
        jurisdiction=p.get("jurisdiction"),
        effective_date=effective_date,
        retirement_date=retirement_date,
        contractor=p.get("contractor"),
        coverage_determination=p.get("coverage_determination"),
        applicable_codes=codes,
        retrieval_run_id=run_id,
        raw_record_id=raw.id,
        content_hash=raw.content_hash,
        is_fixture_data=raw.is_fixture_data,
        not_applicable_fields=[
            "pmid",
            "abstract",
            "journal",
            "doi",
            "mesh_terms",
            "nct_id",
            "phase",
            "enrollment",
            "trial_status",
        ],
    )
