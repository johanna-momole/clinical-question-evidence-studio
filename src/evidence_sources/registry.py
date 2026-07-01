"""Registry of all registered evidence source adapters.

Import ``get_adapter`` to retrieve an adapter by source name; call
``list_sources`` to enumerate all registered source names.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.evidence_sources.base import EvidenceSourceAdapter
from src.evidence_sources.clinical_trials import ClinicalTrialsAdapter
from src.evidence_sources.cms_coverage import CMSCoverageAdapter
from src.evidence_sources.pubmed import PubMedAdapter
from src.evidence_sources.rxnorm import RxNormAdapter
from src.schemas.evidence import EvidenceSourceName
from src.utils.exceptions import UnsupportedSourceError

_FIXTURE_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "fixtures" / "evidence"


@lru_cache(maxsize=1)
def _build_registry() -> dict[EvidenceSourceName, EvidenceSourceAdapter]:
    return {
        "pubmed": PubMedAdapter(fixture_dir=_FIXTURE_ROOT / "pubmed"),
        "clinical_trials_gov": ClinicalTrialsAdapter(fixture_dir=_FIXTURE_ROOT / "clinical_trials"),
        "cms_coverage": CMSCoverageAdapter(fixture_dir=_FIXTURE_ROOT / "cms_coverage"),
    }


def get_adapter(source_name: EvidenceSourceName) -> EvidenceSourceAdapter:
    registry = _build_registry()
    adapter = registry.get(source_name)
    if adapter is None:
        raise UnsupportedSourceError(
            f"No adapter registered for source '{source_name}'. Available: {list(registry.keys())}"
        )
    return adapter


def get_rxnorm_adapter() -> RxNormAdapter:
    return RxNormAdapter(fixture_dir=_FIXTURE_ROOT / "rxnorm")


def list_sources() -> list[EvidenceSourceName]:
    return list(_build_registry().keys())
