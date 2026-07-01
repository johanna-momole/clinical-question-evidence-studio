"""Same-source deduplication for evidence records.

Rules:
  - Deduplication is performed only WITHIN each source (pubmed, clinical_trials_gov,
    cms_coverage) — NEVER cross-source by title similarity alone.
  - Two records are duplicates if they share the same content_hash (exact same raw payload)
    OR the same source-native identifier within the same source.
  - Cross-source relationships (e.g., a trial and its published result) are recorded in
    EvidenceDeduplicationResult.cross_source_relationships as informational links only.
    The records themselves are never merged or deleted.
  - The canonical record in a duplicate group is the first one encountered (stable ordering).

Callers must NOT cross-merge records across sources by title similarity — this is
explicitly prohibited by the Phase 4 spec to preserve source attribution integrity.
"""

from __future__ import annotations

from collections import defaultdict

from src.schemas.evidence import EvidenceDeduplicationResult, EvidenceRecord


def deduplicate(
    records: list[EvidenceRecord],
    run_id: str,
) -> tuple[list[EvidenceRecord], EvidenceDeduplicationResult]:
    """Remove same-source duplicates and return (deduplicated_records, dedup_result).

    Returns all records that are NOT duplicates, marking the ``duplicate_of`` field
    on removed records is NOT done here — callers who want audit trails should persist
    the full pre-dedup set and the EvidenceDeduplicationResult separately.
    """
    # Group by (source_name, identifier) and by (source_name, content_hash)
    # A record is a duplicate if any other record from the same source shares its
    # identifier or content_hash AND comes earlier in the list.
    seen_by_id: dict[tuple[str | None, str], str] = {}  # (source, identifier) -> first record id
    seen_by_hash: dict[
        tuple[str | None, str], str
    ] = {}  # (source, content_hash) -> first record id
    duplicate_groups: dict[str, list[str]] = defaultdict(list)
    result_records: list[EvidenceRecord] = []
    removed_ids: set[str] = set()

    for rec in records:
        source = rec.source_name
        id_key = (source, rec.identifier)
        hash_key = (source, rec.content_hash) if rec.content_hash else None

        is_dup = False
        canonical_id: str | None = None

        if id_key in seen_by_id:
            canonical_id = seen_by_id[id_key]
            is_dup = True
        elif hash_key and hash_key in seen_by_hash:
            canonical_id = seen_by_hash[hash_key]
            is_dup = True

        if is_dup and canonical_id:
            duplicate_groups[canonical_id].append(rec.id)
            removed_ids.add(rec.id)
        else:
            seen_by_id[id_key] = rec.id
            if hash_key:
                seen_by_hash[hash_key] = rec.id
            result_records.append(rec)

    dup_group_list = [[canonical_id] + dups for canonical_id, dups in duplicate_groups.items()]

    # Cross-source relationships: link PubMed records with matching trial NCT IDs
    cross_source = _find_cross_source_relationships(result_records)

    dedup_result = EvidenceDeduplicationResult(
        run_id=run_id,
        total_records=len(records),
        duplicate_groups=dup_group_list,
        duplicates_removed=len(removed_ids),
        cross_source_relationships=cross_source,
    )
    return result_records, dedup_result


def _find_cross_source_relationships(
    records: list[EvidenceRecord],
) -> list[list[str]]:
    """Identify likely cross-source relationships (e.g., a trial and its published result).

    Returns list of [record_id_a, record_id_b, relationship_type] triples.
    These are INFORMATIONAL ONLY — records are never merged.
    """
    from src.schemas.evidence import ClinicalTrialRecord, PublicationRecord

    relationships: list[list[str]] = []

    ct_records: list[ClinicalTrialRecord] = [
        r for r in records if isinstance(r, ClinicalTrialRecord)
    ]
    pub_records: list[PublicationRecord] = [r for r in records if isinstance(r, PublicationRecord)]

    for trial in ct_records:
        trial_title_words = set(_title_tokens(trial.title))
        for pub in pub_records:
            pub_title_words = set(_title_tokens(pub.title))
            # Overlap-based matching is used ONLY for cross-source relationship hints,
            # not for deduplication or merging. Require high overlap to reduce false matches.
            overlap = trial_title_words & pub_title_words
            if len(overlap) >= 3 and len(overlap) / max(len(trial_title_words), 1) >= 0.4:
                relationships.append([trial.id, pub.id, "likely_trial_publication_pair"])

    return relationships


def _title_tokens(title: str) -> list[str]:
    stopwords = {
        "a",
        "an",
        "the",
        "of",
        "in",
        "for",
        "and",
        "or",
        "with",
        "to",
        "on",
        "at",
        "by",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "study",
        "trial",
        "patients",
        "diabetes",
        "mellitus",
        "type",
    }
    return [w.lower() for w in title.split() if len(w) > 2 and w.lower() not in stopwords]
