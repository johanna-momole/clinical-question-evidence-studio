"""PDF export for EvidenceBrief using reportlab.

Generates a structured PDF from a persisted EvidenceBrief without adding
new claims. All content is derived from the brief, snapshot, QA results,
and review history already stored in DuckDB.
"""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.schemas.brief import EvidenceBrief, EvidenceSnapshot

_DISCLAIMER_STYLE_OPTS: dict[str, Any] = {
    "backColor": colors.HexColor("#fff3cd"),
    "borderColor": colors.HexColor("#ffc107"),
    "borderWidth": 1,
    "borderPadding": 6,
    "borderRadius": 4,
}

_APP_VERSION = "1.0.0"


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "BriefTitle",
            parent=base["Title"],
            fontSize=20,
            leading=26,
            spaceAfter=8,
        ),
        "h1": ParagraphStyle(
            "BriefH1",
            parent=base["Heading1"],
            fontSize=14,
            leading=18,
            spaceBefore=14,
            spaceAfter=6,
            textColor=colors.HexColor("#1e3a5f"),
        ),
        "h2": ParagraphStyle(
            "BriefH2",
            parent=base["Heading2"],
            fontSize=12,
            leading=16,
            spaceBefore=10,
            spaceAfter=4,
            textColor=colors.HexColor("#2c5282"),
        ),
        "body": ParagraphStyle(
            "BriefBody",
            parent=base["BodyText"],
            fontSize=10,
            leading=14,
            spaceAfter=4,
        ),
        "disclaimer": ParagraphStyle(
            "BriefDisclaimer",
            parent=base["BodyText"],
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#856404"),
            **_DISCLAIMER_STYLE_OPTS,
        ),
        "citation": ParagraphStyle(
            "BriefCitation",
            parent=base["BodyText"],
            fontSize=9,
            leading=12,
            leftIndent=12,
            spaceAfter=2,
        ),
        "meta": ParagraphStyle(
            "BriefMeta",
            parent=base["BodyText"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#4a5568"),
        ),
        "warning": ParagraphStyle(
            "BriefWarning",
            parent=base["BodyText"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#c0392b"),
        ),
        "footer": ParagraphStyle(
            "BriefFooter",
            parent=base["BodyText"],
            fontSize=8,
            leading=10,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#718096"),
        ),
        "center": ParagraphStyle(
            "BriefCenter",
            parent=base["BodyText"],
            fontSize=10,
            leading=14,
            alignment=TA_CENTER,
        ),
        "label": ParagraphStyle(
            "BriefLabel",
            parent=base["BodyText"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#2d3748"),
            fontName="Helvetica-Bold",
        ),
    }


def _page_header_footer(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#718096"))
    canvas.drawString(
        2 * cm,
        1.2 * cm,
        "Clinical Question-Evidence Studio — Educational prototype — Not for clinical use",
    )
    canvas.drawRightString(
        A4[0] - 2 * cm,
        1.2 * cm,
        f"Page {doc.page}",
    )
    canvas.restoreState()


def generate_pdf(
    brief: EvidenceBrief,
    snapshot: EvidenceSnapshot | None,
    qa_results: list[dict],
    review_history: list[dict],
    question_text: str = "",
    pico_summary: dict | None = None,
    phenotype_summary: dict | None = None,
    cohort_attrition: list[dict] | None = None,
) -> bytes:
    """Render a PDF from a persisted EvidenceBrief. Returns raw bytes.

    No new claims are added during rendering. All content is read from
    the brief object and supplementary metadata passed in.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2 * cm,
        title=f"Evidence Brief — {brief.brief_id}",
        author="Clinical Question-Evidence Studio",
        subject="Evidence Brief (Educational Prototype)",
        creator=f"CQES v{_APP_VERSION}",
    )

    s = _styles()
    story: list[Any] = []

    # ── 1. Title page ──────────────────────────────────────────────────────────
    story.append(Spacer(1, 1.5 * cm))
    story.append(Paragraph("Evidence Brief", s["title"]))
    story.append(Paragraph("Clinical Question-Evidence Studio", s["center"]))
    story.append(Spacer(1, 0.5 * cm))

    meta_rows = [
        ["Brief ID", brief.brief_id],
        ["Version", str(brief.version)],
        ["Generation mode", brief.generation_mode],
        ["Data origin", brief.data_origin],
        ["Review status", brief.human_review_status],
        ["Content hash", brief.content_hash[:24] + "…" if brief.content_hash else "—"],
    ]
    meta_table = Table(meta_rows, colWidths=[4 * cm, 12 * cm])
    meta_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#2d3748")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(meta_table)
    story.append(PageBreak())

    # ── 2. Data-origin notice ──────────────────────────────────────────────────
    story.append(Paragraph("Data-Origin Notice", s["h1"]))
    story.append(Paragraph(brief.data_notice or "No data-origin notice recorded.", s["body"]))
    story.append(Spacer(1, 0.3 * cm))

    # ── 3. Required disclaimer ─────────────────────────────────────────────────
    story.append(Paragraph("Required Disclaimer", s["h1"]))
    story.append(Paragraph(brief.disclaimer, s["disclaimer"]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0")))

    # ── 4. Clinical research question ──────────────────────────────────────────
    story.append(Paragraph("Clinical Research Question", s["h1"]))
    story.append(Paragraph(question_text or "(not provided)", s["body"]))

    # ── 5. PICO summary ────────────────────────────────────────────────────────
    if pico_summary:
        story.append(Paragraph("PICO Framework", s["h2"]))
        pico_rows = [
            ["Population", str(pico_summary.get("population", "—"))],
            ["Intervention", str(pico_summary.get("intervention", "—"))],
            ["Comparator", str(pico_summary.get("comparator", "—"))],
            ["Outcomes", ", ".join(pico_summary.get("outcomes", [])) or "—"],
        ]
        pico_t = Table(pico_rows, colWidths=[3.5 * cm, 12.5 * cm])
        pico_t.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(pico_t)

    # ── 6. Phenotype summary ───────────────────────────────────────────────────
    if phenotype_summary:
        story.append(Paragraph("Computable Phenotype", s["h2"]))
        pheno_text = (
            f"<b>{phenotype_summary.get('name', '—')}</b> "
            f"v{phenotype_summary.get('version', '—')} — "
            f"{phenotype_summary.get('description', '')}"
        )
        story.append(Paragraph(pheno_text, s["body"]))

    # ── 7. Synthetic cohort attrition ──────────────────────────────────────────
    if cohort_attrition:
        story.append(Paragraph("Synthetic Cohort Attrition", s["h2"]))
        story.append(
            Paragraph(
                "<b>Note:</b> Cohort data is entirely synthetic (Synthea FHIR R4). "
                "These numbers do not represent real patients.",
                s["warning"],
            )
        )
        story.append(Spacer(1, 0.2 * cm))
        atr_headers = [["Step", "Label", "Records In", "Excluded", "Records Out"]]
        atr_rows = [
            [
                str(row.get("Step", "")),
                str(row.get("Label", "")),
                str(row.get("Records In", "")),
                str(row.get("Excluded", "")),
                str(row.get("Records Out", "")),
            ]
            for row in cohort_attrition
        ]
        atr_t = Table(atr_headers + atr_rows, colWidths=[1.5 * cm, 5 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm])
        atr_t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c5282")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#ebf4ff")]),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(atr_t)

    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0")))

    # ── 8. Findings by dimension ───────────────────────────────────────────────
    story.append(Paragraph("Evidence Findings", s["h1"]))
    dimensions_seen: set[str] = set()
    for claim in brief.claims:
        if claim.dimension not in dimensions_seen:
            story.append(Paragraph(claim.dimension.replace("_", " ").title(), s["h2"]))
            dimensions_seen.add(claim.dimension)
        citation_str = ""
        cit_nums = [c.citation_number for c in claim.citations]
        if cit_nums:
            citation_str = " " + " ".join(f"[{n}]" for n in cit_nums)
        type_badge = f"[{claim.claim_type.upper()}]"
        claim_para = f"{type_badge} {claim.text}{citation_str}"
        story.append(Paragraph(claim_para, s["body"]))
        if claim.uncertainty_note:
            story.append(Paragraph(f"<i>Note: {claim.uncertainty_note}</i>", s["meta"]))
        story.append(Spacer(1, 0.15 * cm))

    # ── 9. Evidence gaps ──────────────────────────────────────────────────────
    if brief.evidence_gaps:
        story.append(Paragraph("Evidence Gaps", s["h1"]))
        for gap in brief.evidence_gaps:
            story.append(Paragraph(f"• {gap.description}", s["body"]))
            if gap.dimension:
                story.append(Paragraph(f"  Dimension: {gap.dimension}", s["meta"]))

    # ── 10. Limitations ───────────────────────────────────────────────────────
    if brief.limitations:
        story.append(Paragraph("Limitations", s["h1"]))
        for lim in brief.limitations:
            story.append(Paragraph(f"• {lim}", s["body"]))

    # ── 11. Bibliography ──────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Bibliography", s["h1"]))
    if brief.bibliography:
        for entry in brief.bibliography:
            num = entry.citation_number
            title = entry.title or "—"
            source = entry.source_type
            ident = entry.source_specific_id
            url = entry.url or ""
            origin = ""
            line = f"[{num}] {title}"
            if source:
                line += f" ({source}"
                if ident:
                    line += f" {ident}"
                line += ")"
            if origin:
                line += f" — {origin}"
            story.append(Paragraph(line, s["citation"]))
            if url:
                story.append(Paragraph(f"    {url}", s["meta"]))
    else:
        story.append(Paragraph("No bibliography entries.", s["meta"]))

    # ── 12. QA summary ────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("QA Summary", s["h1"]))
    if qa_results:
        qa_headers = [["Check ID", "Status", "Severity", "Details"]]
        qa_rows = [
            [
                str(r.get("check_id", "")),
                str(r.get("status", "")).upper(),
                str(r.get("severity", "")),
                str(r.get("details", "") or "")[:120],
            ]
            for r in qa_results
        ]
        qa_t = Table(qa_headers + qa_rows, colWidths=[2.5 * cm, 2.5 * cm, 2.5 * cm, 8.5 * cm])
        qa_t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c5282")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ("WORDWRAP", (3, 1), (3, -1), True),
                ]
            )
        )
        story.append(qa_t)
    else:
        story.append(Paragraph("No QA results recorded.", s["meta"]))

    # ── 13. Human-review status ───────────────────────────────────────────────
    story.append(Paragraph("Human Review Status", s["h1"]))
    story.append(
        Paragraph(f"Current status: <b>{brief.human_review_status}</b>", s["body"])
    )
    if review_history:
        story.append(Paragraph("Review history:", s["h2"]))
        rev_headers = [["Timestamp", "Status", "Reviewer", "Note"]]
        rev_rows = [
            [
                str(r.get("review_timestamp", ""))[:19],
                str(r.get("new_status", "")),
                str(r.get("reviewer_id", "")),
                str(r.get("note", "") or "")[:80],
            ]
            for r in review_history
        ]
        rev_t = Table(rev_headers + rev_rows, colWidths=[4 * cm, 3 * cm, 3 * cm, 6 * cm])
        rev_t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c5282")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(rev_t)

    # ── 14. Provenance appendix ───────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Provenance Appendix", s["h1"]))
    prov_rows = [
        ["Evidence run ID", brief.evidence_run_id],
        ["Evidence snapshot ID", brief.evidence_snapshot_id],
        ["Snapshot hash", brief.evidence_snapshot_hash],
        ["Content hash", brief.content_hash],
        ["Generation mode", brief.generation_mode],
        ["Model name", brief.provenance.model_name if brief.provenance else "—"],
        ["Generator version", brief.provenance.schema_version if brief.provenance else "—"],
        [
            "Evidence record count",
            str(len(snapshot.records)) if snapshot else "—",
        ],
    ]
    prov_t = Table(prov_rows, colWidths=[5 * cm, 11 * cm])
    prov_t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(prov_t)

    # ── 15. Repeat disclaimer ─────────────────────────────────────────────────
    story.append(Spacer(1, 0.6 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0")))
    story.append(Paragraph(brief.disclaimer, s["disclaimer"]))

    doc.build(story, onFirstPage=_page_header_footer, onLaterPages=_page_header_footer)
    return buf.getvalue()
