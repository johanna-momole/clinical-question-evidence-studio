"""Terminology service — facade used by FastAPI routes and Streamlit pages."""

from functools import lru_cache
from pathlib import Path

from src.schemas.phenotype import ClinicalConcept, TerminologyMapping
from src.terminology import mapper as _mapper
from src.terminology.repository import TerminologyRepository


class TerminologyService:
    """Combines the repository (I/O) with mapper functions (pure logic)."""

    def __init__(self, repository: TerminologyRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Concept / mapping access
    # ------------------------------------------------------------------

    def get_concepts(self, phenotype_id: str) -> list[ClinicalConcept]:
        return self._repo.get_concepts(phenotype_id)

    def get_all_mappings(self, phenotype_id: str) -> list[TerminologyMapping]:
        return self._repo.get_all_mappings(phenotype_id)

    def get_mappings_for_concept(
        self, phenotype_id: str, concept_id: str
    ) -> list[TerminologyMapping]:
        return self._repo.get_mappings_for_concept(phenotype_id, concept_id)

    # ------------------------------------------------------------------
    # Filtered views
    # ------------------------------------------------------------------

    def get_candidate_mappings(self, phenotype_id: str) -> list[TerminologyMapping]:
        return _mapper.filter_by_review_status(self.get_all_mappings(phenotype_id), "candidate")

    def get_llm_suggested_mappings(self, phenotype_id: str) -> list[TerminologyMapping]:
        return _mapper.filter_llm_suggested(self.get_all_mappings(phenotype_id))

    def get_unverified_mappings(self, phenotype_id: str) -> list[TerminologyMapping]:
        return _mapper.filter_unverified(self.get_all_mappings(phenotype_id))

    def get_mappings_by_system(self, phenotype_id: str, system: str) -> list[TerminologyMapping]:
        return _mapper.filter_by_system(self.get_all_mappings(phenotype_id), system)

    # ------------------------------------------------------------------
    # Grouped views
    # ------------------------------------------------------------------

    def group_by_concept(self, phenotype_id: str) -> dict[str, list[TerminologyMapping]]:
        return _mapper.group_by_concept(self.get_all_mappings(phenotype_id))

    def group_by_system(self, phenotype_id: str) -> dict[str, list[TerminologyMapping]]:
        return _mapper.group_by_system(self.get_all_mappings(phenotype_id))

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def review_completeness_pct(self, phenotype_id: str) -> float:
        return _mapper.review_completeness_pct(self.get_all_mappings(phenotype_id))

    def candidate_count(self, phenotype_id: str) -> int:
        return _mapper.candidate_count(self.get_all_mappings(phenotype_id))

    def approved_count(self, phenotype_id: str) -> int:
        return _mapper.approved_count(self.get_all_mappings(phenotype_id))


@lru_cache(maxsize=1)
def get_terminology_service() -> TerminologyService:
    """Singleton factory — call from FastAPI dependencies and Streamlit pages."""
    from src.config.settings import get_settings

    settings = get_settings()
    repo = TerminologyRepository(Path(settings.fixtures_dir))
    return TerminologyService(repo)
