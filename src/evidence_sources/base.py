"""Base Protocol and supporting types for all evidence source adapters.

Every adapter must implement the ``EvidenceSourceAdapter`` Protocol — call ``fetch()``
with a ``SourceSpecificQuery`` and receive a ``RawFetchResult``.  Errors must be raised
as typed domain exceptions (``RetrievalSourceError`` and its subclasses) — never silently
swallowed or returned as an empty list without an error record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from src.schemas.evidence import EvidenceSourceName, RawEvidenceRecord
from src.schemas.retrieval import RetrievalError, SourceSpecificQuery


@dataclass
class RawFetchResult:
    """Return type of every adapter's ``fetch()`` method."""

    source_name: EvidenceSourceName
    records: list[RawEvidenceRecord] = field(default_factory=list)
    errors: list[RetrievalError] = field(default_factory=list)
    cache_hit: bool = False
    duration_ms: int | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class EvidenceSourceAdapter(Protocol):
    """Protocol that every evidence source adapter must satisfy."""

    source_name: EvidenceSourceName

    def fetch(self, query: SourceSpecificQuery, run_id: str) -> RawFetchResult:
        """Retrieve raw records for the given source-specific query.

        Callers must catch ``RetrievalSourceError`` subclasses and record them in a
        ``RetrievalError``; they must NOT catch bare ``Exception`` and discard it.
        """
        ...

    def ping(self) -> bool:
        """Return True if the source is reachable (offline adapters always return True)."""
        ...
