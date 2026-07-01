"""Evidence service: orchestrates the full retrieval pipeline.

Pipeline steps:
  1. Build a deterministic EvidenceQuery (gated on approved question + phenotype)
  2. Dispatch to source adapters (via evidence_sources.service)
  3. Normalize raw records
  4. Deduplicate within each source
  5. Metatag all records
  6. Rank by deterministic relevance score
  7. Run QA checks (record-level + retrieval-level)
  8. Persist everything to the EvidenceRepository
  9. Return the completed RetrievalRun

All steps are deterministic — the same inputs always produce the same outputs.
No LLM is invoked at any point in this service.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache

from src.evidence.deduplication import deduplicate
from src.evidence.metatagging import tag_records
from src.evidence.normalizer import normalize_records
from src.evidence.query_builder import build_query
from src.evidence.ranking import rank_records
from src.evidence.repository import EvidenceRepository, get_evidence_repository
from src.evidence_sources.service import fetch_all_sources
from src.qa.evidence_checks import run_evidence_record_checks
from src.qa.retrieval_checks import run_retrieval_checks
from src.schemas.phenotype import PhenotypeDefinition
from src.schemas.question import ClinicalQuestion
from src.schemas.retrieval import (
    EvidenceQuery,
    EvidenceSourceStatus,
    RetrievalProvenance,
    RetrievalRequest,
    RetrievalRun,
)


class EvidenceService:
    """Orchestrates the full evidence retrieval pipeline."""

    def __init__(self, repository: EvidenceRepository) -> None:
        self._repo = repository

    def run(
        self,
        question: ClinicalQuestion,
        phenotype: PhenotypeDefinition,
        sources: list | None = None,
        max_results_per_source: int = 50,
        offline_only: bool = True,
        max_evidence_age_days: int = 1825,
    ) -> RetrievalRun:
        """Execute the full evidence retrieval pipeline and return the completed RetrievalRun.

        Raises ApprovalRequiredError or UnapprovedPhenotypeError if gates are not met.
        """
        from src.schemas.evidence import EvidenceSourceName

        default_sources: list[EvidenceSourceName] = [
            "pubmed",
            "clinical_trials_gov",
            "cms_coverage",
        ]
        active_sources: list[EvidenceSourceName] = sources or default_sources

        started_at = datetime.now(UTC)
        run_id = str(uuid.uuid4())

        # Step 1: Build query (raises if gates not met)
        query: EvidenceQuery = build_query(question, phenotype)

        request = RetrievalRequest(
            query_id=query.id,
            sources=active_sources,
            offline_only=offline_only,
            max_results_per_source=max_results_per_source,
        )

        # Step 2: Fetch raw records from adapters
        raw_records, source_statuses = fetch_all_sources(
            source_queries=query.source_queries,
            run_id=run_id,
            max_results_per_source=max_results_per_source,
        )

        # Extract fixture manifest versions for provenance
        fixture_versions: dict[str, str] = {}
        for ss in source_statuses:
            records_for_source = [r for r in raw_records if r.source_name == ss.source_name]
            if records_for_source:
                v = records_for_source[0].fixture_manifest_version
                if v:
                    fixture_versions[ss.source_name] = v

        provenance = RetrievalProvenance(
            run_id=run_id,
            query_hash=query.query_hash,
            retrieval_mode="offline_fixture" if offline_only else "live",
            sources_queried=active_sources,
            fixture_manifest_versions=fixture_versions,
        )

        # Step 3: Normalize
        normalized = normalize_records(raw_records, run_id)

        # Update source statuses with post-normalization counts
        norm_count_by_source: dict[str, int] = {}
        for rec in normalized:
            if rec.source_name:
                norm_count_by_source[rec.source_name] = (
                    norm_count_by_source.get(rec.source_name, 0) + 1
                )
        updated_statuses: list[EvidenceSourceStatus] = []
        for ss in source_statuses:
            updated_statuses.append(
                EvidenceSourceStatus(
                    source_name=ss.source_name,
                    records_retrieved=ss.records_retrieved,
                    records_after_normalization=norm_count_by_source.get(ss.source_name, 0),
                    errors=ss.errors,
                    cache_hit=ss.cache_hit,
                    duration_ms=ss.duration_ms,
                )
            )

        # Step 4: Deduplicate
        deduped, dedup_result = deduplicate(normalized, run_id)

        # Step 5: Metatag
        tagged = tag_records(deduped)

        # Step 6: Rank
        ranked = rank_records(tagged, query)

        # Step 7: QA
        evidence_qa = run_evidence_record_checks(
            ranked, run_id, max_evidence_age_days=max_evidence_age_days
        )

        run = RetrievalRun(
            run_id=run_id,
            query=query,
            request=request,
            provenance=provenance,
            source_statuses=updated_statuses,
            total_records_retrieved=len(raw_records),
            total_records_after_dedup=len(deduped),
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )

        retrieval_qa = run_retrieval_checks(run)

        # Step 8: Persist
        self._repo.save_run(
            run=run,
            raw_records=raw_records,
            normalized_records=ranked,
            dedup_result=dedup_result,
            evidence_qa=evidence_qa,
            retrieval_qa=retrieval_qa,
        )

        return run

    def get_run(self, run_id: str) -> dict:
        return self._repo.get_run(run_id)

    def get_run_as_dict(self, run_id: str) -> dict:
        """Return run data shaped for EvidenceBriefService.generate().

        Keys: run_id, query_hash, records (list[dict]), source_statuses (dict[str,str]).
        """
        run_row = self._repo.get_run(run_id)
        records = self._repo.list_evidence_for_run(run_id)
        raw_source_statuses = self._repo.source_coverage(run_id)
        # Derive ok/failed per source: if retrieved > 0 → ok, else → empty
        source_statuses = {
            src: ("ok" if count > 0 else "empty")
            for src, count in raw_source_statuses.items()
        }
        return {
            "run_id": run_id,
            "query_hash": run_row.get("query_hash", ""),
            "records": records,
            "source_statuses": source_statuses,
            "qa_summary": {},
        }

    def list_run_ids(self) -> list[str]:
        return self._repo.list_run_ids()

    def get_evidence(self, evidence_id: str) -> dict:
        return self._repo.get_evidence_record(evidence_id)

    def search_evidence(
        self,
        run_id: str,
        source_type: str | None = None,
        min_score: float | None = None,
        tags: list[str] | None = None,
    ) -> list[dict]:
        return self._repo.list_evidence_for_run(run_id, source_type, min_score, tags)

    def get_evidence_qa(self, run_id: str) -> list[dict]:
        return self._repo.get_evidence_qa(run_id)

    def get_retrieval_qa(self, run_id: str) -> list[dict]:
        return self._repo.get_retrieval_qa(run_id)


@lru_cache(maxsize=1)
def get_evidence_service() -> EvidenceService:
    return EvidenceService(repository=get_evidence_repository())
