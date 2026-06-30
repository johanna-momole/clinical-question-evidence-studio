"""Generate deterministic synthetic FHIR R4 fixtures for the Clinical Q-E Studio demo.

All data generated here is ENTIRELY SYNTHETIC. No real patients, no real clinical records.
Generated for educational portfolio demonstration purposes only.

Usage:
    python scripts/generate_synthetic_fhir.py
    python scripts/generate_synthetic_fhir.py --dry-run   (prints counts only)

Output:
    data/fixtures/fhir/synthetic_cohort_v1/batch_01.json  ... batch_08.json
    data/fixtures/fhir/synthetic_cohort_v1/dataset_info.json
    tests/fixtures/fhir_edge_cases/*.json  (edge-case/QA test resources)
"""

import argparse
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# ---------------------------------------------------------------------------
# Constants — derived from phenotype fixture to ensure code alignment
# ---------------------------------------------------------------------------

_SEED = 42
_REFERENCE_DATE = date(2025, 6, 1)  # fixed reference date for all cohort logic
_BATCH_SIZE = 20  # patients per FHIR Bundle file

# ICD-10-CM T2DM codes (from phenotype concept c-t2dm)
_T2DM_CODES = [
    ("E11.9", "Type 2 diabetes mellitus without complications"),
    ("E11.65", "Type 2 diabetes mellitus with hyperglycemia"),
    ("E11.21", "Type 2 diabetes mellitus with diabetic nephropathy"),
]

# ICD-10-CM CKD inclusion codes (from phenotype concept c-ckd, stages 1-5)
_CKD_INCLUSION_CODES = [
    ("N18.1", "Chronic kidney disease, stage 1"),
    ("N18.2", "Chronic kidney disease, stage 2 (mild)"),
    ("N18.31", "Chronic kidney disease, stage 3a"),
    ("N18.32", "Chronic kidney disease, stage 3b"),
    ("N18.4", "Chronic kidney disease, stage 4 (severe)"),
    ("N18.5", "Chronic kidney disease, stage 5"),
    ("N18.9", "Chronic kidney disease, unspecified"),
]

# ICD-10-CM ESRD exclusion code (from phenotype concept c-esrd)
_ESRD_CODE = ("N18.6", "End stage renal disease")

# ICD-10-CM dialysis dependence code (from phenotype concept c-dialysis)
_DIALYSIS_CODE = ("Z99.2", "Dependence on renal dialysis")

# RxNorm SGLT2 inhibitor codes (from phenotype concept c-sglt2; all LLM-suggested/unverified)
_SGLT2_CODES = [
    ("1545653", "empagliflozin"),
    ("1488564", "dapagliflozin"),
    ("1373458", "canagliflozin"),
    ("2043678", "ertugliflozin"),
]

# LOINC eGFR codes (from phenotype concept c-egfr)
_EGFR_CODES = [
    ("62238-1", "Glomerular filtration rate [mL/min/1.73m2] CKD-EPI 2021"),
    ("33914-3", "Glomerular filtration rate [mL/min/1.73m2] MDRD"),
]

_LOINC_UACR = ("14959-1", "Microalbumin/Creatinine [Mass Ratio] in Urine")

_ICD10_SYSTEM = "http://hl7.org/fhir/sid/icd-10-cm"
_RXNORM_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"
_LOINC_SYSTEM = "http://loinc.org"

# ---------------------------------------------------------------------------
# Patient specification
# ---------------------------------------------------------------------------


def _age_to_birth(age_years: int, rng: random.Random) -> date:
    """Return a synthetic birth date for a patient of the given age at reference date."""
    base = _REFERENCE_DATE - timedelta(days=age_years * 365)
    return base - timedelta(days=rng.randint(0, 364))


def _past_date(base: date, years_ago: float, rng: random.Random, jitter_days: int = 60) -> date:
    d = base - timedelta(days=int(years_ago * 365))
    return d - timedelta(days=rng.randint(0, jitter_days))


# ---------------------------------------------------------------------------
# FHIR resource builders
# ---------------------------------------------------------------------------


def _patient(pid: str, birth_date: date, sex: str, deceased: bool = False) -> dict:
    resource: dict = {
        "resourceType": "Patient",
        "id": pid,
        "gender": sex,
        "birthDate": birth_date.isoformat(),
        "deceasedBoolean": deceased,
    }
    return resource


def _condition(
    cond_id: str,
    pid: str,
    code: str,
    display: str,
    onset: date,
    recorded: date,
    clinical_status: str = "active",
    verification: str = "confirmed",
) -> dict:
    return {
        "resourceType": "Condition",
        "id": cond_id,
        "subject": {"reference": f"Patient/{pid}"},
        "code": {
            "coding": [{"system": _ICD10_SYSTEM, "code": code, "display": display}],
            "text": display,
        },
        "onsetDateTime": onset.isoformat(),
        "recordedDate": recorded.isoformat(),
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": clinical_status,
                }
            ]
        },
        "verificationStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": verification,
                }
            ]
        },
    }


def _encounter(enc_id: str, pid: str, start: date, end: date, status: str = "finished") -> dict:
    return {
        "resourceType": "Encounter",
        "id": enc_id,
        "subject": {"reference": f"Patient/{pid}"},
        "status": status,
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "AMB",
            "display": "ambulatory",
        },
        "period": {"start": start.isoformat(), "end": end.isoformat()},
    }


def _observation(
    obs_id: str,
    pid: str,
    loinc_code: str,
    display: str,
    value: float,
    unit: str,
    effective: date,
    ref_low: float = 60.0,
    ref_high: float = 120.0,
) -> dict:
    return {
        "resourceType": "Observation",
        "id": obs_id,
        "subject": {"reference": f"Patient/{pid}"},
        "status": "final",
        "code": {
            "coding": [{"system": _LOINC_SYSTEM, "code": loinc_code, "display": display}],
            "text": display,
        },
        "valueQuantity": {"value": value, "unit": unit, "system": "http://unitsofmeasure.org"},
        "effectiveDateTime": effective.isoformat(),
        "referenceRange": [
            {
                "low": {"value": ref_low, "unit": unit},
                "high": {"value": ref_high, "unit": unit},
            }
        ],
    }


def _medication_request(med_id: str, pid: str, rxcui: str, display: str, authored: date) -> dict:
    return {
        "resourceType": "MedicationRequest",
        "id": med_id,
        "subject": {"reference": f"Patient/{pid}"},
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [{"system": _RXNORM_SYSTEM, "code": rxcui, "display": display}],
            "text": display,
        },
        "authoredOn": authored.isoformat(),
    }


# ---------------------------------------------------------------------------
# Patient category builders
# ---------------------------------------------------------------------------


def _build_t2dm_ckd_patient(idx: int, rng: random.Random, has_sglt2: bool = False) -> list[dict]:
    """T2DM + CKD adult — target cohort population."""
    pid = f"synth-pt-{idx:04d}"
    age = rng.randint(40, 85)
    sex = rng.choice(["male", "female"])
    birth = _age_to_birth(age, rng)

    dx_date = _past_date(_REFERENCE_DATE, rng.uniform(1.5, 5), rng, 90)
    t2dm_code, t2dm_display = rng.choice(_T2DM_CODES)
    ckd_code, ckd_display = rng.choice(_CKD_INCLUSION_CODES[:5])  # stage 1-4 for inclusion

    egfr_value = round(rng.uniform(15, 59), 1)  # CKD range
    egfr_date = _past_date(_REFERENCE_DATE, rng.uniform(0.1, 0.8), rng, 30)

    enc_start_1 = _past_date(_REFERENCE_DATE, 2, rng, 120)
    enc_start_2 = _past_date(_REFERENCE_DATE, 0.5, rng, 60)

    resources: list[dict] = [
        _patient(pid, birth, sex),
        _condition(f"synth-cond-{idx:04d}-t2dm", pid, t2dm_code, t2dm_display, dx_date, dx_date),
        _condition(f"synth-cond-{idx:04d}-ckd", pid, ckd_code, ckd_display, dx_date, dx_date),
        _encounter(f"synth-enc-{idx:04d}-01", pid, enc_start_1, enc_start_1 + timedelta(days=1)),
        _encounter(f"synth-enc-{idx:04d}-02", pid, enc_start_2, enc_start_2 + timedelta(days=1)),
        _observation(
            f"synth-obs-{idx:04d}-egfr",
            pid,
            *_EGFR_CODES[0],
            egfr_value,
            "mL/min/1.73m2",
            egfr_date,
        ),
    ]

    if has_sglt2:
        rxcui, rx_display = rng.choice(_SGLT2_CODES)
        med_date = _past_date(_REFERENCE_DATE, rng.uniform(0.05, 0.4), rng, 20)
        resources.append(
            _medication_request(f"synth-med-{idx:04d}-01", pid, rxcui, rx_display, med_date)
        )

    return resources


def _build_esrd_excluded_patient(idx: int, rng: random.Random) -> list[dict]:
    """T2DM + CKD adult with ESRD — excluded by exc-001."""
    pid = f"synth-pt-{idx:04d}"
    age = rng.randint(55, 85)
    sex = rng.choice(["male", "female"])
    birth = _age_to_birth(age, rng)
    dx_date = _past_date(_REFERENCE_DATE, rng.uniform(2, 6), rng, 90)
    t2dm_code, t2dm_display = _T2DM_CODES[0]

    enc_start = _past_date(_REFERENCE_DATE, 1, rng, 60)
    return [
        _patient(pid, birth, sex),
        _condition(f"synth-cond-{idx:04d}-t2dm", pid, t2dm_code, t2dm_display, dx_date, dx_date),
        _condition(
            f"synth-cond-{idx:04d}-esrd",
            pid,
            _ESRD_CODE[0],
            _ESRD_CODE[1],
            dx_date,
            dx_date,
        ),
        _encounter(f"synth-enc-{idx:04d}-01", pid, enc_start, enc_start + timedelta(days=1)),
    ]


def _build_dialysis_excluded_patient(idx: int, rng: random.Random) -> list[dict]:
    """T2DM + CKD adult on dialysis — excluded by exc-002."""
    pid = f"synth-pt-{idx:04d}"
    age = rng.randint(50, 80)
    sex = rng.choice(["male", "female"])
    birth = _age_to_birth(age, rng)
    dx_date = _past_date(_REFERENCE_DATE, rng.uniform(2, 6), rng, 90)
    t2dm_code, t2dm_display = _T2DM_CODES[0]
    ckd_code, ckd_display = _CKD_INCLUSION_CODES[4]  # stage 4

    enc_start = _past_date(_REFERENCE_DATE, 1, rng, 60)
    return [
        _patient(pid, birth, sex),
        _condition(f"synth-cond-{idx:04d}-t2dm", pid, t2dm_code, t2dm_display, dx_date, dx_date),
        _condition(f"synth-cond-{idx:04d}-ckd", pid, ckd_code, ckd_display, dx_date, dx_date),
        _condition(
            f"synth-cond-{idx:04d}-dialysis",
            pid,
            _DIALYSIS_CODE[0],
            _DIALYSIS_CODE[1],
            dx_date,
            dx_date,
        ),
        _encounter(f"synth-enc-{idx:04d}-01", pid, enc_start, enc_start + timedelta(days=1)),
    ]


def _build_t2dm_only_patient(idx: int, rng: random.Random) -> list[dict]:
    """T2DM without CKD — fails inc-002."""
    pid = f"synth-pt-{idx:04d}"
    age = rng.randint(35, 75)
    sex = rng.choice(["male", "female"])
    birth = _age_to_birth(age, rng)
    dx_date = _past_date(_REFERENCE_DATE, rng.uniform(1, 4), rng, 90)
    t2dm_code, t2dm_display = rng.choice(_T2DM_CODES)

    enc_start = _past_date(_REFERENCE_DATE, 1, rng, 90)
    egfr_value = round(rng.uniform(75, 120), 1)  # normal eGFR

    return [
        _patient(pid, birth, sex),
        _condition(f"synth-cond-{idx:04d}-t2dm", pid, t2dm_code, t2dm_display, dx_date, dx_date),
        _encounter(f"synth-enc-{idx:04d}-01", pid, enc_start, enc_start + timedelta(days=1)),
        _observation(
            f"synth-obs-{idx:04d}-egfr",
            pid,
            *_EGFR_CODES[0],
            egfr_value,
            "mL/min/1.73m2",
            enc_start,
        ),
    ]


def _build_ckd_only_patient(idx: int, rng: random.Random) -> list[dict]:
    """CKD without T2DM — fails inc-001."""
    pid = f"synth-pt-{idx:04d}"
    age = rng.randint(45, 80)
    sex = rng.choice(["male", "female"])
    birth = _age_to_birth(age, rng)
    dx_date = _past_date(_REFERENCE_DATE, rng.uniform(1, 4), rng, 90)
    ckd_code, ckd_display = rng.choice(_CKD_INCLUSION_CODES)

    enc_start = _past_date(_REFERENCE_DATE, 1, rng, 90)
    egfr_value = round(rng.uniform(20, 58), 1)

    return [
        _patient(pid, birth, sex),
        _condition(f"synth-cond-{idx:04d}-ckd", pid, ckd_code, ckd_display, dx_date, dx_date),
        _encounter(f"synth-enc-{idx:04d}-01", pid, enc_start, enc_start + timedelta(days=1)),
        _observation(
            f"synth-obs-{idx:04d}-egfr",
            pid,
            *_EGFR_CODES[0],
            egfr_value,
            "mL/min/1.73m2",
            enc_start,
        ),
    ]


def _build_healthy_patient(idx: int, rng: random.Random) -> list[dict]:
    """No T2DM, no CKD — fails inc-001 and inc-002."""
    pid = f"synth-pt-{idx:04d}"
    age = rng.randint(30, 70)
    sex = rng.choice(["male", "female"])
    birth = _age_to_birth(age, rng)
    enc_start = _past_date(_REFERENCE_DATE, 1, rng, 90)

    return [
        _patient(pid, birth, sex),
        _encounter(f"synth-enc-{idx:04d}-01", pid, enc_start, enc_start + timedelta(days=1)),
    ]


def _build_minor_patient(idx: int, rng: random.Random) -> list[dict]:
    """Minor (age < 18) — fails inc-004 (age ≥ 18)."""
    pid = f"synth-pt-{idx:04d}"
    age = rng.randint(8, 17)
    sex = rng.choice(["male", "female"])
    birth = _age_to_birth(age, rng)
    dx_date = _past_date(_REFERENCE_DATE, 0.5, rng, 30)
    t2dm_code, t2dm_display = _T2DM_CODES[0]

    enc_start = _past_date(_REFERENCE_DATE, 0.5, rng, 30)
    return [
        _patient(pid, birth, sex),
        _condition(f"synth-cond-{idx:04d}-t2dm", pid, t2dm_code, t2dm_display, dx_date, dx_date),
        _encounter(f"synth-enc-{idx:04d}-01", pid, enc_start, enc_start + timedelta(days=1)),
    ]


def _build_short_history_patient(idx: int, rng: random.Random) -> list[dict]:
    """Adult with T2DM+CKD but only very recent encounter history (<365d lookback)."""
    pid = f"synth-pt-{idx:04d}"
    age = rng.randint(40, 65)
    sex = rng.choice(["male", "female"])
    birth = _age_to_birth(age, rng)
    # Only 1 encounter, very recent (within 30 days of reference date)
    dx_date = _past_date(_REFERENCE_DATE, 0.05, rng, 20)
    t2dm_code, t2dm_display = _T2DM_CODES[0]
    ckd_code, ckd_display = _CKD_INCLUSION_CODES[1]

    enc_start = dx_date
    return [
        _patient(pid, birth, sex),
        _condition(f"synth-cond-{idx:04d}-t2dm", pid, t2dm_code, t2dm_display, dx_date, dx_date),
        _condition(f"synth-cond-{idx:04d}-ckd", pid, ckd_code, ckd_display, dx_date, dx_date),
        _encounter(f"synth-enc-{idx:04d}-01", pid, enc_start, enc_start + timedelta(days=1)),
    ]


def _build_missing_lab_patient(idx: int, rng: random.Random) -> list[dict]:
    """T2DM + CKD patient with no Observation resources (missing lab data for QA testing)."""
    pid = f"synth-pt-{idx:04d}"
    age = rng.randint(50, 75)
    sex = rng.choice(["male", "female"])
    birth = _age_to_birth(age, rng)
    dx_date = _past_date(_REFERENCE_DATE, 2, rng, 90)
    t2dm_code, t2dm_display = _T2DM_CODES[0]
    ckd_code, ckd_display = _CKD_INCLUSION_CODES[2]  # stage 3a

    enc_start_1 = _past_date(_REFERENCE_DATE, 2, rng, 120)
    enc_start_2 = _past_date(_REFERENCE_DATE, 0.5, rng, 60)

    return [
        _patient(pid, birth, sex),
        _condition(f"synth-cond-{idx:04d}-t2dm", pid, t2dm_code, t2dm_display, dx_date, dx_date),
        _condition(f"synth-cond-{idx:04d}-ckd", pid, ckd_code, ckd_display, dx_date, dx_date),
        _encounter(f"synth-enc-{idx:04d}-01", pid, enc_start_1, enc_start_1 + timedelta(days=1)),
        _encounter(f"synth-enc-{idx:04d}-02", pid, enc_start_2, enc_start_2 + timedelta(days=1)),
        # No Observation resources — missing lab data
    ]


def _build_missing_birthdate_patient(idx: int, rng: random.Random) -> list[dict]:
    """Patient with no birth date — age calculation edge case."""
    pid = f"synth-pt-{idx:04d}"
    sex = rng.choice(["male", "female"])
    enc_start = _past_date(_REFERENCE_DATE, 1, rng, 90)

    resource = {
        "resourceType": "Patient",
        "id": pid,
        "gender": sex,
        # birthDate intentionally omitted
        "deceasedBoolean": False,
    }
    return [
        resource,
        _encounter(f"synth-enc-{idx:04d}-01", pid, enc_start, enc_start + timedelta(days=1)),
    ]


# ---------------------------------------------------------------------------
# Patient specification table
# ---------------------------------------------------------------------------


def _build_all_patients(rng: random.Random) -> list[list[dict]]:
    """Return a list of patient resource groups, one list per patient.

    Categories (indices are 1-based):
    1-30:    T2DM+CKD adults with SGLT2 exposure (optional filter candidates)
    31-60:   T2DM+CKD adults WITHOUT SGLT2 exposure (base cohort, fail optional filter)
    61-70:   T2DM+CKD adults with missing lab data (for missingness reporting)
    71-80:   ESRD patients (excluded by exc-001)
    81-88:   Dialysis patients (excluded by exc-002)
    89-113:  T2DM-only adults (fail inc-002)
    114-133: CKD-only adults (fail inc-001)
    134-143: Healthy adults, no T2DM or CKD (fail inc-001 + inc-002)
    144-153: Minors (fail inc-004, age < 18)
    154-158: Adults with short observation history (<365d lookback)
    159-160: Adults with missing birth date (age edge case)
    """
    patients: list[list[dict]] = []

    for i in range(1, 31):
        patients.append(_build_t2dm_ckd_patient(i, rng, has_sglt2=True))

    for i in range(31, 61):
        patients.append(_build_t2dm_ckd_patient(i, rng, has_sglt2=False))

    for i in range(61, 71):
        patients.append(_build_missing_lab_patient(i, rng))

    for i in range(71, 81):
        patients.append(_build_esrd_excluded_patient(i, rng))

    for i in range(81, 89):
        patients.append(_build_dialysis_excluded_patient(i, rng))

    for i in range(89, 114):
        patients.append(_build_t2dm_only_patient(i, rng))

    for i in range(114, 134):
        patients.append(_build_ckd_only_patient(i, rng))

    for i in range(134, 144):
        patients.append(_build_healthy_patient(i, rng))

    for i in range(144, 154):
        patients.append(_build_minor_patient(i, rng))

    for i in range(154, 159):
        patients.append(_build_short_history_patient(i, rng))

    for i in range(159, 161):
        patients.append(_build_missing_birthdate_patient(i, rng))

    return patients


# ---------------------------------------------------------------------------
# Bundle serialization
# ---------------------------------------------------------------------------


def _as_bundle(batch_id: str, resources: list[dict]) -> dict:
    return {
        "resourceType": "Bundle",
        "id": batch_id,
        "type": "collection",
        "entry": [{"resource": r} for r in resources],
    }


def _write_main_dataset(output_dir: Path, dry_run: bool) -> dict:
    """Write batched FHIR Bundle files and a dataset_info.json manifest."""
    rng = random.Random(_SEED)
    all_patient_groups = _build_all_patients(rng)

    resource_type_counts: dict[str, int] = {}
    patient_count = len(all_patient_groups)
    all_resources: list[dict] = []
    for group in all_patient_groups:
        for r in group:
            rt = r["resourceType"]
            resource_type_counts[rt] = resource_type_counts.get(rt, 0) + 1
            all_resources.append(r)

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        # Write in batches
        batch_idx = 1
        for chunk_start in range(0, len(all_patient_groups), _BATCH_SIZE):
            chunk = all_patient_groups[chunk_start : chunk_start + _BATCH_SIZE]
            chunk_resources: list[dict] = []
            for group in chunk:
                chunk_resources.extend(group)
            bundle = _as_bundle(f"batch-{batch_idx:02d}", chunk_resources)
            out_file = output_dir / f"batch_{batch_idx:02d}.json"
            out_file.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
            batch_idx += 1

        dataset_info = {
            "dataset_id": "synthetic-cohort-v1",
            "name": "Synthetic SGLT2 / T2DM / CKD Cohort — Version 1",
            "description": (
                "Deterministic synthetic FHIR R4 patient data for portfolio demonstration. "
                "All patients are entirely fictional. Not real clinical data. "
                f"Generated with seed={_SEED}, reference_date={_REFERENCE_DATE.isoformat()}."
            ),
            "patient_count": patient_count,
            "reference_date": _REFERENCE_DATE.isoformat(),
            "seed": _SEED,
            "source": "bundled_deterministic",
            "is_synthetic": True,
            "resource_type_counts": resource_type_counts,
        }
        (output_dir / "dataset_info.json").write_text(
            json.dumps(dataset_info, indent=2), encoding="utf-8"
        )

    return {
        "patient_count": patient_count,
        "resource_type_counts": resource_type_counts,
        "total_resources": len(all_resources),
    }


# ---------------------------------------------------------------------------
# Edge-case test fixtures (static, not generated by random)
# ---------------------------------------------------------------------------


def _write_edge_case_fixtures(edge_dir: Path, dry_run: bool) -> None:
    if dry_run:
        print("  [dry-run] would write edge case fixtures to", edge_dir)
        return

    edge_dir.mkdir(parents=True, exist_ok=True)

    # 1. Single Patient resource (not a Bundle)
    (edge_dir / "single_patient.json").write_text(
        json.dumps(
            {
                "resourceType": "Patient",
                "id": "edge-pt-single",
                "gender": "female",
                "birthDate": "1980-07-14",
                "deceasedBoolean": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # 2. Valid bundle with two patients for baseline
    (edge_dir / "valid_bundle.json").write_text(
        json.dumps(
            _as_bundle(
                "edge-valid",
                [
                    {
                        "resourceType": "Patient",
                        "id": "edge-pt-valid-01",
                        "gender": "male",
                        "birthDate": "1965-03-12",
                        "deceasedBoolean": False,
                    },
                    {
                        "resourceType": "Condition",
                        "id": "edge-cond-valid-01",
                        "subject": {"reference": "Patient/edge-pt-valid-01"},
                        "code": {
                            "coding": [
                                {
                                    "system": _ICD10_SYSTEM,
                                    "code": "E11.9",
                                    "display": "Type 2 diabetes mellitus without complications",
                                }
                            ]
                        },
                        "onsetDateTime": "2019-05-01",
                        "recordedDate": "2019-05-03",
                        "clinicalStatus": {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                    "code": "active",
                                }
                            ]
                        },
                    },
                ],
            ),
            indent=2,
        ),
        encoding="utf-8",
    )

    # 3. Malformed JSON
    (edge_dir / "malformed.json").write_text(
        '{"resourceType": "Patient", "id": "bad-json", "birthDate": ', encoding="utf-8"
    )

    # 4. Condition resource with missing `id`
    (edge_dir / "missing_id.json").write_text(
        json.dumps(
            {
                "resourceType": "Condition",
                # id intentionally omitted
                "subject": {"reference": "Patient/edge-pt-valid-01"},
                "code": {"coding": [{"system": _ICD10_SYSTEM, "code": "E11.9"}]},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # 5. Unsupported resource type
    (edge_dir / "unsupported_type.json").write_text(
        json.dumps({"resourceType": "Claim", "id": "edge-claim-01", "status": "active"}, indent=2),
        encoding="utf-8",
    )

    # 6a. Duplicate resource ID — file A
    (edge_dir / "duplicate_a.json").write_text(
        json.dumps(
            {
                "resourceType": "Patient",
                "id": "edge-pt-duplicate",
                "gender": "male",
                "birthDate": "1970-01-01",
                "deceasedBoolean": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # 6b. Duplicate resource ID — file B (same id, different content)
    (edge_dir / "duplicate_b.json").write_text(
        json.dumps(
            {
                "resourceType": "Patient",
                "id": "edge-pt-duplicate",
                "gender": "female",
                "birthDate": "1975-06-15",
                "deceasedBoolean": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # 7. Orphaned reference — Condition pointing to non-existent Patient
    (edge_dir / "orphaned_reference.json").write_text(
        json.dumps(
            {
                "resourceType": "Condition",
                "id": "edge-cond-orphan",
                "subject": {"reference": "Patient/does-not-exist"},
                "code": {"coding": [{"system": _ICD10_SYSTEM, "code": "E11.9"}]},
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                            "code": "active",
                        }
                    ]
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # 8. Invalid date: Encounter end before start
    (edge_dir / "invalid_enc_dates.json").write_text(
        json.dumps(
            {
                "resourceType": "Encounter",
                "id": "edge-enc-bad-dates",
                "subject": {"reference": "Patient/edge-pt-valid-01"},
                "status": "finished",
                "class": {"code": "AMB"},
                "period": {
                    "start": "2024-06-15",
                    "end": "2024-06-10",  # end before start
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # 9. Observation missing value and unit (ambiguous/incomplete)
    (edge_dir / "obs_missing_value.json").write_text(
        json.dumps(
            {
                "resourceType": "Observation",
                "id": "edge-obs-missing-value",
                "subject": {"reference": "Patient/edge-pt-valid-01"},
                "status": "final",
                "code": {
                    "coding": [
                        {"system": _LOINC_SYSTEM, "code": "62238-1", "display": "eGFR CKD-EPI"}
                    ]
                },
                # valueQuantity intentionally omitted — missing value/unit
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # 10. Patient with birthDate after their earliest encounter date (impossible/QA edge case)
    (edge_dir / "impossible_birthdate.json").write_text(
        json.dumps(
            _as_bundle(
                "edge-impossible-birth",
                [
                    {
                        "resourceType": "Patient",
                        "id": "edge-pt-impossible-birth",
                        "gender": "male",
                        "birthDate": "2030-01-01",  # future birthdate
                        "deceasedBoolean": False,
                    },
                    {
                        "resourceType": "Encounter",
                        "id": "edge-enc-impossible",
                        "subject": {"reference": "Patient/edge-pt-impossible-birth"},
                        "status": "finished",
                        "class": {"code": "AMB"},
                        "period": {"start": "2020-01-01", "end": "2020-01-01"},
                    },
                ],
            ),
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"  Wrote {len(list(edge_dir.iterdir()))} edge-case fixture files to {edge_dir}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic synthetic FHIR fixtures")
    parser.add_argument("--dry-run", action="store_true", help="Print counts only, write nothing")
    args = parser.parse_args()

    output_dir = _ROOT / "data" / "fixtures" / "fhir" / "synthetic_cohort_v1"
    edge_dir = _ROOT / "tests" / "fixtures" / "fhir_edge_cases"

    print("Generating deterministic synthetic FHIR R4 fixtures (seed=42)...")
    print("NOTICE: All data is ENTIRELY SYNTHETIC. Not real patient data.")
    print()

    stats = _write_main_dataset(output_dir, args.dry_run)

    print(f"  Patients:         {stats['patient_count']}")
    print(f"  Total resources:  {stats['total_resources']}")
    for rt, cnt in sorted(stats["resource_type_counts"].items()):
        print(f"    {rt:30s}: {cnt}")

    if not args.dry_run:
        batch_files = sorted(output_dir.glob("batch_*.json"))
        print(f"  Batch files:      {len(batch_files)} in {output_dir}")

    print()
    print("Writing edge-case test fixtures...")
    _write_edge_case_fixtures(edge_dir, args.dry_run)

    print()
    print("Done." if not args.dry_run else "Done (dry-run — no files written).")


if __name__ == "__main__":
    main()
