"""Utility script to regenerate or validate fixture files from Python schema objects.

Usage:
    python scripts/generate_fixtures.py           # validate fixtures
    python scripts/generate_fixtures.py --regen   # regenerate JSON from code
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is importable
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.schemas.phenotype import PhenotypeDefinition
from src.schemas.question import ClinicalQuestion


def validate_fixtures() -> bool:
    """Load all fixtures and validate them against their schemas. Return True if all pass."""
    errors: list[str] = []
    fixtures: dict[str, tuple[Path, type]] = {
        "question-q1": (
            _ROOT / "data/fixtures/questions/sglt2_ckd_t2dm.json",
            ClinicalQuestion,
        ),
        "question-q2": (
            _ROOT / "data/fixtures/questions/sglt2_ckd_data_elements.json",
            ClinicalQuestion,
        ),
        "question-q3": (
            _ROOT / "data/fixtures/questions/sglt2_ckd_outcome_eval.json",
            ClinicalQuestion,
        ),
        "phenotype": (
            _ROOT / "data/fixtures/phenotypes/sglt2_ckd_t2dm_phenotype.json",
            PhenotypeDefinition,
        ),
    }
    for name, (path, model_cls) in fixtures.items():
        if not path.exists():
            errors.append(f"MISSING: {path}")
            continue
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
            obj = model_cls.model_validate(data)
            print(f"  OK  {name}: {path.name} ({type(obj).__name__})")
        except Exception as exc:
            errors.append(f"INVALID {name} ({path.name}): {exc}")

    # Validate catalog
    catalog_path = _ROOT / "data/fixtures/catalog.json"
    if not catalog_path.exists():
        errors.append(f"MISSING: {catalog_path}")
    else:
        try:
            with catalog_path.open(encoding="utf-8") as f:
                catalog = json.load(f)
            q_count = len(catalog.get("questions", {}))
            p_count = len(catalog.get("phenotypes", {}))
            print(f"  OK  catalog: {catalog_path.name} ({q_count} questions, {p_count} phenotypes)")
        except Exception as exc:
            errors.append(f"INVALID catalog: {exc}")

    if errors:
        for err in errors:
            print(f"  ERR {err}", file=sys.stderr)
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate or regenerate fixture files")
    parser.add_argument(
        "--regen", action="store_true", help="Regenerate fixtures (not implemented in Phase 2)"
    )
    args = parser.parse_args()

    if args.regen:
        print("Fixture regeneration is not implemented yet.")
        print("Edit data/fixtures/ JSON files directly, then run without --regen to validate.")
        sys.exit(0)

    print("Validating fixture files...")
    ok = validate_fixtures()
    if ok:
        print("\nAll fixtures are valid.")
    else:
        print("\nFixture validation failed — see errors above.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
