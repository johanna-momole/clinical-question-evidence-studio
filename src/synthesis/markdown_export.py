"""Markdown and JSON export for evidence briefs.

Supported export formats:
  - JSON: full EvidenceBrief model dump (machine-readable)
  - Markdown: human-readable brief with inline [N] citations
  - Citation map: TSV mapping citation numbers to source metadata
  - QA report: Markdown table of all BQ checks
  - Review history: Markdown table of human review records
  - Provenance: JSON dump of BriefProvenance

No PDF or PPTX export is implemented (spec constraint).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.schemas.brief import (
    BriefProvenance,
    EvidenceBrief,
    GeneratedClaim,
)

_CLAIM_TYPE_LABEL = {
    "supported": "Finding",
    "exploratory": "Exploratory finding",
    "insufficient_evidence": "Evidence gap",
}

_DIMENSION_LABEL = {
    "population": "Population",
    "intervention": "Intervention",
    "outcome": "Outcomes",
    "safety": "Safety",
    "design": "Study Design",
    "coverage": "Coverage / Policy",
    "evidence_gap": "Evidence Gap",
}


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------


def to_json(brief: EvidenceBrief, indent: int = 2) -> str:
    """Full brief as JSON (model_dump)."""
    return json.dumps(brief.model_dump(mode="json"), indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Markdown export
# ---------------------------------------------------------------------------


def to_markdown(brief: EvidenceBrief) -> str:
    """Human-readable evidence brief in GitHub-flavoured Markdown."""
    lines: list[str] = []

    # Header
    lines.append(f"# Evidence Brief: {brief.brief_id}")
    lines.append("")
    lines.append(f"**Generated:** {_fmt_dt(brief.generated_at)}")
    lines.append(f"**Mode:** {brief.generation_mode}")
    lines.append(f"**Question:** {brief.question_id}")
    lines.append(f"**Review status:** {brief.human_review_status.replace('_', ' ').title()}")
    lines.append("")

    # Disclaimer (always first block)
    lines.append("> **Important notice**")
    for sentence in brief.disclaimer.split(". "):
        sentence = sentence.strip()
        if sentence:
            lines.append(f"> {sentence}.")
    lines.append("")

    # Data notice
    lines.append(f"*Data source:* {brief.data_notice}")
    lines.append("")

    # Claims by dimension
    grouped: dict[str, list[GeneratedClaim]] = {}
    for c in brief.claims:
        grouped.setdefault(c.dimension, []).append(c)

    dim_order = [
        "population",
        "intervention",
        "outcome",
        "safety",
        "design",
        "coverage",
        "evidence_gap",
    ]
    for dim in dim_order:
        claims = grouped.get(dim, [])
        if not claims:
            continue
        lines.append(f"## {_DIMENSION_LABEL.get(dim, dim.title())}")
        lines.append("")
        for claim in claims:
            label = _CLAIM_TYPE_LABEL.get(claim.claim_type, "Finding")
            # Build inline citation string
            cit_nums = sorted({c.citation_number for c in claim.citations})
            cit_str = " ".join(f"[{n}]" for n in cit_nums)
            lines.append(f"**{label}:** {claim.text}")
            if cit_str:
                lines.append(f"*Sources: {cit_str}*")
            if claim.design_limitations:
                lines.append("")
                lines.append("*Design limitations:*")
                for lim in claim.design_limitations:
                    lines.append(f"- {lim}")
            if claim.uncertainty_note:
                lines.append("")
                lines.append(f"*Uncertainty:* {claim.uncertainty_note}")
            lines.append("")

    # Evidence gaps
    if brief.evidence_gaps:
        lines.append("## Evidence Gaps")
        lines.append("")
        for gap in brief.evidence_gaps:
            dim_label = _DIMENSION_LABEL.get(gap.dimension, gap.dimension.title())
            lines.append(f"**{dim_label} gap:** {gap.description}")
            if gap.limitations:
                for lim in gap.limitations:
                    lines.append(f"- {lim}")
            lines.append("")

    # Limitations
    if brief.limitations:
        lines.append("## Limitations")
        lines.append("")
        for lim in brief.limitations:
            lines.append(f"- {lim}")
        lines.append("")

    # Bibliography
    if brief.bibliography:
        lines.append("## Bibliography")
        lines.append("")
        for cit in sorted(brief.bibliography, key=lambda c: c.citation_number):
            url_part = f" [{cit.url}]({cit.url})" if cit.url else ""
            lines.append(
                f"[{cit.citation_number}] **{cit.title}** ({cit.source_type}; "
                f"{cit.source_specific_id}){url_part}"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Citation map (TSV)
# ---------------------------------------------------------------------------


def to_citation_map_tsv(brief: EvidenceBrief) -> str:
    """Tab-separated citation map for auditing source traceability."""
    header = "\t".join(
        [
            "citation_number",
            "source_id",
            "source_specific_id",
            "source_type",
            "title",
            "url",
            "support_type",
        ]
    )
    rows = [header]
    for cit in sorted(brief.bibliography, key=lambda c: c.citation_number):
        rows.append(
            "\t".join(
                [
                    str(cit.citation_number),
                    cit.source_id,
                    cit.source_specific_id,
                    cit.source_type,
                    cit.title.replace("\t", " "),
                    cit.url or "",
                    cit.support_type,
                ]
            )
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# QA report (Markdown)
# ---------------------------------------------------------------------------


def to_qa_report_markdown(
    brief_id: str,
    qa_results: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append(f"# QA Report: {brief_id}")
    lines.append("")

    total = len(qa_results)
    passed = sum(1 for r in qa_results if r["status"] == "passed")
    failed = sum(1 for r in qa_results if r["status"] == "failed")
    warnings = sum(1 for r in qa_results if r["status"] == "warning")

    lines.append(f"**{total} checks:** {passed} passed · {failed} failed · {warnings} warnings")
    lines.append("")
    lines.append("| Check ID | Name | Status | Severity | Details |")
    lines.append("|----------|------|--------|----------|---------|")
    for r in qa_results:
        status_icon = {
            "passed": "✓",
            "failed": "✗",
            "warning": "⚠",
            "not_applicable": "—",
        }.get(r["status"], r["status"])
        details = (r.get("details") or "").replace("|", "∣")
        lines.append(
            f"| {r['check_id']} | {r['check_name']} | {status_icon} {r['status']} "
            f"| {r['severity']} | {details} |"
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Review history (Markdown)
# ---------------------------------------------------------------------------


def to_review_history_markdown(
    brief_id: str,
    reviews: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append(f"# Review History: {brief_id}")
    lines.append("")
    if not reviews:
        lines.append("*No review actions have been recorded for this brief.*")
        lines.append("")
        return "\n".join(lines)

    lines.append("| Review ID | Status change | Reviewer | Timestamp | Note |")
    lines.append("|-----------|---------------|----------|-----------|------|")
    for r in reviews:
        note = (r.get("note") or "").replace("|", "∣")[:80]
        lines.append(
            f"| {r.get('review_id', '')} "
            f"| {r.get('previous_status', '')} → {r.get('new_status', '')} "
            f"| {r.get('reviewer_label', r.get('reviewer_id', ''))} "
            f"| {r.get('timestamp', '')} "
            f"| {note} |"
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Provenance export (JSON)
# ---------------------------------------------------------------------------


def to_provenance_json(provenance: BriefProvenance, indent: int = 2) -> str:
    return json.dumps(provenance.model_dump(mode="json"), indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "unknown"
    return dt.strftime("%Y-%m-%d %H:%M UTC")
