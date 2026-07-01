"""Deterministic, non-LLM evidence query builder.

Gates:
  1. ClinicalQuestion.status must be 'approved'  → raises ApprovalRequiredError
  2. PhenotypeDefinition.review_status must be 'approved' → raises UnapprovedPhenotypeError

Query construction is purely rule-based: extract PICO terms from the question's
PICOFramework, extract RxNorm/ICD codes from the phenotype's concepts, and compose
source-native query strings.  No LLM, no randomness, no network calls.

The same (question, phenotype) pair always produces the same EvidenceQuery and the
same query_hash — verified by cross-process determinism tests in the test suite.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from src.schemas.phenotype import PhenotypeDefinition
from src.schemas.question import ClinicalQuestion
from src.schemas.retrieval import EvidenceQuery, SourceSpecificQuery
from src.utils.exceptions import ApprovalRequiredError, UnapprovedPhenotypeError


def build_query(
    question: ClinicalQuestion,
    phenotype: PhenotypeDefinition,
) -> EvidenceQuery:
    """Build a deterministic EvidenceQuery from an approved question + reviewed phenotype.

    Raises:
        ApprovalRequiredError: if question.status != 'approved'.
        UnapprovedPhenotypeError: if phenotype.review_status != 'approved'.
    """
    if question.status != "approved":
        raise ApprovalRequiredError(
            f"Evidence query requires question.status == 'approved'; "
            f"got '{question.status}' for question '{question.id}'. "
            "Approve the clinical question before building an evidence query."
        )
    if phenotype.review_status != "approved":
        raise UnapprovedPhenotypeError(
            f"Evidence query requires phenotype.review_status == 'approved'; "
            f"got '{phenotype.review_status}' for phenotype '{phenotype.id}'. "
            "Approve the phenotype structure before building an evidence query."
        )

    pico = question.pico
    population_terms = _extract_pico_terms(pico.population, pico.population_detail)
    intervention_terms = _extract_pico_terms(pico.intervention)
    comparator_terms = _extract_pico_terms(pico.comparator) if pico.comparator else []
    outcome_terms = list(pico.outcomes)

    rxnorm_codes = _extract_rxnorm_codes(phenotype)
    icd_codes = _extract_icd_codes(phenotype)

    source_queries = [
        _build_pubmed_query(population_terms, intervention_terms, outcome_terms, rxnorm_codes),
        _build_clinical_trials_query(population_terms, intervention_terms, rxnorm_codes),
        _build_cms_query(population_terms, intervention_terms, icd_codes),
    ]

    query_hash = _deterministic_hash(question, phenotype, source_queries)

    return EvidenceQuery(
        id=f"eq-{uuid.uuid4().hex[:8]}",
        question_id=question.id,
        phenotype_id=phenotype.id,
        phenotype_version=phenotype.version,
        population_terms=population_terms,
        intervention_terms=intervention_terms,
        comparator_terms=comparator_terms,
        outcome_terms=outcome_terms,
        source_queries=source_queries,
        query_hash=query_hash,
        built_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Source-specific query composers
# ---------------------------------------------------------------------------


def _build_pubmed_query(
    population_terms: list[str],
    intervention_terms: list[str],
    outcome_terms: list[str],
    rxnorm_codes: list[str],
) -> SourceSpecificQuery:
    """Compose a PubMed boolean MeSH/keyword query string."""
    pop_clause = " OR ".join(f'"{t}"[MeSH Terms]' for t in _dedup(population_terms))
    int_clause = " OR ".join(f'"{t}"[MeSH Terms]' for t in _dedup(intervention_terms))
    out_clause = " OR ".join(f'"{t}"[Title/Abstract]' for t in _dedup(outcome_terms[:3]))
    query = f"({pop_clause}) AND ({int_clause}) AND ({out_clause})"
    return SourceSpecificQuery(
        source_name="pubmed",
        query_string=query,
        parameters={
            "retmax": 50,
            "sort": "relevance",
            "db": "pubmed",
        },
        terms_used=population_terms + intervention_terms + outcome_terms[:3],
    )


def _build_clinical_trials_query(
    population_terms: list[str],
    intervention_terms: list[str],
    rxnorm_codes: list[str],
) -> SourceSpecificQuery:
    """Compose a ClinicalTrials.gov v2 query term."""
    terms = _dedup(intervention_terms[:3] + population_terms[:2])
    query = " AND ".join(f'"{t}"' for t in terms)
    return SourceSpecificQuery(
        source_name="clinical_trials_gov",
        query_string=query,
        parameters={
            "pageSize": 50,
            "format": "json",
        },
        terms_used=terms,
    )


def _build_cms_query(
    population_terms: list[str],
    intervention_terms: list[str],
    icd_codes: list[str],
) -> SourceSpecificQuery:
    """Compose a CMS Coverage search term."""
    terms = _dedup(intervention_terms[:2] + population_terms[:2])
    query = " ".join(terms)
    return SourceSpecificQuery(
        source_name="cms_coverage",
        query_string=query,
        parameters={"limit": 20},
        terms_used=terms + icd_codes[:5],
    )


# ---------------------------------------------------------------------------
# Term extraction helpers
# ---------------------------------------------------------------------------


def _extract_pico_terms(*fields: str | None) -> list[str]:
    """Split PICO text into token terms, preserving meaningful phrases."""
    tokens: list[str] = []
    for field in fields:
        if not field:
            continue
        # split on comma/semicolon, keep multi-word phrases
        for chunk in field.replace(";", ",").split(","):
            term = chunk.strip()
            if term and len(term) > 2:
                tokens.append(term)
    return _dedup(tokens) if tokens else [f for f in fields if f][:1]  # type: ignore[return-value]


def _extract_rxnorm_codes(phenotype: PhenotypeDefinition) -> list[str]:
    codes: list[str] = []
    for concept in phenotype.concepts:
        for mapping in concept.mappings:
            if mapping.terminology_system == "RxNorm":
                codes.append(mapping.code)
    return _dedup(codes)


def _extract_icd_codes(phenotype: PhenotypeDefinition) -> list[str]:
    codes: list[str] = []
    for concept in phenotype.concepts:
        for mapping in concept.mappings:
            if mapping.terminology_system == "ICD-10-CM":
                codes.append(mapping.code)
    return _dedup(codes)


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _deterministic_hash(
    question: ClinicalQuestion,
    phenotype: PhenotypeDefinition,
    source_queries: list[SourceSpecificQuery],
) -> str:
    """Produce a stable 16-hex-char hash of the query inputs, for cross-run comparison."""
    payload = json.dumps(
        {
            "question_id": question.id,
            "question_status": question.status,
            "phenotype_id": phenotype.id,
            "phenotype_version": phenotype.version,
            "phenotype_review_status": phenotype.review_status,
            "pico_population": question.pico.population,
            "pico_intervention": question.pico.intervention,
            "pico_outcomes": sorted(question.pico.outcomes),
            "source_queries": [
                {
                    "source": sq.source_name,
                    "query_string": sq.query_string,
                    "terms_used": sorted(sq.terms_used),
                }
                for sq in sorted(source_queries, key=lambda s: s.source_name)
            ],
        },
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()[:16]
