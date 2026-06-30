"""Phenotype service — builds and validates PhenotypeResult from an approved question."""

import json
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from src.phenotypes.repository import PhenotypeRepository
from src.schemas.parsing import PhenotypeAuditRecord, PhenotypeResult
from src.schemas.phenotype import PhenotypeDefinition
from src.schemas.question import ClinicalQuestion
from src.utils.exceptions import PhenotypeNotFoundError


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PhenotypeService:
    """Resolves questions to phenotype fixtures and validates phenotype structure."""

    def __init__(self, repository: PhenotypeRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Core operation
    # ------------------------------------------------------------------

    def build_from_question(self, question: ClinicalQuestion) -> PhenotypeResult:
        """Return the phenotype for an approved question.

        Returns PhenotypeResult(is_available=False) when:
        - the question is in draft status
        - no phenotype is mapped to this question_id in the catalog
        """
        run_id = str(uuid.uuid4())

        if question.status != "approved":
            return PhenotypeResult(
                run_id=run_id,
                phenotype=None,
                is_available=False,
                unavailable_reason=(
                    f"Question '{question.id}' has status '{question.status}'. "
                    "A question must be approved before a phenotype can be loaded."
                ),
                warnings=["Approve the question on the Question Builder page before proceeding."],
            )

        phenotype_id = self._repo.get_phenotype_id_for_question(question.id)
        if phenotype_id is None:
            return PhenotypeResult(
                run_id=run_id,
                phenotype=None,
                is_available=False,
                unavailable_reason=(
                    f"No phenotype is mapped to question '{question.id}' in the demo catalog. "
                    "Only the three curated SGLT2/T2DM/CKD questions have associated phenotypes."
                ),
                warnings=[
                    "[DEMO MODE] Phenotype unavailable for this question. "
                    "Select a curated demo question to view a phenotype."
                ],
            )

        try:
            phenotype = self._repo.load(phenotype_id)
        except PhenotypeNotFoundError as exc:
            return PhenotypeResult(
                run_id=run_id,
                phenotype=None,
                is_available=False,
                unavailable_reason=str(exc),
                warnings=["Phenotype fixture file is missing — check data/fixtures/."],
            )

        warnings = self.validate_phenotype(phenotype)
        return PhenotypeResult(  # type: ignore[call-arg]  # pydantic Field defaults opaque via __future__ annotations
            run_id=run_id,
            phenotype=phenotype,
            is_available=True,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_phenotype(self, phenotype: PhenotypeDefinition) -> list[str]:
        """Return a list of warning strings for common phenotype issues."""
        warnings: list[str] = []

        # Unverified RxNorm codes
        for concept in phenotype.concepts:
            for m in concept.mappings:
                if m.is_llm_suggested and m.verification_date is None:
                    warnings.append(
                        f"Mapping [{m.terminology_system}] {m.code} ({m.concept_name}) "
                        f"is LLM-suggested and has not been verified against an authoritative source."
                    )

        # All-candidate phenotype (none approved)
        all_mappings = [m for c in phenotype.concepts for m in c.mappings]
        if all_mappings and all(m.review_status == "candidate" for m in all_mappings):
            warnings.append(
                "All terminology mappings are in 'candidate' status. "
                "At least one mapping must be reviewed before this phenotype can be used in production."
            )

        # Inclusion rule concept cross-references
        concept_ids = {c.concept_id for c in phenotype.concepts}
        for rule in phenotype.inclusion_rules + phenotype.exclusion_rules:
            if rule.concept_id not in concept_ids:
                warnings.append(
                    f"Rule '{rule.rule_id}' references concept_id '{rule.concept_id}' "
                    f"which does not exist in phenotype.concepts."
                )

        return warnings

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------

    def record_audit(
        self,
        phenotype_id: str,
        phenotype_version: str,
        field_path: str,
        previous_value: object,
        new_value: object,
        change_type: str,
        changed_by: str = "user",
        notes: str | None = None,
    ) -> PhenotypeAuditRecord:
        return PhenotypeAuditRecord(
            audit_id=str(uuid.uuid4()),
            phenotype_id=phenotype_id,
            phenotype_version=phenotype_version,
            field_path=field_path,
            previous_value_json=(
                json.dumps(previous_value) if previous_value is not None else None
            ),
            new_value_json=json.dumps(new_value) if new_value is not None else None,
            change_type=change_type,  # type: ignore[arg-type]
            changed_by=changed_by,  # type: ignore[arg-type]
            notes=notes,
        )


@lru_cache(maxsize=1)
def get_phenotype_service() -> PhenotypeService:
    """Singleton factory — call from FastAPI dependencies and Streamlit pages."""
    from src.config.settings import get_settings

    settings = get_settings()
    fixture_dir = Path(settings.fixtures_dir)
    catalog_path = fixture_dir / "catalog.json"
    repo = PhenotypeRepository(fixture_dir=fixture_dir, catalog_path=catalog_path)
    return PhenotypeService(repo)
