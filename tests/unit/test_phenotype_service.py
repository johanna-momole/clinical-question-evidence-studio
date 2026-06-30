"""Tests for phenotype repository and service."""

from pathlib import Path

import pytest

from src.phenotypes.repository import PhenotypeRepository
from src.phenotypes.service import PhenotypeService
from src.question_parser.demo_parser import DemoQuestionParser
from src.question_parser.service import QuestionService

_FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "fixtures"
_CATALOG_PATH = _FIXTURE_DIR / "catalog.json"
_PHENOTYPE_ID = "pheno-sglt2-ckd-t2dm-001"


@pytest.fixture
def repo() -> PhenotypeRepository:
    return PhenotypeRepository(fixture_dir=_FIXTURE_DIR, catalog_path=_CATALOG_PATH)


@pytest.fixture
def service(repo: PhenotypeRepository) -> PhenotypeService:
    return PhenotypeService(repo)


@pytest.fixture
def q_service() -> QuestionService:
    return QuestionService(parser=DemoQuestionParser(_FIXTURE_DIR), fixture_dir=_FIXTURE_DIR)


class TestPhenotypeRepository:
    def test_load_phenotype_by_id(self, repo: PhenotypeRepository) -> None:
        pheno = repo.load(_PHENOTYPE_ID)
        assert pheno.id == _PHENOTYPE_ID

    def test_unknown_phenotype_raises(self, repo: PhenotypeRepository) -> None:
        from src.utils.exceptions import PhenotypeNotFoundError

        with pytest.raises(PhenotypeNotFoundError):
            repo.load("pheno-does-not-exist")

    def test_get_phenotype_id_for_q1(self, repo: PhenotypeRepository) -> None:
        pid = repo.get_phenotype_id_for_question("q-sglt2-ckd-t2dm-001")
        assert pid == _PHENOTYPE_ID

    def test_get_phenotype_id_for_q2(self, repo: PhenotypeRepository) -> None:
        pid = repo.get_phenotype_id_for_question("q-sglt2-ckd-data-elem-001")
        assert pid == _PHENOTYPE_ID

    def test_get_phenotype_id_for_q3(self, repo: PhenotypeRepository) -> None:
        pid = repo.get_phenotype_id_for_question("q-sglt2-ckd-outcome-eval-001")
        assert pid == _PHENOTYPE_ID

    def test_get_phenotype_id_for_unknown_question(self, repo: PhenotypeRepository) -> None:
        pid = repo.get_phenotype_id_for_question("q-does-not-exist")
        assert pid is None

    def test_list_question_ids_has_three_entries(self, repo: PhenotypeRepository) -> None:
        ids = repo.list_question_ids()
        assert len(ids) == 3

    def test_cache_hit_returns_same_object(self, repo: PhenotypeRepository) -> None:
        p1 = repo.load(_PHENOTYPE_ID)
        p2 = repo.load(_PHENOTYPE_ID)
        assert p1 is p2  # cache hit — same object


class TestPhenotypeServiceBuildFromQuestion:
    def test_approved_q1_returns_available_phenotype(
        self, service: PhenotypeService, q_service: QuestionService
    ) -> None:
        q = q_service.get_curated_question("q-sglt2-ckd-t2dm-001")
        assert q is not None
        result = service.build_from_question(q)
        assert result.is_available is True
        assert result.phenotype is not None

    def test_approved_q2_returns_same_phenotype(
        self, service: PhenotypeService, q_service: QuestionService
    ) -> None:
        q = q_service.get_curated_question("q-sglt2-ckd-data-elem-001")
        assert q is not None
        result = service.build_from_question(q)
        assert result.is_available is True
        assert result.phenotype is not None
        assert result.phenotype.id == _PHENOTYPE_ID

    def test_draft_question_returns_unavailable(
        self, service: PhenotypeService, q_service: QuestionService
    ) -> None:
        from src.question_parser.demo_parser import DemoQuestionParser

        parser = DemoQuestionParser(_FIXTURE_DIR)
        draft_result = parser.parse("Some unrelated question")
        result = service.build_from_question(draft_result.question)
        assert result.is_available is False
        assert "approved" in (result.unavailable_reason or "").lower()

    def test_unsupported_question_id_returns_unavailable(
        self, service: PhenotypeService, q_service: QuestionService
    ) -> None:
        from src.schemas.question import ClinicalQuestion, PICOFramework

        fake_q = ClinicalQuestion(
            id="q-fake-question-001",
            raw_question="Fake question",
            pico=PICOFramework(
                population="Adults",
                intervention="Some drug",
                outcomes=["Some outcome"],
            ),
            status="approved",
            source="user_input",
        )
        result = service.build_from_question(fake_q)
        assert result.is_available is False

    def test_result_includes_run_id(
        self, service: PhenotypeService, q_service: QuestionService
    ) -> None:
        q = q_service.get_curated_question("q-sglt2-ckd-t2dm-001")
        assert q is not None
        result = service.build_from_question(q)
        assert result.run_id
        assert len(result.run_id) == 36  # UUID format


class TestPhenotypeServiceValidation:
    def test_validate_warns_about_llm_suggested_unverified(
        self, service: PhenotypeService, repo: PhenotypeRepository
    ) -> None:
        pheno = repo.load(_PHENOTYPE_ID)
        warnings = service.validate_phenotype(pheno)
        # Should warn about the 4 unverified LLM-suggested RxNorm codes
        llm_warnings = [w for w in warnings if "LLM-suggested" in w]
        assert len(llm_warnings) >= 4

    def test_validate_warns_all_candidate(
        self, service: PhenotypeService, repo: PhenotypeRepository
    ) -> None:
        pheno = repo.load(_PHENOTYPE_ID)
        warnings = service.validate_phenotype(pheno)
        candidate_warnings = [w for w in warnings if "candidate" in w.lower()]
        assert len(candidate_warnings) >= 1


class TestPhenotypeAuditRecord:
    def test_record_audit_returns_valid_record(self, service: PhenotypeService) -> None:
        record = service.record_audit(
            phenotype_id=_PHENOTYPE_ID,
            phenotype_version="0.2.0",
            field_path="concepts[0].mappings[0].review_status",
            previous_value="candidate",
            new_value="approved",
            change_type="mapping_review",
            changed_by="user",
            notes="Verified E11.9 against ICD-10-CM FY2024 tabular",
        )
        assert record.phenotype_id == _PHENOTYPE_ID
        assert record.change_type == "mapping_review"
        assert record.changed_by == "user"
        assert '"candidate"' in (record.previous_value_json or "")
        assert '"approved"' in (record.new_value_json or "")
