"""Cohort service: orchestrates FHIR ingestion, engine execution, QA, and result storage.

All operations in this module are synthetic-data only.
"""

from __future__ import annotations

from functools import lru_cache

from src.cohorts.engine import run_cohort
from src.fhir.service import FHIRService, get_fhir_service
from src.phenotypes.service import PhenotypeService, get_phenotype_service
from src.qa.cohort_checks import run_cohort_checks
from src.qa.fhir_checks import run_fhir_checks
from src.schemas.cohort import CohortConfiguration, CohortRun
from src.schemas.phenotype import PhenotypeDefinition
from src.schemas.qa import QASummary
from src.utils.exceptions import CohortRunNotFoundError


class CohortService:
    """Orchestrates cohort runs against synthetic FHIR datasets."""

    def __init__(self, fhir_service: FHIRService, phenotype_service: PhenotypeService) -> None:
        self._fhir = fhir_service
        self._phenotype = phenotype_service
        self._runs: dict[str, CohortRun] = {}
        self._fhir_qa: dict[str, QASummary] = {}

    def run(
        self,
        phenotype: PhenotypeDefinition,
        config: CohortConfiguration,
    ) -> tuple[CohortRun, QASummary, QASummary]:
        """Execute a cohort run and return (CohortRun, FHIR QASummary, Cohort QASummary).

        Ingests the dataset (idempotent) then executes the cohort engine.
        Both phenotype gate checks and QA checks are run before returning.
        """
        # FHIR ingestion (idempotent unless force_reload)
        ingestion_result = self._fhir.ingest(config.dataset_id)
        dataset = self._fhir.get_dataset(config.dataset_id)

        # FHIR QA
        all_errors = ingestion_result.errors
        fhir_qa = run_fhir_checks(dataset, all_errors, ingestion_result.run_id)
        self._fhir_qa[ingestion_result.run_id] = fhir_qa

        # Cohort execution (may raise UnapprovedPhenotypeError or UnresolvedConceptError)
        cohort_run = run_cohort(
            phenotype=phenotype,
            config=config,
            dataset=dataset,
            fhir_run_id=ingestion_result.run_id,
        )

        # Cohort QA (patient_ids_at_steps not tracked; coh-008 reports not_applicable)
        cohort_qa = run_cohort_checks(
            cohort_run.attrition, cohort_run.run_id, cohort_run.summary.initial_population
        )

        # Persist
        self._runs[cohort_run.run_id] = cohort_run
        return cohort_run, fhir_qa, cohort_qa

    def get_run(self, run_id: str) -> CohortRun:
        run = self._runs.get(run_id)
        if run is None:
            raise CohortRunNotFoundError(f"No saved cohort run with run_id='{run_id}'")
        return run

    def get_fhir_qa(self, fhir_run_id: str) -> QASummary | None:
        return self._fhir_qa.get(fhir_run_id)

    def list_run_ids(self) -> list[str]:
        return list(self._runs.keys())

    def approve_phenotype_for_demo(self, phenotype: PhenotypeDefinition) -> PhenotypeDefinition:
        """Return a copy of the phenotype with review_status='approved' for synthetic demo use.

        This approval is ONLY for demonstrating the cohort pipeline against synthetic data.
        It does NOT certify individual terminology codes, does NOT constitute clinical validation,
        and MUST NOT be used for real patient care decisions.
        """
        return phenotype.model_copy(update={"review_status": "approved"})


@lru_cache(maxsize=1)
def get_cohort_service() -> CohortService:
    """Singleton cohort service backed by shared FHIR and phenotype service singletons."""
    return CohortService(
        fhir_service=get_fhir_service(),
        phenotype_service=get_phenotype_service(),
    )
