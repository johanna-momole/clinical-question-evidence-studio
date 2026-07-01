"""Unit tests for all Pydantic schema models.

Tests validate field constraints, cross-field validators, and default values.
No external services or files are required — all tests use inline data.
"""

import pytest
from pydantic import ValidationError

from src.schemas.cohort import CohortStep, MissingnessReport
from src.schemas.evidence import ClinicalTrialRecord, EvidenceRecord, PublicationRecord
from src.schemas.exports import ExportManifest
from src.schemas.phenotype import (
    PhenotypeDefinition,
    TerminologyMapping,
)
from src.schemas.qa import QAResult, QASummary
from src.schemas.question import AmbiguityFlag, ClinicalQuestion, PICOFramework
from src.schemas.synthesis import Citation, EvidenceBrief, GeneratedClaim

# ── ClinicalQuestion ───────────────────────────────────────────────────────────


class TestClinicalQuestion:
    def test_valid_predefined_question(self) -> None:
        q = ClinicalQuestion(
            id="q-test-001",
            raw_question="Test question?",
            pico=PICOFramework(
                population="Adults with T2DM",
                intervention="SGLT2 inhibitors",
                outcomes=["eGFR decline", "cardiovascular events"],
            ),
            source="predefined",
        )
        assert q.id == "q-test-001"
        assert q.status == "draft"
        assert q.source == "predefined"
        assert len(q.ambiguity_flags) == 0

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError, match="status"):
            ClinicalQuestion(
                id="q-test-002",
                raw_question="Test?",
                pico=PICOFramework(
                    population="Adults",
                    intervention="Drug X",
                    outcomes=["Outcome A"],
                ),
                source="user_input",
                status="invalid_status",  # type: ignore[arg-type]
            )

    def test_empty_outcomes_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PICOFramework(
                population="Adults",
                intervention="Drug X",
                outcomes=[],  # min_length=1
            )

    def test_none_comparator_allowed(self) -> None:
        pico = PICOFramework(
            population="Adults",
            intervention="Drug X",
            comparator=None,
            outcomes=["Primary outcome"],
        )
        assert pico.comparator is None

    def test_ambiguity_flag_severity_constraint(self) -> None:
        flag = AmbiguityFlag(
            field="comparator",
            description="No comparator specified",
            suggested_clarification="Specify a comparator arm",
            severity="medium",
        )
        assert flag.severity == "medium"

    def test_invalid_ambiguity_severity_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AmbiguityFlag(
                field="comparator",
                description="desc",
                suggested_clarification="clarify",
                severity="extreme",  # type: ignore[arg-type]
            )


# ── PhenotypeDefinition ────────────────────────────────────────────────────────


class TestPhenotypeDefinition:
    def test_valid_phenotype_creation(self) -> None:
        pheno = PhenotypeDefinition(
            id="pheno-test-001",
            version="0.1.0",
            name="Test Phenotype",
            description="A test phenotype",
            clinical_intent="Descriptive cohort",
            question_id="q-test-001",
            lookback_period_days=365,
            index_date_definition="First qualifying prescription",
        )
        assert pheno.review_status == "draft"
        assert pheno.lookback_period_days == 365
        assert len(pheno.concepts) == 0
        assert len(pheno.inclusion_rules) == 0

    def test_negative_lookback_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PhenotypeDefinition(
                id="pheno-test-002",
                version="0.1.0",
                name="Test",
                description="Test",
                clinical_intent="Test",
                question_id="q-test-001",
                lookback_period_days=-1,
                index_date_definition="First Rx",
            )

    def test_terminology_mapping_defaults(self) -> None:
        mapping = TerminologyMapping(
            concept_id="c-t2dm",
            concept_name="Type 2 Diabetes",
            terminology_system="ICD-10-CM",
            code="E11.9",
            description="Type 2 diabetes mellitus without complications",
            source_or_rationale="ICD-10-CM FY2024 tabular list",
            confidence="high",
        )
        assert mapping.review_status == "candidate"
        assert mapping.is_llm_suggested is False

    def test_llm_suggested_flag(self) -> None:
        mapping = TerminologyMapping(
            concept_id="c-test",
            concept_name="Test Concept",
            terminology_system="LOINC",
            code="12345-6",
            description="Test lab",
            source_or_rationale="LLM suggestion",
            confidence="low",
            is_llm_suggested=True,
        )
        assert mapping.is_llm_suggested is True
        assert mapping.review_status == "candidate"

    def test_invalid_terminology_system_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TerminologyMapping(
                concept_id="c-test",
                concept_name="Test",
                terminology_system="NDC",  # type: ignore[arg-type]  # not in Literal
                code="12345",
                description="Test",
                source_or_rationale="Test",
                confidence="high",
            )


# ── CohortStep ─────────────────────────────────────────────────────────────────


class TestCohortStep:
    def test_valid_attrition_step(self) -> None:
        step = CohortStep(
            step_number=1,
            label="Age ≥18 years",
            description="Exclude patients under 18",
            records_in=1000,
            records_excluded=42,
            records_out=958,
        )
        assert step.records_out == 958

    def test_attrition_math_enforced(self) -> None:
        """records_out must equal records_in - records_excluded."""
        with pytest.raises(ValidationError, match="Attrition math error"):
            CohortStep(
                step_number=1,
                label="Age filter",
                description="Age ≥18",
                records_in=1000,
                records_excluded=42,
                records_out=900,  # Wrong — should be 958
            )

    def test_zero_exclusions_valid(self) -> None:
        step = CohortStep(
            step_number=2,
            label="No exclusions",
            description="Informational step",
            records_in=958,
            records_excluded=0,
            records_out=958,
        )
        assert step.records_out == step.records_in

    def test_negative_step_number_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CohortStep(
                step_number=0,  # ge=1
                label="Bad step",
                description="Should fail",
                records_in=100,
                records_excluded=10,
                records_out=90,
            )


# ── MissingnessReport ─────────────────────────────────────────────────────────


class TestMissingnessReport:
    def test_valid_missingness(self) -> None:
        r = MissingnessReport(
            variable="eGFR at baseline",
            available_count=820,
            missing_count=180,
            total_count=1000,
            availability_pct=82.0,
        )
        assert r.availability_pct == 82.0

    def test_count_reconciliation_enforced(self) -> None:
        with pytest.raises(ValidationError, match="Missingness count error"):
            MissingnessReport(
                variable="eGFR",
                available_count=800,
                missing_count=180,  # 800 + 180 = 980, not 1000
                total_count=1000,
                availability_pct=80.0,
            )


# ── QAResult and QASummary ────────────────────────────────────────────────────


class TestQASchemas:
    def test_qa_result_valid(self) -> None:
        result = QAResult(
            check_id="dq-001",
            check_name="Required columns present",
            category="data_quality",
            status="passed",
            description="Validates that all required columns exist in the dataset",
            severity="critical",
        )
        assert result.status == "passed"
        assert result.severity == "critical"

    def test_qa_summary_counts_computed_automatically(self) -> None:
        results = [
            QAResult(
                check_id=f"check-{i}",
                check_name=f"Check {i}",
                category="data_quality",
                status=status,
                description=f"Description {i}",
                severity="major",
            )
            for i, status in enumerate(["passed", "passed", "warning", "failed", "not_applicable"])
        ]
        summary = QASummary(run_id="run-001", results=results)
        assert summary.passed == 2
        assert summary.warnings == 1
        assert summary.failed == 1
        assert summary.not_applicable == 1

    def test_critical_failure_detected(self) -> None:
        results = [
            QAResult(
                check_id="dq-critical",
                check_name="Schema validation",
                category="data_quality",
                status="failed",
                description="Required column missing",
                severity="critical",
            )
        ]
        summary = QASummary(run_id="run-002", results=results)
        assert summary.has_critical_failure is True

    def test_no_critical_failure_when_all_pass(self) -> None:
        results = [
            QAResult(
                check_id="dq-ok",
                check_name="Schema valid",
                category="data_quality",
                status="passed",
                description="All columns present",
                severity="critical",
            )
        ]
        summary = QASummary(run_id="run-003", results=results)
        assert summary.has_critical_failure is False


# ── EvidenceRecord ─────────────────────────────────────────────────────────────


class TestEvidenceSchemas:
    def test_publication_record_defaults(self) -> None:
        pub = PublicationRecord(
            id="ev-001",
            title="EMPA-REG OUTCOME Trial",
            identifier="26378978",
            source_type="publication",
        )
        assert pub.source_type == "publication"
        assert pub.review_status == "pending"
        assert pub.tags == []

    def test_relevance_score_range_enforced(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceRecord(
                id="ev-002",
                source_type="publication",
                title="Test",
                identifier="12345",
                relevance_score=1.5,  # must be 0.0–1.0
            )

    def test_clinical_trial_record_fields(self) -> None:
        trial = ClinicalTrialRecord(
            id="ev-003",
            title="CREDENCE Trial",
            identifier="NCT02065791",
            nct_id="NCT02065791",
            phase="Phase 3",
            trial_status="Completed",
            enrollment=4401,
            source_type="clinical_trial",
        )
        assert trial.nct_id == "NCT02065791"
        assert trial.enrollment == 4401


# ── EvidenceBrief ─────────────────────────────────────────────────────────────


class TestEvidenceBriefSchemas:
    def test_default_disclaimer_present(self) -> None:
        brief = EvidenceBrief(
            id="brief-001",
            question_id="q-test-001",
            phenotype_id="pheno-test-001",
            research_question="Test question?",
            pico_summary="P: Adults | I: Drug | C: None | O: Outcome",
            phenotype_summary="Test phenotype",
            cohort_summary_text="N=0 synthetic patients",
            evidence_overview="No evidence retrieved",
            provenance_statement="Generated in demo mode",
        )
        assert "synthetic" in brief.disclaimer.lower()
        assert brief.is_deterministic_mode is True
        assert brief.human_review_status == "not_reviewed"

    def test_generated_claim_causal_default_false(self) -> None:
        claim = GeneratedClaim(
            claim_id="claim-001",
            claim_text="SGLT2 inhibitors are associated with reduced CKD progression.",
            claim_type="retrieved_fact",
            is_cited=True,
        )
        assert claim.is_causal is False

    def test_citation_fields(self) -> None:
        cite = Citation(
            citation_id="cite-001",
            evidence_id="ev-001",
            source_type="publication",
            title="EMPA-REG OUTCOME",
            identifier="26378978",
            url="https://pubmed.ncbi.nlm.nih.gov/26378978/",
            retrieval_date="2025-01-15",
            short_reference="Zinman et al., 2015 [PMID:26378978]",
        )
        assert cite.citation_id == "cite-001"
        assert "Zinman" in cite.short_reference


# ── ExportManifest ─────────────────────────────────────────────────────────────


_MANIFEST_BASE = {
    "manifest_id": "m-001",
    "brief_id": "b-001",
    "brief_version": 1,
    "brief_content_hash": "ch",
    "snapshot_hash": "sh",
    "bundle_name": "b-001_bundle.zip",
    "generation_mode": "deterministic",
    "origin_classification": "captured_source_fixture",
    "review_status": "not_reviewed",
}


class TestExportManifest:
    def test_all_succeeded_property(self) -> None:
        manifest = ExportManifest(
            **_MANIFEST_BASE,
            run_id="run-001",
            formats_requested=["json", "markdown"],
            formats_completed=["json", "markdown"],
        )
        assert manifest.all_succeeded is True

    def test_partial_completion_not_succeeded(self) -> None:
        manifest = ExportManifest(
            **_MANIFEST_BASE,
            run_id="run-002",
            formats_requested=["json", "pdf"],
            formats_completed=["json"],
        )
        assert manifest.all_succeeded is False
