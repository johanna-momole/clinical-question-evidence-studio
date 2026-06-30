"""Temporal and logical helpers for cohort rule evaluation.

All functions are pure and stateless; they do not access the database directly.
Explicit None handling: missing dates are treated conservatively (patient fails criteria).
"""

from __future__ import annotations

from datetime import date
from typing import NamedTuple

from src.fhir.normalizer import NormalizedDataset
from src.schemas.fhir import (
    NormalizedCondition,
    NormalizedEncounter,
    NormalizedMedication,
    NormalizedObservation,
)

# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def age_on(birth_date: date | None, reference_date: date) -> float | None:
    """Return age in fractional years at reference_date, or None if birth_date is missing."""
    if birth_date is None:
        return None
    delta = reference_date - birth_date
    return delta.days / 365.25


def earliest_encounter_date(encounters: list[NormalizedEncounter]) -> date | None:
    """Return the earliest start_date across a list of encounters, or None if none have dates."""
    dates = [e.start_date for e in encounters if e.start_date is not None]
    return min(dates) if dates else None


def latest_encounter_date(encounters: list[NormalizedEncounter]) -> date | None:
    dates = [e.end_date or e.start_date for e in encounters if e.start_date is not None]
    return max(dates) if dates else None


def observation_period_days(
    encounters: list[NormalizedEncounter], reference_date: date
) -> int | None:
    """Return the number of days between first encounter and reference_date.

    Returns None if no encounter dates are available.
    Conservative: uses start_date of the earliest encounter.
    """
    earliest = earliest_encounter_date(encounters)
    if earliest is None:
        return None
    return (reference_date - earliest).days


# ---------------------------------------------------------------------------
# Per-patient rule evaluation primitives
# ---------------------------------------------------------------------------


def has_condition_code(
    conditions: list[NormalizedCondition],
    codes: frozenset[str],
    before_or_on: date | None = None,
) -> bool:
    """Return True if the patient has any condition with code in `codes`.

    If before_or_on is given, only consider conditions with onset_date or recorded_date
    on or before that cutoff. A condition with no date is excluded (conservative).
    """
    for cond in conditions:
        if cond.code not in codes:
            continue
        if before_or_on is None:
            return True
        cond_date = cond.onset_date or cond.recorded_date
        if cond_date is not None and cond_date <= before_or_on:
            return True
    return False


def has_medication_code(
    medications: list[NormalizedMedication],
    codes: frozenset[str],
    on_or_after: date | None = None,
    within_days: int | None = None,
    reference_date: date | None = None,
) -> bool:
    """Return True if the patient has any medication with code in `codes`.

    on_or_after: medication start_date must be on or after this date.
    within_days + reference_date: start_date must be within this many days before reference.
    A medication with no start_date is excluded (conservative).
    """
    for med in medications:
        if med.code not in codes:
            continue
        med_date = med.start_date
        if med_date is None:
            continue
        if on_or_after is not None and med_date < on_or_after:
            continue
        if within_days is not None and reference_date is not None:
            lookback_start = reference_date - __import__("datetime").timedelta(days=within_days)
            if med_date < lookback_start or med_date > reference_date:
                continue
        return True
    return False


def has_observation_code(
    observations: list[NormalizedObservation],
    codes: frozenset[str],
    within_days: int | None = None,
    reference_date: date | None = None,
) -> bool:
    """Return True if the patient has any observation with code in `codes`.

    within_days + reference_date: effective_date must be within this window before reference.
    An observation with no effective_date is excluded (conservative).
    """
    for obs in observations:
        if obs.code not in codes:
            continue
        obs_date = obs.effective_date
        if obs_date is None:
            continue
        if within_days is not None and reference_date is not None:
            import datetime

            lookback_start = reference_date - datetime.timedelta(days=within_days)
            if obs_date < lookback_start or obs_date > reference_date:
                continue
        return True
    return False


# ---------------------------------------------------------------------------
# Patient group filtering
# ---------------------------------------------------------------------------


class PatientGroup(NamedTuple):
    """Convenience container: a frozenset of patient_id strings."""

    ids: frozenset[str]

    def __len__(self) -> int:
        return len(self.ids)

    def intersection(self, other: PatientGroup) -> PatientGroup:
        return PatientGroup(self.ids & other.ids)

    def difference(self, other: PatientGroup) -> PatientGroup:
        return PatientGroup(self.ids - other.ids)


def all_patient_ids(dataset: NormalizedDataset) -> PatientGroup:
    return PatientGroup(frozenset(p.patient_id for p in dataset.patients))


def patients_meeting_age(
    patient_ids: frozenset[str],
    dataset: NormalizedDataset,
    min_age_years: int,
    reference_date: date,
) -> PatientGroup:
    """Filter to patients who are at least min_age_years old at reference_date.

    Patients with no birth_date are excluded (conservative).
    """
    passing = set()
    birth_by_id = {p.patient_id: p.birth_date for p in dataset.patients}
    for pid in patient_ids:
        birth = birth_by_id.get(pid)
        age = age_on(birth, reference_date)
        if age is not None and age >= min_age_years:
            passing.add(pid)
    return PatientGroup(frozenset(passing))


def patients_with_observation_period(
    patient_ids: frozenset[str],
    dataset: NormalizedDataset,
    min_days: int,
    reference_date: date,
) -> PatientGroup:
    """Filter to patients with at least min_days of observation history before reference_date."""
    from collections import defaultdict

    enc_by_patient: dict[str, list] = defaultdict(list)
    for enc in dataset.encounters:
        if enc.patient_id in patient_ids:
            enc_by_patient[enc.patient_id].append(enc)

    passing = set()
    for pid in patient_ids:
        days = observation_period_days(enc_by_patient.get(pid, []), reference_date)
        if days is not None and days >= min_days:
            passing.add(pid)
    return PatientGroup(frozenset(passing))


def patients_with_condition(
    patient_ids: frozenset[str],
    dataset: NormalizedDataset,
    codes: frozenset[str],
    reference_date: date,
    lookback_days: int | None = None,
) -> PatientGroup:
    """Filter to patients who have at least one condition with a code in `codes`."""
    from collections import defaultdict

    cond_by_patient: dict[str, list] = defaultdict(list)
    for cond in dataset.conditions:
        if cond.patient_id in patient_ids:
            cond_by_patient[cond.patient_id].append(cond)

    passing = set()
    for pid in patient_ids:
        effective_cutoff = reference_date  # condition must be on or before reference date
        if has_condition_code(cond_by_patient.get(pid, []), codes, before_or_on=effective_cutoff):
            passing.add(pid)
    return PatientGroup(frozenset(passing))


def patients_with_medication(
    patient_ids: frozenset[str],
    dataset: NormalizedDataset,
    codes: frozenset[str],
    lookback_days: int | None,
    reference_date: date,
) -> PatientGroup:
    """Filter to patients who have at least one medication with a code in `codes` in the window."""
    from collections import defaultdict

    med_by_patient: dict[str, list] = defaultdict(list)
    for med in dataset.medications:
        if med.patient_id in patient_ids:
            med_by_patient[med.patient_id].append(med)

    passing = set()
    for pid in patient_ids:
        if has_medication_code(
            med_by_patient.get(pid, []),
            codes,
            within_days=lookback_days,
            reference_date=reference_date,
        ):
            passing.add(pid)
    return PatientGroup(frozenset(passing))


def patients_with_observation(
    patient_ids: frozenset[str],
    dataset: NormalizedDataset,
    codes: frozenset[str],
    lookback_days: int | None,
    reference_date: date,
) -> PatientGroup:
    """Filter to patients who have at least one observation with a code in `codes` in the window."""
    from collections import defaultdict

    obs_by_patient: dict[str, list] = defaultdict(list)
    for obs in dataset.observations:
        if obs.patient_id in patient_ids:
            obs_by_patient[obs.patient_id].append(obs)

    passing = set()
    for pid in patient_ids:
        if has_observation_code(
            obs_by_patient.get(pid, []),
            codes,
            within_days=lookback_days,
            reference_date=reference_date,
        ):
            passing.add(pid)
    return PatientGroup(frozenset(passing))
