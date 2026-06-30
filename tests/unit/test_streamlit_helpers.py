"""Tests for shared Streamlit UI helper functions (pure functions — no Streamlit required)."""

import json
from pathlib import Path

import pytest

from app.components.ui_helpers import (
    ambiguity_severity_order,
    attrition_table_rows,
    calculate_review_stats,
    cohort_run_to_json_bytes,
    concept_display_name,
    format_ambiguity_label,
    format_attrition_pct,
    mapping_review_summary,
    new_run_id,
    qa_status_color,
    qa_summary_rows,
    question_to_json_bytes,
    validate_pico_completeness,
)
from src.cohorts.engine import run_cohort
from src.cohorts.service import get_cohort_service
from src.fhir.service import get_fhir_service
from src.phenotypes.repository import PhenotypeRepository
from src.qa.cohort_checks import run_cohort_checks
from src.schemas.cohort import CohortConfiguration
from src.schemas.phenotype import PhenotypeDefinition
from src.schemas.question import ClinicalQuestion, PICOFramework

_FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "fixtures"
_PHENOTYPE_ID = "pheno-sglt2-ckd-t2dm-001"
_DATASET_ID = "synthetic-cohort-v1"


@pytest.fixture
def phenotype() -> PhenotypeDefinition:
    path = _FIXTURE_DIR / "phenotypes" / "sglt2_ckd_t2dm_phenotype.json"
    return PhenotypeDefinition.model_validate(json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture
def valid_pico_dict() -> dict:  # type: ignore[type-arg]
    return {
        "population": "Adults with T2DM and CKD",
        "intervention": "SGLT2 inhibitors",
        "comparator": None,
        "outcomes": ["eGFR decline"],
        "timeframe": "12 months",
        "study_intent": "Cohort study",
    }


class TestValidatePICOCompleteness:
    def test_valid_pico_returns_no_errors(self, valid_pico_dict: dict) -> None:  # type: ignore[type-arg]
        errors = validate_pico_completeness(valid_pico_dict)
        assert errors == []

    def test_empty_population_returns_error(self, valid_pico_dict: dict) -> None:  # type: ignore[type-arg]
        valid_pico_dict["population"] = ""
        errors = validate_pico_completeness(valid_pico_dict)
        assert any("population" in e for e in errors)

    def test_empty_intervention_returns_error(self, valid_pico_dict: dict) -> None:  # type: ignore[type-arg]
        valid_pico_dict["intervention"] = ""
        errors = validate_pico_completeness(valid_pico_dict)
        assert any("intervention" in e for e in errors)

    def test_empty_outcomes_returns_error(self, valid_pico_dict: dict) -> None:  # type: ignore[type-arg]
        valid_pico_dict["outcomes"] = []
        errors = validate_pico_completeness(valid_pico_dict)
        assert any("outcome" in e.lower() for e in errors)

    def test_demo_placeholder_in_population_returns_error(
        self,
        valid_pico_dict: dict,  # type: ignore[type-arg]
    ) -> None:
        valid_pico_dict["population"] = "[DEMO MODE] Population not extracted"
        errors = validate_pico_completeness(valid_pico_dict)
        assert any("placeholder" in e.lower() for e in errors)


class TestAmbiguityHelpers:
    def test_severity_order_high_is_smallest(self) -> None:
        assert ambiguity_severity_order("high") < ambiguity_severity_order("medium")
        assert ambiguity_severity_order("medium") < ambiguity_severity_order("low")

    def test_format_ambiguity_label_high(self) -> None:
        assert format_ambiguity_label("high") == "HIGH"

    def test_format_ambiguity_label_unknown(self) -> None:
        result = format_ambiguity_label("custom")
        assert result == "CUSTOM"


class TestReviewStats:
    def test_calculate_review_stats_totals(self, phenotype: PhenotypeDefinition) -> None:
        stats = calculate_review_stats(phenotype)
        assert stats["total"] > 0
        assert stats["total"] == stats["candidate"] + stats["approved"] + stats["rejected"]

    def test_calculate_review_stats_all_unverified(self, phenotype: PhenotypeDefinition) -> None:
        stats = calculate_review_stats(phenotype)
        assert stats["unverified"] == stats["total"]

    def test_calculate_review_stats_llm_suggested_count(
        self, phenotype: PhenotypeDefinition
    ) -> None:
        stats = calculate_review_stats(phenotype)
        assert stats["llm_suggested"] == 4  # 4 RxNorm codes

    def test_pct_reviewed_is_zero(self, phenotype: PhenotypeDefinition) -> None:
        stats = calculate_review_stats(phenotype)
        assert stats["pct_reviewed"] == 0.0


class TestConceptHelpers:
    def test_concept_display_name_found(self, phenotype: PhenotypeDefinition) -> None:
        name = concept_display_name("c-t2dm", phenotype)
        assert "diabetes" in name.lower() or "T2DM" in name

    def test_concept_display_name_not_found(self, phenotype: PhenotypeDefinition) -> None:
        name = concept_display_name("c-nonexistent", phenotype)
        assert name == "c-nonexistent"

    def test_mapping_review_summary_all_candidate(self, phenotype: PhenotypeDefinition) -> None:
        concept = phenotype.concepts[0]
        summary = mapping_review_summary(concept.mappings)
        assert "pending" in summary.lower()

    def test_mapping_review_summary_empty(self) -> None:
        summary = mapping_review_summary([])
        assert "no" in summary.lower()


class TestDownloadHelpers:
    def test_question_to_json_bytes_is_valid_json(self) -> None:
        q = ClinicalQuestion(
            id="q-test-001",
            raw_question="Test",
            pico=PICOFramework(population="P", intervention="I", outcomes=["O"]),
            status="draft",
            source="user_input",
        )
        data = question_to_json_bytes(q)
        parsed = json.loads(data.decode("utf-8"))
        assert parsed["id"] == "q-test-001"


class TestRunIdHelpers:
    def test_new_run_id_is_uuid_format(self) -> None:
        rid = new_run_id()
        assert len(rid) == 36
        assert rid.count("-") == 4

    def test_new_run_ids_are_unique(self) -> None:
        ids = {new_run_id() for _ in range(10)}
        assert len(ids) == 10


@pytest.fixture
def cohort_run():
    from datetime import date

    repo = PhenotypeRepository(_FIXTURE_DIR)
    pheno = repo.load(_PHENOTYPE_ID)
    svc = get_cohort_service()
    approved = svc.approve_phenotype_for_demo(pheno)
    fhir_svc = get_fhir_service()
    fhir_svc.ingest(_DATASET_ID)
    dataset = fhir_svc.get_dataset(_DATASET_ID)
    config = CohortConfiguration(reference_date=date(2025, 6, 1), dataset_id=_DATASET_ID)
    return run_cohort(approved, config, dataset, fhir_run_id="ui-test-run")


class TestAttritionTableRows:
    def test_row_count_matches_steps(self, cohort_run) -> None:
        rows = attrition_table_rows(cohort_run.attrition)
        assert len(rows) == len(cohort_run.attrition.steps)

    def test_row_fields_present(self, cohort_run) -> None:
        rows = attrition_table_rows(cohort_run.attrition)
        first = rows[0]
        assert set(first.keys()) == {
            "Step",
            "Label",
            "Records In",
            "Excluded",
            "Records Out",
            "Exclusion Reason",
        }

    def test_first_row_matches_first_step(self, cohort_run) -> None:
        rows = attrition_table_rows(cohort_run.attrition)
        step = cohort_run.attrition.steps[0]
        assert rows[0]["Records In"] == step.records_in
        assert rows[0]["Records Out"] == step.records_out


class TestQASummaryRows:
    def test_row_count_matches_results(self, cohort_run) -> None:
        qa = run_cohort_checks(
            cohort_run.attrition, "ui-test-run", cohort_run.summary.initial_population
        )
        rows = qa_summary_rows(qa)
        assert len(rows) == len(qa.results)

    def test_status_is_uppercased(self, cohort_run) -> None:
        qa = run_cohort_checks(
            cohort_run.attrition, "ui-test-run", cohort_run.summary.initial_population
        )
        rows = qa_summary_rows(qa)
        assert all(r["Status"] == r["Status"].upper() for r in rows)


class TestCohortRunToJsonBytes:
    def test_round_trips_to_valid_json(self, cohort_run) -> None:
        data = cohort_run_to_json_bytes(cohort_run)
        parsed = json.loads(data.decode("utf-8"))
        assert parsed["run_id"] == cohort_run.run_id

    def test_includes_synthetic_provenance(self, cohort_run) -> None:
        data = cohort_run_to_json_bytes(cohort_run)
        parsed = json.loads(data.decode("utf-8"))
        assert parsed["provenance"]["is_synthetic"] is True


class TestFormatAttritionPct:
    def test_full_retention(self) -> None:
        assert format_attrition_pct(100, 100) == "100.0% retained"

    def test_partial_retention(self) -> None:
        assert format_attrition_pct(160, 70) == "43.8% retained"

    def test_zero_records_in_returns_na(self) -> None:
        assert format_attrition_pct(0, 0) == "N/A"


class TestQAStatusColor:
    def test_passed_is_green(self) -> None:
        assert qa_status_color("passed") == "green"

    def test_warning_is_orange(self) -> None:
        assert qa_status_color("warning") == "orange"

    def test_failed_is_red(self) -> None:
        assert qa_status_color("failed") == "red"

    def test_unknown_status_is_gray(self) -> None:
        assert qa_status_color("bogus") == "gray"

    def test_case_insensitive(self) -> None:
        assert qa_status_color("PASSED") == "green"
