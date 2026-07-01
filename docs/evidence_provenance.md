# Evidence Provenance

## Purpose

Every evidence retrieval run produces a complete, auditable provenance chain from the original clinical question through to the final ranked record set. This document describes the provenance fields, their meaning, and how to interpret them.

---

## Provenance Chain

```
ClinicalQuestion (approved)
  └─ PhenotypeDefinition (reviewed)
       └─ EvidenceQuery (deterministic, hash-identified)
            └─ RetrievalRun
                 ├─ RetrievalProvenance      (run-level)
                 ├─ RawEvidenceRecord[]      (source-level)
                 └─ EvidenceRecord[]         (record-level)
                      └─ EvidenceTag[]       (tag-level)
```

---

## EvidenceQuery

```python
class EvidenceQuery:
    id: str                  # UUID
    question_id: str         # ClinicalQuestion.id
    phenotype_id: str        # PhenotypeDefinition.id
    phenotype_version: str   # PhenotypeDefinition.version
    query_hash: str          # SHA-256 of canonical query JSON (16 hex chars)
    sources: list[EvidenceSourceName]
    pico_terms: dict[str, list[str]]   # population/intervention/comparator/outcome keywords
    created_at: datetime
```

The `query_hash` is the fingerprint of the query inputs. The same question + phenotype version + sources always yields the same `query_hash`, making retrieval reproducible.

---

## RetrievalProvenance

```python
class RetrievalProvenance:
    run_id: str
    query_hash: str                          # must match EvidenceQuery.query_hash
    retrieval_mode: str                      # "offline_fixture" | "live"
    sources_queried: list[str]
    fixture_manifest_versions: dict[str, str]  # {source_name: manifest_version}
    data_authenticity_note: str
    retrieved_at: datetime
```

`fixture_manifest_versions` records the exact version of each fixture file used. If a fixture is updated, all prior runs retain their original version string, preserving the historical provenance.

`data_authenticity_note` contains the canonical statement:

> "Evidence content is real, publicly available source data from PubMed, ClinicalTrials.gov, and CMS Coverage. This application presents source records as retrieved; it does not synthesize, modify, or generate clinical content."

---

## RawEvidenceRecord

```python
class RawEvidenceRecord:
    id: str                          # raw-{source}-{identifier}-{content_hash}
    source_name: EvidenceSourceName
    source_identifier: str
    content_hash: str                # SHA-256 of payload JSON (16 hex chars)
    fetched_at: datetime
    is_fixture_data: bool
    fixture_manifest_version: str | None
    raw_payload: dict[str, Any]      # verbatim source payload, never modified
```

`content_hash` is computed over the raw payload JSON with `sort_keys=True`. It is **never recomputed** during normalization — it travels through the pipeline unchanged as a stable record fingerprint.

---

## EvidenceRecord (normalized)

```python
class EvidenceRecord:
    id: str              # ev-{source}-{identifier}-{content_hash}
    retrieval_run_id: str
    raw_record_id: str   # links back to the RawEvidenceRecord
    content_hash: str    # same hash as RawEvidenceRecord.content_hash
    is_fixture_data: bool
    ...
```

`id`, `raw_record_id`, and `content_hash` create a traceable link from any normalized record back to its raw source payload.

---

## EvidenceTag

```python
class EvidenceTag:
    tag: str        # e.g. "intervention:sglt2_class"
    dimension: str  # e.g. "intervention"
    rule_id: str    # e.g. "INT-001" — identifies which keyword rule fired
```

`rule_id` makes tag assignments auditable: given a tag, you can look up the keyword rule that produced it. Tag rules are defined in `src/evidence/metatagging.py` and are version-stable for a given release.

---

## Interpreting `is_fixture_data`

| `is_fixture_data` | `fixture_manifest_version` | Meaning |
|---|---|---|
| `True` | `"1.0.0"` | Record came from the versioned offline fixture. |
| `False` | `None` | Record was fetched live from the source API at retrieval time. |

Because fixture data may be a snapshot from a specific date, the `fixture_manifest_version` should be checked against the manifest's `generated_at` field to understand the recency of the source snapshot.

---

## Deduplication and Cross-Source Note

Deduplication is **within-source only**. If two records from the same source have the same content hash, only one is retained and the other's ID is recorded in `EvidenceRecord.duplicate_of`.

Cross-source relationships (e.g. a PubMed article that reports results from a ClinicalTrials.gov study) are logged as informational notes in `EvidenceDeduplicationResult.cross_source_relationships`. These records are **never merged** automatically — they remain as separate, independent records.

---

## Audit Trail Summary

For any evidence record, the full audit trail is:

1. `EvidenceRecord.retrieval_run_id` → `RetrievalRun.run_id`
2. `RetrievalRun` → `RetrievalProvenance` (fixture versions, retrieval mode, query hash)
3. `EvidenceRecord.raw_record_id` → `RawEvidenceRecord` (verbatim payload)
4. `RetrievalRun.query` → `EvidenceQuery` (PICO terms, source list, question/phenotype IDs)
5. `EvidenceQuery.question_id` → `ClinicalQuestion` (original NL question)
6. `EvidenceQuery.phenotype_id` + `.phenotype_version` → `PhenotypeDefinition`
