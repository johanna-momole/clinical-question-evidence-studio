"""Tests for terminology repository, mapper, and service."""

from pathlib import Path

import pytest

from src.terminology import mapper as m
from src.terminology.repository import TerminologyRepository
from src.terminology.service import TerminologyService

_FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "fixtures"
_PHENOTYPE_ID = "pheno-sglt2-ckd-t2dm-001"


@pytest.fixture
def repo() -> TerminologyRepository:
    return TerminologyRepository(_FIXTURE_DIR)


@pytest.fixture
def service(repo: TerminologyRepository) -> TerminologyService:
    return TerminologyService(repo)


class TestTerminologyRepository:
    def test_load_phenotype_succeeds(self, repo: TerminologyRepository) -> None:
        pheno = repo.load_phenotype(_PHENOTYPE_ID)
        assert pheno.id == _PHENOTYPE_ID

    def test_get_all_mappings_not_empty(self, repo: TerminologyRepository) -> None:
        mappings = repo.get_all_mappings(_PHENOTYPE_ID)
        assert len(mappings) >= 14

    def test_get_concepts_count(self, repo: TerminologyRepository) -> None:
        concepts = repo.get_concepts(_PHENOTYPE_ID)
        assert len(concepts) == 7

    def test_get_mappings_for_known_concept(self, repo: TerminologyRepository) -> None:
        mappings = repo.get_mappings_for_concept(_PHENOTYPE_ID, "c-sglt2")
        assert len(mappings) >= 4  # 4 SGLT2 inhibitors

    def test_get_mappings_for_unknown_concept_returns_empty(
        self, repo: TerminologyRepository
    ) -> None:
        result = repo.get_mappings_for_concept(_PHENOTYPE_ID, "c-nonexistent")
        assert result == []

    def test_unknown_phenotype_raises_fixture_load_error(self, repo: TerminologyRepository) -> None:
        from src.utils.exceptions import FixtureLoadError

        with pytest.raises(FixtureLoadError):
            repo.load_phenotype("pheno-does-not-exist")


class TestTerminologyMapper:
    def test_group_by_concept_keys(self, repo: TerminologyRepository) -> None:
        mappings = repo.get_all_mappings(_PHENOTYPE_ID)
        grouped = m.group_by_concept(mappings)
        assert "c-t2dm" in grouped
        assert "c-ckd" in grouped
        assert "c-sglt2" in grouped
        assert "c-egfr" in grouped

    def test_group_by_system_keys(self, repo: TerminologyRepository) -> None:
        mappings = repo.get_all_mappings(_PHENOTYPE_ID)
        grouped = m.group_by_system(mappings)
        assert "ICD-10-CM" in grouped
        assert "RxNorm" in grouped
        assert "LOINC" in grouped

    def test_filter_by_system_icd10(self, repo: TerminologyRepository) -> None:
        mappings = repo.get_all_mappings(_PHENOTYPE_ID)
        icd = m.filter_by_system(mappings, "ICD-10-CM")
        assert all(x.terminology_system == "ICD-10-CM" for x in icd)

    def test_filter_by_review_status_candidate(self, repo: TerminologyRepository) -> None:
        mappings = repo.get_all_mappings(_PHENOTYPE_ID)
        candidates = m.filter_by_review_status(mappings, "candidate")
        assert len(candidates) == len(mappings)  # all are candidate in the fixture

    def test_filter_unverified_returns_all(self, repo: TerminologyRepository) -> None:
        mappings = repo.get_all_mappings(_PHENOTYPE_ID)
        unverified = m.filter_unverified(mappings)
        # All current fixtures have verification_date=None
        assert len(unverified) == len(mappings)

    def test_filter_llm_suggested_returns_rxnorm_only(self, repo: TerminologyRepository) -> None:
        mappings = repo.get_all_mappings(_PHENOTYPE_ID)
        llm = m.filter_llm_suggested(mappings)
        assert len(llm) == 4  # exactly the 4 RxNorm codes
        assert all(x.terminology_system == "RxNorm" for x in llm)

    def test_review_completeness_is_zero(self, repo: TerminologyRepository) -> None:
        mappings = repo.get_all_mappings(_PHENOTYPE_ID)
        pct = m.review_completeness_pct(mappings)
        assert pct == 0.0  # nothing reviewed yet

    def test_candidate_count_equals_total(self, repo: TerminologyRepository) -> None:
        mappings = repo.get_all_mappings(_PHENOTYPE_ID)
        assert m.candidate_count(mappings) == len(mappings)

    def test_approved_count_is_zero(self, repo: TerminologyRepository) -> None:
        mappings = repo.get_all_mappings(_PHENOTYPE_ID)
        assert m.approved_count(mappings) == 0


class TestTerminologyService:
    def test_get_concepts_count(self, service: TerminologyService) -> None:
        concepts = service.get_concepts(_PHENOTYPE_ID)
        assert len(concepts) == 7

    def test_get_all_mappings_not_empty(self, service: TerminologyService) -> None:
        mappings = service.get_all_mappings(_PHENOTYPE_ID)
        assert len(mappings) >= 14

    def test_get_mappings_by_system_rxnorm(self, service: TerminologyService) -> None:
        rx = service.get_mappings_by_system(_PHENOTYPE_ID, "RxNorm")
        assert len(rx) == 4

    def test_get_llm_suggested_mappings(self, service: TerminologyService) -> None:
        llm = service.get_llm_suggested_mappings(_PHENOTYPE_ID)
        assert len(llm) == 4

    def test_get_unverified_mappings(self, service: TerminologyService) -> None:
        unverified = service.get_unverified_mappings(_PHENOTYPE_ID)
        assert len(unverified) > 0

    def test_review_completeness_pct(self, service: TerminologyService) -> None:
        pct = service.review_completeness_pct(_PHENOTYPE_ID)
        assert pct == 0.0

    def test_candidate_count(self, service: TerminologyService) -> None:
        count = service.candidate_count(_PHENOTYPE_ID)
        assert count > 0

    def test_group_by_concept_includes_all(self, service: TerminologyService) -> None:
        grouped = service.group_by_concept(_PHENOTYPE_ID)
        assert "c-t2dm" in grouped
        assert "c-sglt2" in grouped
