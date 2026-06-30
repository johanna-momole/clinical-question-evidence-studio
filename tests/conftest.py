"""Pytest configuration and shared fixtures."""

import json
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path for imports when not installed
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_FIXTURES_DIR = _PROJECT_ROOT / "data" / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return _FIXTURES_DIR


# ── Q1 (original) ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def question_fixture_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "questions" / "sglt2_ckd_t2dm.json"


@pytest.fixture(scope="session")
def phenotype_fixture_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "phenotypes" / "sglt2_ckd_t2dm_phenotype.json"


@pytest.fixture(scope="session")
def raw_question_fixture(question_fixture_path: Path) -> dict:  # type: ignore[type-arg]
    with question_fixture_path.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def raw_phenotype_fixture(phenotype_fixture_path: Path) -> dict:  # type: ignore[type-arg]
    with phenotype_fixture_path.open(encoding="utf-8") as f:
        return json.load(f)


# ── Q2 (data elements) ─────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def q2_fixture_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "questions" / "sglt2_ckd_data_elements.json"


@pytest.fixture(scope="session")
def raw_q2_fixture(q2_fixture_path: Path) -> dict:  # type: ignore[type-arg]
    with q2_fixture_path.open(encoding="utf-8") as f:
        return json.load(f)


# ── Q3 (outcome evaluation) ────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def q3_fixture_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "questions" / "sglt2_ckd_outcome_eval.json"


@pytest.fixture(scope="session")
def raw_q3_fixture(q3_fixture_path: Path) -> dict:  # type: ignore[type-arg]
    with q3_fixture_path.open(encoding="utf-8") as f:
        return json.load(f)


# ── Catalog ────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def catalog_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "catalog.json"


@pytest.fixture(scope="session")
def raw_catalog(catalog_path: Path) -> dict:  # type: ignore[type-arg]
    with catalog_path.open(encoding="utf-8") as f:
        return json.load(f)
