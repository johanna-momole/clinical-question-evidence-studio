"""Terminology repository — loads phenotype fixture files and exposes raw mappings."""

import json
from pathlib import Path

from src.schemas.phenotype import ClinicalConcept, PhenotypeDefinition, TerminologyMapping
from src.utils.exceptions import FixtureLoadError


class TerminologyRepository:
    """Loads and caches phenotype definitions to serve terminology lookups."""

    def __init__(self, fixture_dir: Path) -> None:
        self._fixture_dir = Path(fixture_dir)
        self._cache: dict[str, PhenotypeDefinition] = {}

    # ------------------------------------------------------------------
    # Phenotype loading
    # ------------------------------------------------------------------

    def load_phenotype(self, phenotype_id: str) -> PhenotypeDefinition:
        """Load a phenotype fixture by ID. Results are cached in-process."""
        if phenotype_id in self._cache:
            return self._cache[phenotype_id]

        path = self._resolve_path(phenotype_id)
        if not path.exists():
            raise FixtureLoadError(f"Phenotype fixture not found: {path}")

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            phenotype = PhenotypeDefinition.model_validate(data)
        except Exception as exc:
            raise FixtureLoadError(f"Failed to parse phenotype fixture {path.name}: {exc}") from exc

        self._cache[phenotype_id] = phenotype
        return phenotype

    # ------------------------------------------------------------------
    # Mapping accessors
    # ------------------------------------------------------------------

    def get_all_mappings(self, phenotype_id: str) -> list[TerminologyMapping]:
        """Return all terminology mappings across all concepts in the phenotype."""
        phenotype = self.load_phenotype(phenotype_id)
        mappings: list[TerminologyMapping] = []
        for concept in phenotype.concepts:
            mappings.extend(concept.mappings)
        return mappings

    def get_concepts(self, phenotype_id: str) -> list[ClinicalConcept]:
        """Return all ClinicalConcept objects for the phenotype."""
        return self.load_phenotype(phenotype_id).concepts

    def get_mappings_for_concept(
        self, phenotype_id: str, concept_id: str
    ) -> list[TerminologyMapping]:
        """Return mappings for a single concept within the phenotype."""
        concepts = self.get_concepts(phenotype_id)
        for c in concepts:
            if c.concept_id == concept_id:
                return list(c.mappings)
        return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_path(self, phenotype_id: str) -> Path:
        _FIXTURE_MAP: dict[str, str] = {
            "pheno-sglt2-ckd-t2dm-001": "phenotypes/sglt2_ckd_t2dm_phenotype.json",
        }
        rel = _FIXTURE_MAP.get(phenotype_id)
        if rel is None:
            # Fall back to a filename derived from the ID
            rel = f"phenotypes/{phenotype_id}.json"
        return self._fixture_dir / rel

    def clear_cache(self) -> None:
        """Evict in-process cache — useful for tests."""
        self._cache.clear()
