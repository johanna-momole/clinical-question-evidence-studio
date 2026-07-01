"""Evidence brief generation, citation management, and Markdown export (Phase 5)."""

from src.synthesis.brief_service import EvidenceBriefService
from src.synthesis.citation_resolver import resolve_citations
from src.synthesis.deterministic_generator import generate_deterministic
from src.synthesis.evidence_snapshot import build_snapshot
from src.synthesis.limitations import generate_limitations
from src.synthesis.markdown_export import (
    to_citation_map_tsv,
    to_json,
    to_markdown,
    to_provenance_json,
    to_qa_report_markdown,
    to_review_history_markdown,
)
from src.synthesis.repository import SynthesisRepository, get_synthesis_repository

__all__ = [
    "EvidenceBriefService",
    "SynthesisRepository",
    "build_snapshot",
    "generate_deterministic",
    "generate_limitations",
    "get_synthesis_repository",
    "resolve_citations",
    "to_citation_map_tsv",
    "to_json",
    "to_markdown",
    "to_provenance_json",
    "to_qa_report_markdown",
    "to_review_history_markdown",
]
