"""FHIR R4 resource parsers: extract structured data from raw resource dicts.

Each parser returns a typed normalized model or raises ValueError for unrecoverable data.
Parsers do NOT perform cross-resource validation (e.g., orphaned reference checks) —
that belongs in the QA layer.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from src.schemas.fhir import (
    NormalizedCondition,
    NormalizedEncounter,
    NormalizedMedication,
    NormalizedObservation,
    NormalizedPatient,
    NormalizedProcedure,
    ReferenceRange,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GENDER_MAP: dict[str, Literal["male", "female", "other", "unknown"]] = {
    "male": "male",
    "female": "female",
    "other": "other",
    "unknown": "unknown",
}


def _parse_date(value: str | None) -> date | None:
    """Parse an ISO date or datetime string; return None for missing/invalid values."""
    if not value:
        return None
    try:
        # Accept both date (YYYY-MM-DD) and datetime (YYYY-MM-DDT...) strings
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _first_coding(code_obj: dict) -> tuple[str, str, str]:
    """Extract (code, system, display) from a FHIR CodeableConcept."""
    codings = code_obj.get("coding", [])
    if codings:
        first = codings[0]
        return (
            first.get("code", ""),
            first.get("system", ""),
            first.get("display", ""),
        )
    # Fallback to text
    return ("", "", code_obj.get("text", ""))


def _subject_id(resource: dict) -> str | None:
    """Extract patient ID from resource.subject.reference (e.g., 'Patient/abc' → 'abc')."""
    subject = resource.get("subject", {})
    ref = subject.get("reference", "") if isinstance(subject, dict) else ""
    if ref.startswith("Patient/"):
        return ref[len("Patient/") :]
    return None


# ---------------------------------------------------------------------------
# Resource parsers
# ---------------------------------------------------------------------------


def parse_patient(resource: dict) -> NormalizedPatient:
    pid = resource.get("id", "")
    birth_date = _parse_date(resource.get("birthDate"))
    gender_raw = resource.get("gender", "unknown")
    sex = _GENDER_MAP.get(gender_raw, "unknown")

    deceased = False
    deceased_date: date | None = None
    if resource.get("deceasedBoolean"):
        deceased = True
    elif resource.get("deceasedDateTime"):
        deceased = True
        deceased_date = _parse_date(resource.get("deceasedDateTime"))

    # US Core race/ethnicity extensions
    race: str | None = None
    ethnicity: str | None = None
    for ext in resource.get("extension", []):
        url = ext.get("url", "")
        if "us-core-race" in url:
            for sub in ext.get("extension", []):
                if sub.get("url") == "text":
                    race = sub.get("valueString")
        elif "us-core-ethnicity" in url:
            for sub in ext.get("extension", []):
                if sub.get("url") == "text":
                    ethnicity = sub.get("valueString")

    return NormalizedPatient(
        patient_id=pid,
        birth_date=birth_date,
        sex=sex,
        race=race,
        ethnicity=ethnicity,
        deceased=deceased,
        deceased_date=deceased_date,
        source_resource_id=pid,
    )


def parse_condition(resource: dict) -> NormalizedCondition | None:
    """Return a NormalizedCondition or None if the patient reference cannot be resolved."""
    pid = _subject_id(resource)
    if not pid:
        return None

    cid = resource.get("id", "")
    code_obj = resource.get("code", {})
    code, system, display = _first_coding(code_obj)

    onset = _parse_date(
        resource.get("onsetDateTime") or resource.get("onsetPeriod", {}).get("start")
    )
    recorded = _parse_date(resource.get("recordedDate"))

    clinical_status: str | None = None
    cs_obj = resource.get("clinicalStatus", {})
    if isinstance(cs_obj, dict):
        cs_codings = cs_obj.get("coding", [])
        if cs_codings:
            clinical_status = cs_codings[0].get("code")

    ver_status: str | None = None
    vs_obj = resource.get("verificationStatus", {})
    if isinstance(vs_obj, dict):
        vs_codings = vs_obj.get("coding", [])
        if vs_codings:
            ver_status = vs_codings[0].get("code")

    return NormalizedCondition(
        patient_id=pid,
        condition_id=cid,
        code=code,
        code_system=system,
        display=display or None,
        onset_date=onset,
        recorded_date=recorded,
        clinical_status=clinical_status,
        verification_status=ver_status,
        source_resource_id=cid,
    )


def parse_encounter(resource: dict) -> NormalizedEncounter | None:
    pid = _subject_id(resource)
    if not pid:
        return None

    eid = resource.get("id", "")
    period = resource.get("period", {})
    start = _parse_date(period.get("start"))
    end = _parse_date(period.get("end"))
    status = resource.get("status")

    class_obj = resource.get("class", {})
    if isinstance(class_obj, dict):
        enc_class = class_obj.get("code")
    else:
        enc_class = None

    return NormalizedEncounter(
        patient_id=pid,
        encounter_id=eid,
        encounter_class=enc_class,
        start_date=start,
        end_date=end,
        status=status,
        source_resource_id=eid,
    )


def parse_observation(resource: dict) -> NormalizedObservation | None:
    pid = _subject_id(resource)
    if not pid:
        return None

    oid = resource.get("id", "")
    code_obj = resource.get("code", {})
    code, system, display = _first_coding(code_obj)

    value_numeric: float | None = None
    value_text: str | None = None
    unit: str | None = None

    vq = resource.get("valueQuantity")
    if isinstance(vq, dict):
        raw_val = vq.get("value")
        value_numeric = float(raw_val) if raw_val is not None else None
        unit = vq.get("unit") or vq.get("code")
    else:
        # valueString or valueCodeableConcept
        vs = resource.get("valueString")
        if vs:
            value_text = str(vs)
        elif resource.get("valueCodeableConcept"):
            _, _, value_text = _first_coding(resource["valueCodeableConcept"])

    effective = _parse_date(
        resource.get("effectiveDateTime") or resource.get("effectivePeriod", {}).get("start")
    )
    status = resource.get("status")

    # Reference range (first entry only)
    ref_range: ReferenceRange | None = None
    rr_list = resource.get("referenceRange", [])
    if rr_list and isinstance(rr_list, list):
        rr0 = rr_list[0]
        low_val = rr0.get("low", {}).get("value")
        high_val = rr0.get("high", {}).get("value")
        rr_unit = (rr0.get("low") or rr0.get("high") or {}).get("unit")
        ref_range = ReferenceRange(
            low=float(low_val) if low_val is not None else None,
            high=float(high_val) if high_val is not None else None,
            unit=rr_unit,
        )

    return NormalizedObservation(
        patient_id=pid,
        observation_id=oid,
        code=code,
        code_system=system,
        display=display or None,
        value_numeric=value_numeric,
        value_text=value_text,
        unit=unit,
        effective_date=effective,
        status=status,
        reference_range=ref_range,
        source_resource_id=oid,
    )


def parse_medication_request(resource: dict) -> NormalizedMedication | None:
    pid = _subject_id(resource)
    if not pid:
        return None

    mid = resource.get("id", "")
    med_obj = resource.get("medicationCodeableConcept", {})
    code, system, display = _first_coding(med_obj)

    start = _parse_date(
        resource.get("authoredOn")
        or resource.get("dispenseRequest", {}).get("validityPeriod", {}).get("start")
    )
    end: date | None = None
    status = resource.get("status")

    return NormalizedMedication(
        patient_id=pid,
        medication_record_id=mid,
        code=code,
        code_system=system,
        display=display or None,
        start_date=start,
        end_date=end,
        status=status,
        source_resource_type="MedicationRequest",
        source_resource_id=mid,
    )


def parse_medication_statement(resource: dict) -> NormalizedMedication | None:
    pid = _subject_id(resource)
    if not pid:
        return None

    mid = resource.get("id", "")
    med_obj = resource.get("medicationCodeableConcept", {})
    code, system, display = _first_coding(med_obj)

    period = resource.get("effectivePeriod", {})
    start = _parse_date(resource.get("effectiveDateTime") or period.get("start"))
    end = _parse_date(period.get("end"))
    status = resource.get("status")

    return NormalizedMedication(
        patient_id=pid,
        medication_record_id=mid,
        code=code,
        code_system=system,
        display=display or None,
        start_date=start,
        end_date=end,
        status=status,
        source_resource_type="MedicationStatement",
        source_resource_id=mid,
    )


def parse_procedure(resource: dict) -> NormalizedProcedure | None:
    pid = _subject_id(resource)
    if not pid:
        return None

    proc_id = resource.get("id", "")
    code_obj = resource.get("code", {})
    code, system, display = _first_coding(code_obj)

    performed = _parse_date(
        resource.get("performedDateTime") or resource.get("performedPeriod", {}).get("start")
    )
    status = resource.get("status")

    return NormalizedProcedure(
        patient_id=pid,
        procedure_id=proc_id,
        code=code,
        code_system=system,
        display=display or None,
        performed_date=performed,
        status=status,
        source_resource_id=proc_id,
    )
