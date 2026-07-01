"""Audit log helpers for the brief review workflow."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from src.schemas.brief import BriefAuditRecord


def make_audit_record(
    brief_id: str,
    event_type: str,
    actor: str,
    detail: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> BriefAuditRecord:
    return BriefAuditRecord(
        audit_id=f"audit-{uuid.uuid4().hex[:12]}",
        brief_id=brief_id,
        event_type=event_type,  # type: ignore[arg-type]
        actor=actor,
        timestamp=datetime.now(UTC),
        detail=detail,
        metadata=metadata or {},
    )
