# Source Adapter Contract

## Overview

Every evidence source adapter must implement the `BaseEvidenceAdapter` interface defined in `src/evidence_sources/base.py`. This contract ensures all adapters can be used interchangeably by the `EvidenceService` pipeline.

---

## Interface

```python
class BaseEvidenceAdapter(ABC):
    @abstractmethod
    def fetch(
        self,
        query: EvidenceQuery,
        max_results: int = 50,
        offline_only: bool = True,
    ) -> list[RawEvidenceRecord]: ...

    @abstractmethod
    def ping(self) -> bool: ...

    @property
    @abstractmethod
    def source_name(self) -> EvidenceSourceName: ...
```

### `fetch(query, max_results, offline_only)`

- Returns a list of `RawEvidenceRecord` objects. The list may be empty.
- If `offline_only=True`, only fixture data is used. If the fixture does not exist or is unreadable, a `FixtureManifestError` is raised.
- If `offline_only=False` and live retrieval fails, a `RetrievalParseError` (or subclass) is raised, which the service converts into a `RetrievalError` entry on `EvidenceSourceStatus`.
- Raw payloads are stored verbatim in `RawEvidenceRecord.raw_payload`. They are never modified.

### `ping()`

- Returns `True` if the adapter is reachable (for live adapters: successful HTTP health check; for offline adapters: fixture directory exists).
- Used by the `/evidence/sources` API endpoint to show source availability.

### `source_name`

- A string literal matching one of the values in `EvidenceSourceName` (Literal type): `"pubmed"`, `"clinical_trials_gov"`, `"cms_coverage"`.

---

## RawEvidenceRecord Fields

All adapters must populate these fields on each returned record:

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Unique ID: `raw-{source}-{identifier}-{content_hash}` |
| `source_name` | `EvidenceSourceName` | Must match `adapter.source_name` |
| `source_identifier` | `str` | Source-native ID (PMID, NCT ID, etc.) |
| `content_hash` | `str` | SHA-256 of canonical payload JSON, hex-truncated to 16 chars |
| `fetched_at` | `datetime` | UTC timestamp of retrieval |
| `is_fixture_data` | `bool` | `True` if from offline fixture; `False` if from live API |
| `fixture_manifest_version` | `str \| None` | Set when `is_fixture_data=True`; `None` for live |
| `raw_payload` | `dict[str, Any]` | Verbatim source payload (PubMed article dict, ClinicalTrials study dict, etc.) |

---

## Fixture File Contract

Every offline adapter reads from a fixture directory with this structure:

```
data/fixtures/evidence/{source_name}/
  manifest.json
  {index_file}
```

`manifest.json` must contain:

```json
{
  "version": "1.0.0",
  "generated_at": "2024-01-15T00:00:00Z",
  "index_file": "articles.json",
  "record_count": 12,
  "description": "..."
}
```

The `version` field is stored as `fixture_manifest_version` on every `RawEvidenceRecord` produced from this fixture. Updating a fixture **must** increment `version` so cached results from an older version are not served alongside newer ones.

---

## Content Hash

Content hashes are computed identically across all adapters:

```python
import hashlib, json

payload_str = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
content_hash = hashlib.sha256(payload_str.encode()).hexdigest()[:16]
```

This guarantees that:
- The same raw payload always produces the same hash.
- The `evidence_id` for a normalized record (`ev-{source}-{identifier}-{content_hash}`) is stable and idempotent across re-runs.

---

## Error Handling

Adapters must NOT silently swallow errors. The following exception types are used:

| Exception | When |
|---|---|
| `FixtureManifestError` | Fixture file or manifest is missing or unparseable |
| `RetrievalParseError` | Live API returned an unexpected response structure |
| `RetrievalNetworkError` | Live API returned a non-2xx status or connection failed |

The `EvidenceService` catches these exceptions per-adapter and records them as `RetrievalError` entries on `EvidenceSourceStatus.errors`. A `RetrievalError` with `is_fatal_for_source=True` means the adapter contributed zero records for this run.

---

## Adding a New Adapter

1. Create `src/evidence_sources/{source}.py` implementing `BaseEvidenceAdapter`.
2. Add offline fixtures under `data/fixtures/evidence/{source_name}/`.
3. Register the adapter in `EvidenceService._build_adapters()`.
4. Add the new source name to `EvidenceSourceName` in `src/schemas/evidence.py`.
5. Write unit tests covering: fixture load, content hash computation, normalization of at least one real record, and empty-result behavior.
6. Live tests must be decorated `@pytest.mark.live` and excluded from the default test suite.
