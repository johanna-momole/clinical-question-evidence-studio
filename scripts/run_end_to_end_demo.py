"""End-to-end offline demonstration script.

Runs the complete Clinical Question-Evidence Studio pipeline using bundled
fixtures and no internet connection or LLM API key.

Usage:
    python scripts/run_end_to_end_demo.py [--output-dir OUT_DIR]

Exit codes:
    0  All stages completed successfully
    1  One or more critical stages failed

Determinism guarantee:
    Run this script twice with the same fixture set; the following outputs
    must be identical across runs:
        - question hash
        - phenotype hash
        - cohort attrition sequence
        - final cohort count
        - evidence query hash
        - evidence snapshot hash
        - normalized evidence IDs
        - brief claims
        - citation mapping
        - bibliography
        - QA statuses
        - Markdown content hash
        - export checksums

    Permitted differences across runs:
        - run IDs (UUIDs)
        - timestamps
        - archive creation timestamps
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Ensure project root is importable
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from rich.console import Console
from rich.table import Table

console = Console()

_EXPECTED_ATTRITION = [160, 148, 143, 113, 78, 78, 70]
_EXPECTED_FINAL_COUNT = 70
_CURATED_QUESTION_ID = "q-sglt2-ckd-t2dm-001"


def _sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:16]


def _fail(stage: str, reason: str) -> None:
    console.print(f"[bold red]FAIL[/] [{stage}] {reason}")


def _ok(stage: str, detail: str = "") -> None:
    console.print(f"[bold green]OK[/]   [{stage}]{(' — ' + detail) if detail else ''}")


def run_demo(output_dir: Path | None = None) -> dict:
    """Execute the full pipeline and return a results dict."""
    results: dict = {
        "stages": {},
        "hashes": {},
        "counts": {},
        "errors": [],
    }

    console.rule("[bold blue]Clinical Question-Evidence Studio — End-to-End Demo[/]")
    console.print("Mode: OFFLINE (no internet, no LLM API key)")
    console.print()

    # ── Stage 1: Question selection ────────────────────────────────────────────
    try:
        from src.question_parser.service import get_question_service

        svc = get_question_service()
        curated = svc.get_curated_questions()
        question = next((q for q in curated if q.question_id == _CURATED_QUESTION_ID), None)
        if question is None:
            raise ValueError(f"Curated question {_CURATED_QUESTION_ID!r} not found")

        q_hash = _sha256(question.question_text)
        results["hashes"]["question_text"] = q_hash
        results["stages"]["question"] = "ok"
        _ok("question", f"ID={question.question_id}  hash={q_hash}")
        console.print(f"         Text: {question.question_text[:80]}…")
    except Exception as exc:
        results["stages"]["question"] = f"FAIL: {exc}"
        results["errors"].append(f"question: {exc}")
        _fail("question", str(exc))
        return results

    # ── Stage 2: PICO review ───────────────────────────────────────────────────
    try:
        pico = question.pico
        pico_hash = _sha256(json.dumps(pico.model_dump(), sort_keys=True))
        results["hashes"]["pico"] = pico_hash
        results["stages"]["pico"] = "ok"
        _ok("pico", f"hash={pico_hash}")
        console.print(f"         Population: {pico.population[:60]}")
        console.print(f"         Intervention: {pico.intervention[:60]}")
    except Exception as exc:
        results["stages"]["pico"] = f"FAIL: {exc}"
        results["errors"].append(f"pico: {exc}")
        _fail("pico", str(exc))

    # ── Stage 3: Phenotype ─────────────────────────────────────────────────────
    try:
        from src.phenotypes.service import get_phenotype_service

        pheno_svc = get_phenotype_service()
        phenotype = pheno_svc.get_phenotype_for_question(question.question_id)
        if phenotype is None:
            raise ValueError("No phenotype found for question")

        pheno_hash = _sha256(phenotype.model_dump_json())
        results["hashes"]["phenotype"] = pheno_hash
        results["stages"]["phenotype"] = "ok"
        _ok("phenotype", f"name={phenotype.name}  v{phenotype.version}  hash={pheno_hash}")
    except Exception as exc:
        results["stages"]["phenotype"] = f"FAIL: {exc}"
        results["errors"].append(f"phenotype: {exc}")
        _fail("phenotype", str(exc))
        return results

    # ── Stage 4: Synthetic FHIR ingestion ─────────────────────────────────────
    try:
        from src.fhir.service import get_fhir_service

        fhir_svc = get_fhir_service()
        datasets = fhir_svc.list_datasets()
        if not datasets:
            raise ValueError("No FHIR datasets found")

        dataset = datasets[0]
        fhir_result = fhir_svc.ingest(dataset.dataset_id)
        results["counts"]["fhir_patients"] = fhir_result.patient_count
        results["stages"]["fhir"] = "ok"
        _ok("fhir", f"dataset={dataset.dataset_id}  patients={fhir_result.patient_count}")
    except Exception as exc:
        results["stages"]["fhir"] = f"FAIL: {exc}"
        results["errors"].append(f"fhir: {exc}")
        _fail("fhir", str(exc))
        return results

    # ── Stage 5: Cohort execution ──────────────────────────────────────────────
    try:
        from src.cohorts.service import get_cohort_service
        from src.schemas.cohort import CohortConfiguration

        cohort_svc = get_cohort_service()
        config = CohortConfiguration(
            configuration_id="demo-config",
            phenotype_id=phenotype.phenotype_id,
            phenotype_version=phenotype.version,
            dataset_id=dataset.dataset_id,
            include_demographics=True,
        )
        cohort_run = cohort_svc.run(
            phenotype=phenotype,
            fhir_result=fhir_result,
            config=config,
        )
        attrition_seq = [step.records_out for step in cohort_run.attrition.steps]
        final_count = cohort_run.attrition.final_count

        results["counts"]["cohort_final"] = final_count
        results["counts"]["attrition_sequence"] = attrition_seq
        results["stages"]["cohort"] = "ok"

        # Validate against expected attrition
        if attrition_seq != _EXPECTED_ATTRITION:
            console.print(
                f"[yellow]WARN[/] Attrition {attrition_seq} ≠ expected {_EXPECTED_ATTRITION}"
            )
        if final_count != _EXPECTED_FINAL_COUNT:
            console.print(
                f"[yellow]WARN[/] Final count {final_count} ≠ expected {_EXPECTED_FINAL_COUNT}"
            )

        _ok("cohort", f"final_count={final_count}  attrition={attrition_seq}")
    except Exception as exc:
        results["stages"]["cohort"] = f"FAIL: {exc}"
        results["errors"].append(f"cohort: {exc}")
        _fail("cohort", str(exc))
        return results

    # ── Stage 6: Evidence retrieval (offline fixture mode) ─────────────────────
    try:
        from src.evidence.repository import get_evidence_repository
        from src.evidence.service import get_evidence_service

        ev_repo = get_evidence_repository()
        ev_svc = get_evidence_service(ev_repo)
        retrieval_run = ev_svc.run(
            question=question,
            phenotype=phenotype,
            offline_only=True,
        )
        ev_count = retrieval_run.total_records_returned
        query_hash = retrieval_run.query_hash or _sha256(str(retrieval_run.run_id))
        results["hashes"]["evidence_query"] = query_hash[:16]
        results["counts"]["evidence_records"] = ev_count
        results["stages"]["evidence"] = "ok"

        source_counts = {s.source_name: s.records_returned for s in retrieval_run.source_statuses}
        _ok("evidence", f"total={ev_count}  sources={source_counts}")
        console.print(f"         Query hash: {query_hash[:24]}")
    except Exception as exc:
        results["stages"]["evidence"] = f"FAIL: {exc}"
        results["errors"].append(f"evidence: {exc}")
        _fail("evidence", str(exc))
        return results

    # ── Stage 7: Evidence normalization (happens inside ev_svc.run above) ──────
    results["stages"]["normalization"] = "ok"
    _ok("normalization", "completed as part of evidence pipeline")

    # ── Stage 8: Evidence brief generation ────────────────────────────────────
    try:
        from src.synthesis.brief_service import EvidenceBriefService

        run_dict = ev_svc.get_run_as_dict(retrieval_run.run_id)
        brief_svc = EvidenceBriefService()
        gen_result = brief_svc.generate(
            run_data=run_dict,
            generation_mode="deterministic",
            question_text=question.question_text,
        )
        brief = gen_result.brief
        snap_hash = brief.evidence_snapshot_hash
        content_hash = brief.content_hash
        claim_count = len(brief.claims)

        results["hashes"]["snapshot"] = snap_hash[:16]
        results["hashes"]["brief_content"] = content_hash[:16]
        results["counts"]["claims"] = claim_count
        results["stages"]["brief_generation"] = "ok"
        _ok(
            "brief_generation",
            f"brief_id={brief.brief_id}  claims={claim_count}  "
            f"snapshot_hash={snap_hash[:16]}  content_hash={content_hash[:16]}",
        )
    except Exception as exc:
        results["stages"]["brief_generation"] = f"FAIL: {exc}"
        results["errors"].append(f"brief_generation: {exc}")
        _fail("brief_generation", str(exc))
        return results

    # ── Stage 9: Brief QA ──────────────────────────────────────────────────────
    try:
        from src.synthesis.repository import get_synthesis_repository

        repo = get_synthesis_repository()
        qa_results = repo.get_qa_results(brief.brief_id) or []
        critical_fails = [
            r for r in qa_results if r.get("severity") == "critical" and r.get("status") == "failed"
        ]
        warn_count = sum(1 for r in qa_results if r.get("status") == "warning")

        results["counts"]["qa_checks"] = len(qa_results)
        results["counts"]["qa_critical_failures"] = len(critical_fails)
        results["counts"]["qa_warnings"] = warn_count
        results["stages"]["brief_qa"] = "ok"

        status_summary = {r.get("check_id"): r.get("status") for r in qa_results}
        results["hashes"]["qa_statuses"] = _sha256(json.dumps(status_summary, sort_keys=True))
        _ok(
            "brief_qa",
            f"checks={len(qa_results)}  critical_fails={len(critical_fails)}  warns={warn_count}",
        )
    except Exception as exc:
        results["stages"]["brief_qa"] = f"FAIL: {exc}"
        results["errors"].append(f"brief_qa: {exc}")
        _fail("brief_qa", str(exc))

    # ── Stage 10: Technical review ─────────────────────────────────────────────
    try:
        from src.review.brief_review_service import BriefReviewService

        review_svc = BriefReviewService()
        review_record = review_svc.submit_review(
            brief_id=brief.brief_id,
            new_status="in_review",
            reviewer_id="demo-script",
            reviewer_label="Demo script review",
            note="Automated demo run",
        )
        results["stages"]["review"] = "ok"
        _ok("review", f"status={review_record.new_status}")
    except Exception as exc:
        results["stages"]["review"] = f"FAIL: {exc}"
        results["errors"].append(f"review: {exc}")
        _fail("review", str(exc))

    # ── Stage 11: Export generation ────────────────────────────────────────────
    try:
        from src.exports.service import ExportService
        from src.schemas.exports import ExportRequest

        exp_svc = ExportService()
        snap_raw = repo.get_snapshot(brief.evidence_snapshot_id)
        from src.schemas.brief import EvidenceSnapshot

        snapshot = EvidenceSnapshot.model_validate(snap_raw) if snap_raw else None
        review_history = repo.get_review_history(brief.brief_id) or []

        req = ExportRequest(
            brief_id=brief.brief_id,
            formats=[
                "json",
                "markdown",
                "citation_map_tsv",
                "qa_report_json",
                "provenance",
                "pdf",
                "pptx",
                "zip",
            ],
        )
        bundle, artifact_bytes = exp_svc.generate_bundle(
            request=req,
            brief=brief,
            snapshot=snapshot,
            qa_results=qa_results,
            review_history=review_history,
            supplementary={"question_text": question.question_text},
        )

        export_checksums: dict[str, str] = {}
        export_sizes: dict[str, int] = {}
        for art in bundle.manifest.artifacts:
            content = artifact_bytes.get(art.artifact_id)
            if content:
                export_checksums[art.export_format] = art.sha256[:16]
                export_sizes[art.export_format] = art.byte_size

        if "__zip__" in artifact_bytes:
            export_checksums["zip"] = bundle.zip_sha256[:16] if bundle.zip_sha256 else "—"
            export_sizes["zip"] = bundle.zip_byte_size or 0

        results["hashes"]["exports"] = export_checksums
        results["counts"]["export_sizes"] = export_sizes
        results["stages"]["exports"] = "ok"
        results["hashes"]["manifest"] = bundle.manifest.manifest_sha256[:16]

        _ok(
            "exports",
            f"formats={bundle.artifacts_generated}  manifest={bundle.manifest.manifest_sha256[:16]}",
        )

        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            for art in bundle.manifest.artifacts:
                content = artifact_bytes.get(art.artifact_id)
                if content:
                    (output_dir / art.filename).write_bytes(content)
            if "__zip__" in artifact_bytes:
                zip_fname = bundle.zip_filename or f"{brief.brief_id}_bundle.zip"
                (output_dir / zip_fname).write_bytes(artifact_bytes["__zip__"])
            console.print(f"         Exports written to: {output_dir}")

    except Exception as exc:
        results["stages"]["exports"] = f"FAIL: {exc}"
        results["errors"].append(f"exports: {exc}")
        _fail("exports", str(exc))

    return results


def _print_summary(results: dict) -> None:
    console.rule("[bold]Pipeline Summary[/]")

    # Stage table
    stage_table = Table(title="Stage Results", show_header=True, header_style="bold blue")
    stage_table.add_column("Stage", style="cyan", width=22)
    stage_table.add_column("Status", width=10)
    for stage, status in results["stages"].items():
        color = "green" if status == "ok" else "red"
        stage_table.add_row(stage, f"[{color}]{status}[/{color}]")
    console.print(stage_table)

    # Hash table
    hash_table = Table(title="Deterministic Hashes (first 16 hex chars)", show_header=True)
    hash_table.add_column("Key", style="cyan", width=20)
    hash_table.add_column("Hash", width=20)
    for k, v in results.get("hashes", {}).items():
        if isinstance(v, str):
            hash_table.add_row(k, v)
    console.print(hash_table)

    # Count table
    count_table = Table(title="Record Counts", show_header=True)
    count_table.add_column("Metric", style="cyan", width=24)
    count_table.add_column("Value", width=20)
    for k, v in results.get("counts", {}).items():
        count_table.add_row(k, str(v))
    console.print(count_table)

    if results["errors"]:
        console.print("[bold red]Errors:[/]")
        for e in results["errors"]:
            console.print(f"  - {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-end offline demo")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write export artifacts (optional)",
    )
    args = parser.parse_args()

    results = run_demo(output_dir=args.output_dir)
    _print_summary(results)

    # Persist results for determinism comparison
    results_path = Path("data/demo_run_results.json")
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(results_path, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    console.print(f"\nResults written to: {results_path}")

    failed_stages = [s for s, v in results["stages"].items() if v != "ok"]
    if failed_stages:
        console.print(f"\n[bold red]FAILED stages:[/] {', '.join(failed_stages)}")
        return 1

    console.print("\n[bold green]All stages completed successfully.[/]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
