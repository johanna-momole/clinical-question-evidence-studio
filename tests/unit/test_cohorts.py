"""Phase 3 cohort engine, rules, and QA tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.cohorts import rules as R
from src.cohorts.engine import run_cohort
from src.cohorts.service import get_cohort_service
from src.fhir.service import get_fhir_service
from src.phenotypes.repository import PhenotypeRepository
from src.qa.cohort_checks import run_cohort_checks
from src.schemas.cohort import CohortConfiguration
from src.schemas.fhir import NormalizedCondition, NormalizedEncounter
from src.utils.exceptions import UnapprovedPhenotypeError

_FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "fixtures"
_PHENOTYPE_ID = "pheno-sglt2-ckd-t2dm-001"
_DATASET_ID = "synthetic-cohort-v1"


@pytest.fixture
def phenotype_repo() -> PhenotypeRepository:
    return PhenotypeRepository(_FIXTURE_DIR)


@pytest.fixture
def approved_phenotype(phenotype_repo: PhenotypeRepository):
    pheno = phenotype_repo.load(_PHENOTYPE_ID)
    svc = get_cohort_service()
    return svc.approve_phenotype_for_demo(pheno)


@pytest.fixture
def default_config() -> CohortConfiguration:
    return CohortConfiguration(reference_date=date(2025, 6, 1), dataset_id=_DATASET_ID)


# ---------------------------------------------------------------------------
# rules.py — temporal helpers
# ---------------------------------------------------------------------------


class TestTemporalHelpers:
    def test_age_on_basic(self) -> None:
        age = R.age_on(date(1960, 1, 1), date(2025, 1, 1))
        assert age == pytest.approx(65.0, abs=0.1)

    def test_age_on_none_birthdate(self) -> None:
        assert R.age_on(None, date(2025, 1, 1)) is None

    def test_earliest_encounter_date(self) -> None:
        encs = [
            NormalizedEncounter(
                patient_id="p1",
                encounter_id="e1",
                start_date=date(2023, 1, 1),
                source_resource_id="e1",
            ),
            NormalizedEncounter(
                patient_id="p1",
                encounter_id="e2",
                start_date=date(2020, 1, 1),
                source_resource_id="e2",
            ),
        ]
        assert R.earliest_encounter_date(encs) == date(2020, 1, 1)

    def test_earliest_encounter_date_empty(self) -> None:
        assert R.earliest_encounter_date([]) is None

    def test_observation_period_days(self) -> None:
        encs = [
            NormalizedEncounter(
                patient_id="p1",
                encounter_id="e1",
                start_date=date(2024, 1, 1),
                source_resource_id="e1",
            )
        ]
        days = R.observation_period_days(encs, date(2025, 1, 1))
        assert days == 366  # 2024 is a leap year

    def test_has_condition_code_match(self) -> None:
        conds = [
            NormalizedCondition(
                patient_id="p1",
                condition_id="c1",
                code="E11.9",
                code_system="icd10",
                onset_date=date(2020, 1, 1),
                source_resource_id="c1",
            )
        ]
        assert R.has_condition_code(conds, frozenset({"E11.9"})) is True

    def test_has_condition_code_no_match(self) -> None:
        conds = [
            NormalizedCondition(
                patient_id="p1",
                condition_id="c1",
                code="N18.9",
                code_system="icd10",
                source_resource_id="c1",
            )
        ]
        assert R.has_condition_code(conds, frozenset({"E11.9"})) is False

    def test_has_condition_code_respects_cutoff(self) -> None:
        conds = [
            NormalizedCondition(
                patient_id="p1",
                condition_id="c1",
                code="E11.9",
                code_system="icd10",
                onset_date=date(2026, 1, 1),
                source_resource_id="c1",
            )
        ]
        assert (
            R.has_condition_code(conds, frozenset({"E11.9"}), before_or_on=date(2025, 1, 1))
            is False
        )

    def test_has_condition_code_missing_date_excluded(self) -> None:
        conds = [
            NormalizedCondition(
                patient_id="p1",
                condition_id="c1",
                code="E11.9",
                code_system="icd10",
                source_resource_id="c1",
            )
        ]
        assert (
            R.has_condition_code(conds, frozenset({"E11.9"}), before_or_on=date(2025, 1, 1))
            is False
        )


class TestPatientGroup:
    def test_intersection(self) -> None:
        a = R.PatientGroup(frozenset({"p1", "p2", "p3"}))
        b = R.PatientGroup(frozenset({"p2", "p3", "p4"}))
        result = a.intersection(b)
        assert result.ids == frozenset({"p2", "p3"})

    def test_difference(self) -> None:
        a = R.PatientGroup(frozenset({"p1", "p2", "p3"}))
        b = R.PatientGroup(frozenset({"p2"}))
        result = a.difference(b)
        assert result.ids == frozenset({"p1", "p3"})

    def test_len(self) -> None:
        a = R.PatientGroup(frozenset({"p1", "p2"}))
        assert len(a) == 2


# ---------------------------------------------------------------------------
# Cohort engine — gating
# ---------------------------------------------------------------------------


class TestCohortEngineGating:
    def test_unapproved_phenotype_raises(
        self, phenotype_repo: PhenotypeRepository, default_config: CohortConfiguration
    ) -> None:
        pheno = phenotype_repo.load(_PHENOTYPE_ID)
        assert pheno.review_status != "approved"
        fhir_svc = get_fhir_service()
        fhir_svc.ingest(_DATASET_ID)
        dataset = fhir_svc.get_dataset(_DATASET_ID)
        with pytest.raises(UnapprovedPhenotypeError):
            run_cohort(pheno, default_config, dataset, fhir_run_id="test-run")

    def test_approved_phenotype_runs(
        self, approved_phenotype, default_config: CohortConfiguration
    ) -> None:
        fhir_svc = get_fhir_service()
        fhir_svc.ingest(_DATASET_ID)
        dataset = fhir_svc.get_dataset(_DATASET_ID)
        run = run_cohort(approved_phenotype, default_config, dataset, fhir_run_id="test-run")
        assert run.summary.final_cohort_count > 0

    def test_llm_suggested_medication_not_required(
        self, approved_phenotype, default_config: CohortConfiguration
    ) -> None:
        """SGLT2 (RxNorm, LLM-suggested) must never gate the required cohort, even though
        inc-003 is marked required=True in the phenotype JSON."""
        fhir_svc = get_fhir_service()
        fhir_svc.ingest(_DATASET_ID)
        dataset = fhir_svc.get_dataset(_DATASET_ID)
        run = run_cohort(approved_phenotype, default_config, dataset, fhir_run_id="test-run")
        step_labels = [s.label for s in run.attrition.steps]
        assert not any("SGLT2" in label and "EXPLORATORY" not in label for label in step_labels)
        assert any("LLM-suggested" in w for w in run.warnings)

    def test_medication_filter_opt_in_produces_warning(self, approved_phenotype) -> None:
        config = CohortConfiguration(
            reference_date=date(2025, 6, 1),
            dataset_id=_DATASET_ID,
            include_medication_exposure_filter=True,
        )
        fhir_svc = get_fhir_service()
        fhir_svc.ingest(_DATASET_ID)
        dataset = fhir_svc.get_dataset(_DATASET_ID)
        run = run_cohort(approved_phenotype, config, dataset, fhir_run_id="test-run")
        assert any("PROVISIONAL" in w for w in run.warnings)
        assert any("EXPLORATORY" in s.label for s in run.attrition.steps)


# ---------------------------------------------------------------------------
# Cohort engine — attrition correctness
# ---------------------------------------------------------------------------


class TestCohortAttrition:
    def test_attrition_math_reconciles(
        self, approved_phenotype, default_config: CohortConfiguration
    ) -> None:
        fhir_svc = get_fhir_service()
        fhir_svc.ingest(_DATASET_ID)
        dataset = fhir_svc.get_dataset(_DATASET_ID)
        run = run_cohort(approved_phenotype, default_config, dataset, fhir_run_id="test-run")
        assert run.attrition.reconciles is True
        for step in run.attrition.steps:
            assert step.records_out == step.records_in - step.records_excluded

    def test_first_step_is_full_population(
        self, approved_phenotype, default_config: CohortConfiguration
    ) -> None:
        fhir_svc = get_fhir_service()
        fhir_svc.ingest(_DATASET_ID)
        dataset = fhir_svc.get_dataset(_DATASET_ID)
        run = run_cohort(approved_phenotype, default_config, dataset, fhir_run_id="test-run")
        assert run.attrition.steps[0].records_in == 160
        assert run.attrition.steps[0].records_out == 160
        assert run.attrition.steps[0].records_excluded == 0

    def test_final_count_within_bounds(
        self, approved_phenotype, default_config: CohortConfiguration
    ) -> None:
        fhir_svc = get_fhir_service()
        fhir_svc.ingest(_DATASET_ID)
        dataset = fhir_svc.get_dataset(_DATASET_ID)
        run = run_cohort(approved_phenotype, default_config, dataset, fhir_run_id="test-run")
        assert 0 < run.summary.final_cohort_count <= run.summary.initial_population

    def test_age_filter_excludes_minors(
        self, approved_phenotype, default_config: CohortConfiguration
    ) -> None:
        fhir_svc = get_fhir_service()
        fhir_svc.ingest(_DATASET_ID)
        dataset = fhir_svc.get_dataset(_DATASET_ID)
        run = run_cohort(approved_phenotype, default_config, dataset, fhir_run_id="test-run")
        age_step = run.attrition.steps[1]
        assert age_step.records_excluded > 0

    def test_determinism_across_runs(
        self, approved_phenotype, default_config: CohortConfiguration
    ) -> None:
        fhir_svc = get_fhir_service()
        fhir_svc.ingest(_DATASET_ID)
        dataset = fhir_svc.get_dataset(_DATASET_ID)
        run1 = run_cohort(approved_phenotype, default_config, dataset, fhir_run_id="run-1")
        run2 = run_cohort(approved_phenotype, default_config, dataset, fhir_run_id="run-2")
        steps1 = [(s.records_in, s.records_excluded, s.records_out) for s in run1.attrition.steps]
        steps2 = [(s.records_in, s.records_excluded, s.records_out) for s in run2.attrition.steps]
        assert steps1 == steps2
        assert run1.summary.final_cohort_count == run2.summary.final_cohort_count


# ---------------------------------------------------------------------------
# Cohort QA checks
# ---------------------------------------------------------------------------


class TestCohortQAChecks:
    def test_valid_attrition_passes_all_critical_checks(
        self, approved_phenotype, default_config: CohortConfiguration
    ) -> None:
        fhir_svc = get_fhir_service()
        fhir_svc.ingest(_DATASET_ID)
        dataset = fhir_svc.get_dataset(_DATASET_ID)
        run = run_cohort(approved_phenotype, default_config, dataset, fhir_run_id="test-run")
        qa = run_cohort_checks(run.attrition, "test-run", run.summary.initial_population)
        assert qa.has_critical_failure is False
        assert qa.failed == 0

    def test_empty_initial_population_fails_critical(self) -> None:
        from src.schemas.cohort import CohortAttrition, CohortStep

        steps = [
            CohortStep(
                step_number=1,
                label="All patients",
                description="d",
                records_in=0,
                records_excluded=0,
                records_out=0,
            )
        ]
        attrition = CohortAttrition(steps=steps)
        qa = run_cohort_checks(attrition, "test-run", initial_count=0)
        assert qa.has_critical_failure is True

    def test_broken_math_detected(self) -> None:
        from pydantic import ValidationError

        from src.schemas.cohort import CohortStep

        with pytest.raises(ValidationError):
            # CohortStep model validator should reject inconsistent math
            CohortStep(
                step_number=1,
                label="Bad step",
                description="d",
                records_in=100,
                records_excluded=10,
                records_out=95,  # should be 90
            )


# ---------------------------------------------------------------------------
# Cohort service
# ---------------------------------------------------------------------------


class TestCohortService:
    def test_service_run_returns_three_tuple(
        self, phenotype_repo: PhenotypeRepository, default_config: CohortConfiguration
    ) -> None:
        pheno = phenotype_repo.load(_PHENOTYPE_ID)
        svc = get_cohort_service()
        approved = svc.approve_phenotype_for_demo(pheno)
        run, fhir_qa, cohort_qa = svc.run(approved, default_config)
        assert run.run_id
        assert fhir_qa.run_id
        assert cohort_qa.run_id

    def test_get_run_after_execution(
        self, phenotype_repo: PhenotypeRepository, default_config: CohortConfiguration
    ) -> None:
        pheno = phenotype_repo.load(_PHENOTYPE_ID)
        svc = get_cohort_service()
        approved = svc.approve_phenotype_for_demo(pheno)
        run, _, _ = svc.run(approved, default_config)
        fetched = svc.get_run(run.run_id)
        assert fetched.run_id == run.run_id

    def test_get_run_unknown_raises(self) -> None:
        from src.utils.exceptions import CohortRunNotFoundError

        svc = get_cohort_service()
        with pytest.raises(CohortRunNotFoundError):
            svc.get_run("nonexistent-run-id")

    def test_approve_phenotype_for_demo_does_not_mutate_original(
        self, phenotype_repo: PhenotypeRepository
    ) -> None:
        pheno = phenotype_repo.load(_PHENOTYPE_ID)
        original_status = pheno.review_status
        svc = get_cohort_service()
        approved = svc.approve_phenotype_for_demo(pheno)
        assert approved.review_status == "approved"
        assert pheno.review_status == original_status
