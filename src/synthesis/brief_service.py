"""BriefService: 8-step pipeline for evidence brief generation.

Pipeline steps:
  1. Verify evidence retrieval run exists
  2. Build immutable evidence snapshot
  3. Gate: clinical-safety checks (no recommendation language can proceed)
  4. Run selected generator (deterministic or live_llm)
  5. Resolve citations to numbered ClaimCitations
  6. Generate deterministic limitations
  7. Run all BQ-001–BQ-016 QA checks; fail on critical errors
  8. Persist brief, snapshot, QA results, and audit log entry

All live LLM generation is gated behind generation_mode='live_llm' and
requires an injected llm_client; the default mode is 'deterministic'.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from src.qa.brief_checks import has_critical_failures, run_brief_checks
from src.schemas.brief import (
    BriefGenerationResult,
    BriefProvenance,
    DataOriginClass,
    EvidenceBrief,
    EvidenceSnapshot,
    GenerationMode,
    _default_data_notice,
)
from src.synthesis.citation_resolver import resolve_citations
from src.synthesis.deterministic_generator import (
    generate_deterministic,
)
from src.synthesis.evidence_snapshot import build_snapshot
from src.synthesis.limitations import generate_limitations
from src.synthesis.repository import get_synthesis_repository
from src.utils.exceptions import (
    BriefGenerationError,
    CriticalQABlockError,
)

# ---------------------------------------------------------------------------
# Gate 1: evidence run compatibility
# ---------------------------------------------------------------------------

_REQUIRED_EVIDENCE_FIELDS = ("run_id", "records", "source_statuses", "query_hash")


def _validate_evidence_run(run_data: dict[str, Any]) -> None:
    for field in _REQUIRED_EVIDENCE_FIELDS:
        if field not in run_data:
            raise BriefGenerationError(
                f"Evidence run missing required field: {field!r}. Run a retrieval pipeline first."
            )
    if not run_data.get("records"):
        raise BriefGenerationError(
            "Evidence retrieval run returned zero records. "
            "Cannot generate a brief without evidence."
        )


# ---------------------------------------------------------------------------
# Gate 2: snapshot pre-generation QA
# ---------------------------------------------------------------------------


def _gate_snapshot(snapshot: EvidenceSnapshot) -> list[str]:
    """Return warning list. Does not raise — warnings are captured in the result."""
    warnings: list[str] = []
    failed = [sn for sn, st in snapshot.source_statuses.items() if st == "failed"]
    if failed:
        warnings.append(
            f"Evidence snapshot: {len(failed)} source(s) failed during retrieval: {failed}. "
            "Brief may have incomplete coverage."
        )
    if not snapshot.records:
        raise BriefGenerationError("Snapshot contains zero records after building.")
    return warnings


# ---------------------------------------------------------------------------
# Data-origin / data-notice helpers
# ---------------------------------------------------------------------------


def _build_data_notice(snapshot: EvidenceSnapshot, data_origin: DataOriginClass) -> str:
    """Generate an accurate data notice from per-record origin classification."""
    origin_counts: dict[DataOriginClass, int] = {}
    for rec in snapshot.records:
        origin_counts[rec.data_origin] = origin_counts.get(rec.data_origin, 0) + 1

    if len(origin_counts) == 1:
        sole = next(iter(origin_counts))
        return _default_data_notice(sole)

    parts = []
    if origin_counts.get("live_api"):
        parts.append(f"{origin_counts['live_api']} live API records")
    if origin_counts.get("captured_source_fixture"):
        parts.append(f"{origin_counts['captured_source_fixture']} captured public-source records")
    if origin_counts.get("manually_constructed_fixture"):
        parts.append(f"{origin_counts['manually_constructed_fixture']} demonstration fixtures")
    if not parts:
        return _default_data_notice(data_origin)
    return (
        "Brief generated from a combination of "
        + ", ".join(parts)
        + ". Record-level provenance identifies each origin."
    )


# ---------------------------------------------------------------------------
# Core service
# ---------------------------------------------------------------------------


class EvidenceBriefService:
    """Orchestrates the 8-step brief generation pipeline."""

    def __init__(
        self,
        question_id: str = "q-sglt2-ckd-cvd",
        phenotype_id: str = "pheno-sglt2",
        phenotype_version: str = "1.0.0",
        cohort_run_id: str | None = None,
        llm_client: Any | None = None,
    ) -> None:
        self._question_id = question_id
        self._phenotype_id = phenotype_id
        self._phenotype_version = phenotype_version
        self._cohort_run_id = cohort_run_id
        self._llm_client = llm_client
        self._repo = get_synthesis_repository()

    # ------------------------------------------------------------------
    # Step 1+2: validate run + build snapshot
    # ------------------------------------------------------------------

    def _step_build_snapshot(
        self,
        run_data: dict[str, Any],
    ) -> tuple[EvidenceSnapshot, list[str]]:
        _validate_evidence_run(run_data)
        snapshot = build_snapshot(
            raw_dicts=run_data["records"],
            retrieval_run_id=run_data["run_id"],
            query_hash=run_data.get("query_hash", ""),
            source_statuses=run_data.get("source_statuses", {}),
            qa_summary=run_data.get("qa_summary", {}),
        )
        warnings = _gate_snapshot(snapshot)
        return snapshot, warnings

    # ------------------------------------------------------------------
    # Steps 4+5+6: generate, resolve citations, build limitations
    # ------------------------------------------------------------------

    def _step_generate(
        self,
        snapshot: EvidenceSnapshot,
        evidence_run_id: str,
        generation_mode: GenerationMode,
        question_text: str,
    ) -> tuple[Any, Any, str, str | None, str | None]:
        """Returns (claims, gaps, prompt_version, model_provider, model_name)."""
        if generation_mode == "deterministic":
            claims, gaps, pv = generate_deterministic(snapshot, evidence_run_id)
            return claims, gaps, pv, None, None
        elif generation_mode == "live_llm":
            if self._llm_client is None:
                raise BriefGenerationError(
                    "generation_mode='live_llm' requires an llm_client to be injected."
                )
            from src.synthesis.llm_generator import generate_live_llm

            claims, gaps, pv, provider, model = generate_live_llm(
                snapshot, question_text, evidence_run_id, self._llm_client
            )
            return claims, gaps, pv, provider, model
        else:
            raise BriefGenerationError(f"Unknown generation_mode: {generation_mode!r}")

    # ------------------------------------------------------------------
    # Main pipeline entry point
    # ------------------------------------------------------------------

    def generate(
        self,
        run_data: dict[str, Any],
        generation_mode: GenerationMode = "deterministic",
        question_text: str = (
            "What is the evidence for SGLT2 inhibitors in T2DM patients with CKD and CVD?"
        ),
        cohort_is_synthetic: bool = True,
        has_candidate_terminology: bool = True,
    ) -> BriefGenerationResult:
        """Execute the 8-step brief generation pipeline.

        Args:
            run_data: Raw retrieval run dict with keys:
                run_id, records, source_statuses, query_hash, qa_summary
            generation_mode: 'deterministic' (default) or 'live_llm'
            question_text: Natural language question (used in LLM prompts)
            cohort_is_synthetic: Whether the cohort data is synthetic
            has_candidate_terminology: Whether RxNorm codes are candidate/unverified

        Returns:
            BriefGenerationResult with brief, snapshot, QA, provenance.

        Raises:
            BriefGenerationError: Pre-generation gate failures.
            MissingExpectedSourceError: Required template source absent from snapshot.
            CriticalQABlockError: Post-generation QA found blocking issues.
        """
        all_warnings: list[str] = []

        # Step 1+2: validate and snapshot
        snapshot, snap_warnings = self._step_build_snapshot(run_data)
        all_warnings.extend(snap_warnings)

        evidence_run_id = run_data["run_id"]
        brief_id = f"brief-{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)

        # Step 4: generate claims + gaps
        claims, gaps, prompt_version, model_provider, model_name = self._step_generate(
            snapshot, evidence_run_id, generation_mode, question_text
        )

        # Step 5: resolve citations
        claims_with_cits, bibliography = resolve_citations(claims, snapshot)

        # Step 6: generate limitations
        source_statuses_from_run = run_data.get("source_statuses_typed")
        limitations = generate_limitations(
            snapshot,
            source_statuses=source_statuses_from_run,
            cohort_is_synthetic=cohort_is_synthetic,
            has_candidate_terminology=has_candidate_terminology,
        )

        # Determine aggregate data_origin
        origin_set = {r.data_origin for r in snapshot.records}
        if len(origin_set) == 1:
            data_origin = next(iter(origin_set))
        else:
            data_origin = "mixed"

        data_notice = _build_data_notice(snapshot, data_origin)

        # Build provenance
        provenance = BriefProvenance(
            brief_id=brief_id,
            question_id=self._question_id,
            phenotype_id=self._phenotype_id,
            phenotype_version=self._phenotype_version,
            cohort_run_id=self._cohort_run_id,
            evidence_run_id=evidence_run_id,
            evidence_snapshot_id=snapshot.snapshot_id,
            evidence_snapshot_hash=snapshot.snapshot_hash,
            generation_mode=generation_mode,
            model_provider=model_provider,
            model_name=model_name,
            prompt_version=prompt_version,
            data_origin=data_origin,
            generated_at=now,
        )

        # Assemble brief
        brief = EvidenceBrief(
            brief_id=brief_id,
            question_id=self._question_id,
            phenotype_id=self._phenotype_id,
            phenotype_version=self._phenotype_version,
            cohort_run_id=self._cohort_run_id,
            evidence_run_id=evidence_run_id,
            evidence_snapshot_id=snapshot.snapshot_id,
            evidence_snapshot_hash=snapshot.snapshot_hash,
            generated_at=now,
            generation_mode=generation_mode,
            model_provider=model_provider,
            model_name=model_name,
            prompt_version=prompt_version,
            data_origin=data_origin,
            data_notice=data_notice,
            claims=claims_with_cits,
            evidence_gaps=gaps,
            bibliography=bibliography,
            limitations=limitations,
            provenance=provenance,
        )

        # Step 7: run QA checks
        qa_results = run_brief_checks(brief, snapshot)
        qa_summary = {
            "checks_run": len(qa_results),
            "passed": sum(1 for r in qa_results if r["status"] == "passed"),
            "failed": sum(1 for r in qa_results if r["status"] == "failed"),
            "warnings": sum(1 for r in qa_results if r["status"] == "warning"),
            "not_applicable": sum(1 for r in qa_results if r["status"] == "not_applicable"),
            "has_critical_failures": has_critical_failures(qa_results),
        }
        brief = brief.model_copy(update={"qa_summary": qa_summary, "content_hash": ""})
        # Re-trigger hash recomputation
        brief = EvidenceBrief(
            **{
                **brief.model_dump(exclude={"content_hash", "disclaimer"}),
                "disclaimer": brief.disclaimer,
            }
        )

        if qa_summary["has_critical_failures"]:
            failed_checks = [r["check_id"] for r in qa_results if r["status"] == "failed"]
            raise CriticalQABlockError(
                f"Brief generation blocked by {qa_summary['failed']} critical QA failure(s): "
                f"{failed_checks}. "
                "Correct the evidence run configuration and retry."
            )

        # Step 8: persist
        self._repo.save_snapshot(snapshot)
        self._repo.save_brief(brief)
        self._repo.save_qa_results(brief.brief_id, qa_results, version=brief.version)
        self._repo.log_audit(
            brief_id=brief_id,
            event_type="created",
            actor="EvidenceBriefService",
            detail=(
                f"Brief generated via {generation_mode} mode; "
                f"{len(claims_with_cits)} claims; "
                f"QA: {qa_summary['passed']} passed, "
                f"{qa_summary['failed']} failed, "
                f"{qa_summary['warnings']} warnings."
            ),
        )

        return BriefGenerationResult(
            brief=brief,
            snapshot=snapshot,
            qa_summary=qa_summary,
            data_notice=data_notice,
            warnings=all_warnings,
            provenance=provenance,
        )

    # ------------------------------------------------------------------
    # Retrieval helpers
    # ------------------------------------------------------------------

    def get_brief(self, brief_id: str) -> EvidenceBrief:
        return self._repo.get_brief(brief_id)

    def get_brief_qa(self, brief_id: str) -> list[dict[str, Any]]:
        return self._repo.get_brief_qa(brief_id)

    def get_snapshot(self, snapshot_id: str) -> EvidenceSnapshot | None:
        return self._repo.get_snapshot(snapshot_id)
