"""Cohort execution quality assurance checks.

Run after cohort engine execution to validate attrition consistency and safety invariants.
Critical failures indicate the cohort result must not be used or exported.
"""

from __future__ import annotations

from typing import Literal

from src.schemas.cohort import CohortAttrition
from src.schemas.qa import QAResult, QASummary


def _qa(
    check_id: str,
    check_name: str,
    status: Literal["passed", "warning", "failed", "not_applicable"],
    description: str,
    severity: Literal["critical", "major", "minor", "info"],
    details: str | None = None,
    affected: list[str] | None = None,
) -> QAResult:
    return QAResult(
        check_id=check_id,
        check_name=check_name,
        category="data_quality",
        status=status,
        description=description,
        severity=severity,
        details=details,
        affected_records=affected or [],
    )


def run_cohort_checks(
    attrition: CohortAttrition,
    run_id: str,
    initial_count: int,
    patient_ids_at_steps: list[set[str]] | None = None,
) -> QASummary:
    """Run all cohort QA checks and return a QASummary.

    patient_ids_at_steps is optional: if provided (one set per step), enables
    duplicate-patient detection per step.
    """
    results: list[QAResult] = []
    steps = attrition.steps

    # ------------------------------------------------------------------
    # Check 1: non-empty initial population
    # ------------------------------------------------------------------
    if initial_count == 0:
        results.append(
            _qa(
                "coh-001",
                "Non-empty starting population",
                "failed",
                "Cohort execution requires at least one patient in the source dataset",
                "critical",
                details="Starting population is zero — no patients to evaluate",
            )
        )
    else:
        results.append(
            _qa(
                "coh-001",
                "Non-empty starting population",
                "passed",
                "Cohort execution requires at least one patient in the source dataset",
                "info",
                details=f"Starting population: {initial_count}",
            )
        )

    # ------------------------------------------------------------------
    # Check 2: step sequence is complete (no gaps)
    # ------------------------------------------------------------------
    if steps:
        expected_numbers = list(range(1, len(steps) + 1))
        actual_numbers = [s.step_number for s in steps]
        if actual_numbers != expected_numbers:
            results.append(
                _qa(
                    "coh-002",
                    "Sequential step numbering",
                    "failed",
                    "Step numbers must form a continuous 1-based sequence",
                    "critical",
                    details=f"Expected {expected_numbers}, got {actual_numbers}",
                )
            )
        else:
            results.append(
                _qa(
                    "coh-002",
                    "Sequential step numbering",
                    "passed",
                    "Step numbers must form a continuous 1-based sequence",
                    "info",
                )
            )

    # ------------------------------------------------------------------
    # Check 3: no negative exclusion counts
    # ------------------------------------------------------------------
    negative_excl = [s.label for s in steps if s.records_excluded < 0]
    if negative_excl:
        results.append(
            _qa(
                "coh-003",
                "Non-negative exclusion counts",
                "failed",
                "No step may exclude a negative number of patients",
                "critical",
                details=f"Steps with negative exclusion: {negative_excl}",
                affected=negative_excl,
            )
        )
    else:
        results.append(
            _qa(
                "coh-003",
                "Non-negative exclusion counts",
                "passed",
                "No step may exclude a negative number of patients",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # Check 4: attrition math (records_out = records_in - records_excluded)
    # ------------------------------------------------------------------
    math_errors = []
    for s in steps:
        expected = s.records_in - s.records_excluded
        if s.records_out != expected:
            math_errors.append(
                f"step {s.step_number} ({s.label}): "
                f"{s.records_in} - {s.records_excluded} = {expected}, got {s.records_out}"
            )
    if math_errors:
        results.append(
            _qa(
                "coh-004",
                "Attrition math reconciles",
                "failed",
                "records_out must equal records_in minus records_excluded at every step",
                "critical",
                details="; ".join(math_errors),
            )
        )
    else:
        results.append(
            _qa(
                "coh-004",
                "Attrition math reconciles",
                "passed",
                "records_out must equal records_in minus records_excluded at every step",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # Check 5: consecutive step continuity (records_out[n] == records_in[n+1])
    # ------------------------------------------------------------------
    continuity_errors = []
    for curr, nxt in zip(steps, steps[1:], strict=False):
        if curr.records_out != nxt.records_in:
            continuity_errors.append(
                f"step {curr.step_number} out={curr.records_out} != "
                f"step {nxt.step_number} in={nxt.records_in}"
            )
    if continuity_errors:
        results.append(
            _qa(
                "coh-005",
                "Step continuity",
                "failed",
                "records_out of each step must equal records_in of the next step",
                "critical",
                details="; ".join(continuity_errors),
            )
        )
    else:
        results.append(
            _qa(
                "coh-005",
                "Step continuity",
                "passed",
                "records_out of each step must equal records_in of the next step",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # Check 6: final cohort does not exceed initial population
    # ------------------------------------------------------------------
    if steps and steps[-1].records_out > initial_count:
        results.append(
            _qa(
                "coh-006",
                "Final cohort within bounds",
                "failed",
                "Final cohort count must not exceed the initial population",
                "critical",
                details=f"Final count {steps[-1].records_out} > initial {initial_count}",
            )
        )
    else:
        results.append(
            _qa(
                "coh-006",
                "Final cohort within bounds",
                "passed",
                "Final cohort count must not exceed the initial population",
                "info",
            )
        )

    # ------------------------------------------------------------------
    # Check 7: unexpected empty cohort after first step
    # ------------------------------------------------------------------
    if len(steps) > 1:
        for i, step in enumerate(steps[1:], start=2):
            if step.records_out == 0 and i < len(steps):
                results.append(
                    _qa(
                        "coh-007",
                        "Non-empty intermediate steps",
                        "warning",
                        "An intermediate attrition step produced an empty cohort",
                        "major",
                        details=f"Step {step.step_number} ({step.label}) produced 0 patients; "
                        "all subsequent steps will also be empty",
                    )
                )
                break
        else:
            results.append(
                _qa(
                    "coh-007",
                    "Non-empty intermediate steps",
                    "passed",
                    "An intermediate attrition step produced an empty cohort",
                    "info",
                )
            )

    # ------------------------------------------------------------------
    # Check 8: duplicate patient IDs per step (optional, requires patient_ids_at_steps)
    # ------------------------------------------------------------------
    if patient_ids_at_steps:
        for step, id_set in zip(steps, patient_ids_at_steps, strict=False):
            if len(id_set) != step.records_out:
                results.append(
                    _qa(
                        "coh-008",
                        "No duplicate patient IDs per step",
                        "failed",
                        "Each patient should appear at most once in any cohort step",
                        "critical",
                        details=(
                            f"Step {step.step_number} ({step.label}): "
                            f"records_out={step.records_out} but unique IDs={len(id_set)}"
                        ),
                    )
                )
                break
        else:
            results.append(
                _qa(
                    "coh-008",
                    "No duplicate patient IDs per step",
                    "passed",
                    "Each patient should appear at most once in any cohort step",
                    "info",
                )
            )
    else:
        results.append(
            _qa(
                "coh-008",
                "No duplicate patient IDs per step",
                "not_applicable",
                "Each patient should appear at most once in any cohort step",
                "info",
                details="patient_ids_at_steps not provided; check skipped",
            )
        )

    return QASummary(run_id=run_id, results=results)
