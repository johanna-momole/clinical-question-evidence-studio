"""Phenotype repository — loads phenotype fixtures and resolves question→phenotype mapping."""

import json
from pathlib import Path

from src.schemas.phenotype import PhenotypeDefinition
from src.utils.exceptions import FixtureLoadError, PhenotypeNotFoundError


class PhenotypeRepository:
    """Loads phenotype definitions from fixture files and the catalog JSON."""

    def __init__(self, fixture_dir: Path, catalog_path: Path | None = None) -> None:
        self._fixture_dir = Path(fixture_dir)
        self._catalog_path = catalog_path or (self._fixture_dir / "catalog.json")
        self._phenotype_cache: dict[str, PhenotypeDefinition] = {}
        self._catalog: dict | None = None

    # ------------------------------------------------------------------
    # Phenotype loading
    # ------------------------------------------------------------------

    def load(self, phenotype_id: str) -> PhenotypeDefinition:
        """Load a phenotype by its ID. Raises PhenotypeNotFoundError if absent."""
        if phenotype_id in self._phenotype_cache:
            return self._phenotype_cache[phenotype_id]

        path = self._resolve_phenotype_path(phenotype_id)
        if not path.exists():
            raise PhenotypeNotFoundError(
                f"No phenotype fixture found for id='{phenotype_id}' at {path}"
            )

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            phenotype = PhenotypeDefinition.model_validate(data)
        except Exception as exc:
            raise FixtureLoadError(f"Failed to parse phenotype fixture {path.name}: {exc}") from exc

        self._phenotype_cache[phenotype_id] = phenotype
        return phenotype

    # ------------------------------------------------------------------
    # Catalog look-ups
    # ------------------------------------------------------------------

    def get_phenotype_id_for_question(self, question_id: str) -> str | None:
        """Return the phenotype_id associated with the given question_id, or None."""
        catalog = self._load_catalog()
        entry = catalog.get("questions", {}).get(question_id)
        if entry is None:
            return None
        return entry.get("phenotype_id")  # type: ignore[no-any-return]

    def list_question_ids(self) -> list[str]:
        """Return all question IDs registered in the catalog."""
        catalog = self._load_catalog()
        return list(catalog.get("questions", {}).keys())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_catalog(self) -> dict:
        if self._catalog is not None:
            return self._catalog
        if not self._catalog_path.exists():
            return {}
        try:
            self._catalog = json.loads(self._catalog_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise FixtureLoadError(
                f"Failed to load catalog at {self._catalog_path}: {exc}"
            ) from exc
        return self._catalog  # type: ignore[return-value]

    def _resolve_phenotype_path(self, phenotype_id: str) -> Path:
        catalog = self._load_catalog()
        entry = catalog.get("phenotypes", {}).get(phenotype_id)
        if entry:
            rel = entry.get("fixture_path", "")
            # fixture_path is relative to the project root (data/fixtures/...)
            root = self._fixture_dir.parent.parent
            candidate = root / rel
            if candidate.exists():
                return Path(candidate)
        # Fallback: look in phenotypes/ sub-dir by id
        return self._fixture_dir / f"phenotypes/{phenotype_id}.json"

    def clear_cache(self) -> None:
        self._phenotype_cache.clear()
        self._catalog = None
