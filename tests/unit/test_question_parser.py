"""Tests for the question parser service and demo parser."""

from pathlib import Path

import pytest

from src.question_parser.demo_parser import DemoQuestionParser
from src.question_parser.service import QuestionService

_FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "fixtures"


@pytest.fixture
def parser() -> DemoQuestionParser:
    return DemoQuestionParser(_FIXTURE_DIR)


@pytest.fixture
def service() -> QuestionService:
    return QuestionService(parser=DemoQuestionParser(_FIXTURE_DIR), fixture_dir=_FIXTURE_DIR)


class TestDemoParserSupportedQuestions:
    def test_parse_q1_by_id_returns_supported(self, parser: DemoQuestionParser) -> None:
        result = parser.parse("", question_id="q-sglt2-ckd-t2dm-001")
        assert result.is_supported_question is True
        assert result.curated_question_id == "q-sglt2-ckd-t2dm-001"

    def test_parse_q2_by_id_returns_supported(self, parser: DemoQuestionParser) -> None:
        result = parser.parse("", question_id="q-sglt2-ckd-data-elem-001")
        assert result.is_supported_question is True

    def test_parse_q3_by_id_returns_supported(self, parser: DemoQuestionParser) -> None:
        result = parser.parse("", question_id="q-sglt2-ckd-outcome-eval-001")
        assert result.is_supported_question is True

    def test_q1_result_has_approved_status(self, parser: DemoQuestionParser) -> None:
        result = parser.parse("", question_id="q-sglt2-ckd-t2dm-001")
        assert result.question.status == "approved"

    def test_q1_pico_not_empty(self, parser: DemoQuestionParser) -> None:
        result = parser.parse("", question_id="q-sglt2-ckd-t2dm-001")
        pico = result.question.pico
        assert pico.population.strip()
        assert pico.intervention.strip()
        assert len(pico.outcomes) >= 1

    def test_provenance_records_demo_mode(self, parser: DemoQuestionParser) -> None:
        result = parser.parse("", question_id="q-sglt2-ckd-t2dm-001")
        assert result.provenance.is_demo_mode is True
        assert result.provenance.model_id is None
        assert result.provenance.parser_name == "DemoQuestionParser"

    def test_run_id_is_unique_per_call(self, parser: DemoQuestionParser) -> None:
        r1 = parser.parse("", question_id="q-sglt2-ckd-t2dm-001")
        r2 = parser.parse("", question_id="q-sglt2-ckd-t2dm-001")
        assert r1.run_id != r2.run_id


class TestDemoParserTextMatching:
    def test_sglt2_ckd_text_matches_q1(self, parser: DemoQuestionParser) -> None:
        result = parser.parse("Among adults with T2DM and CKD, what is the impact of SGLT2?")
        assert result.is_supported_question is True

    def test_data_elements_text_matches_q2(self, parser: DemoQuestionParser) -> None:
        result = parser.parse("What data elements are needed to study SGLT2 initiation in CKD?")
        assert result.is_supported_question is True
        assert result.curated_question_id == "q-sglt2-ckd-data-elem-001"

    def test_outcome_text_matches_q3(self, parser: DemoQuestionParser) -> None:
        result = parser.parse(
            "How do we structure a cohort to evaluate outcomes following SGLT2 therapy?"
        )
        assert result.is_supported_question is True
        assert result.curated_question_id == "q-sglt2-ckd-outcome-eval-001"


class TestDemoParserUnsupportedQuestion:
    def test_unsupported_question_is_flagged(self, parser: DemoQuestionParser) -> None:
        result = parser.parse("What is the mortality rate of pancreatic cancer?")
        assert result.is_supported_question is False
        assert result.curated_question_id is None

    def test_unsupported_question_returns_draft_status(self, parser: DemoQuestionParser) -> None:
        result = parser.parse("Unrelated question about a different disease area")
        assert result.question.status == "draft"

    def test_unsupported_question_has_demo_placeholder_in_pico(
        self, parser: DemoQuestionParser
    ) -> None:
        result = parser.parse("Completely unrelated question")
        assert "[DEMO MODE]" in result.question.pico.population

    def test_unsupported_question_has_high_severity_flag(self, parser: DemoQuestionParser) -> None:
        result = parser.parse("Something unrelated")
        flags = result.question.ambiguity_flags
        assert len(flags) >= 1
        assert any(f.severity == "high" for f in flags)

    def test_unsupported_question_produces_warning(self, parser: DemoQuestionParser) -> None:
        result = parser.parse("What causes hypertension?")
        assert len(result.warnings) >= 1
        assert any("[DEMO MODE]" in w for w in result.warnings)


class TestQuestionService:
    def test_get_curated_questions_returns_three(self, service: QuestionService) -> None:
        questions = service.get_curated_questions()
        assert len(questions) == 3

    def test_get_curated_questions_all_approved(self, service: QuestionService) -> None:
        for q in service.get_curated_questions():
            assert q.status == "approved", f"Curated question {q.id} is not approved"

    def test_get_curated_question_by_id(self, service: QuestionService) -> None:
        q = service.get_curated_question("q-sglt2-ckd-t2dm-001")
        assert q is not None
        assert q.id == "q-sglt2-ckd-t2dm-001"

    def test_get_curated_question_unknown_id_returns_none(self, service: QuestionService) -> None:
        q = service.get_curated_question("q-does-not-exist")
        assert q is None

    def test_service_is_demo_mode(self, service: QuestionService) -> None:
        assert service.is_demo_mode is True
