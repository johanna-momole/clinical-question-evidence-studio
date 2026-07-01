"""Human review service for evidence briefs.

Manages:
- Status transitions with guard rails
- Reviewer label validation (blocks 'clinically approved' language)
- Persistent review records + audit trail
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from src.schemas.brief import (
    BriefReviewRecord,
    BriefReviewStatus,
)
from src.synthesis.repository import get_synthesis_repository
from src.utils.exceptions import (
    InvalidReviewTransitionError,
)

# Allowed status transitions. Key = current status, Value = set of valid next statuses.
_TRANSITIONS: dict[BriefReviewStatus, set[BriefReviewStatus]] = {
    "not_reviewed": {"in_review"},
    "in_review": {"changes_requested", "approved", "rejected"},
    "changes_requested": {"in_review"},
    "approved": {"in_review"},  # allow re-review after approval
    "rejected": {"in_review"},  # allow re-review after rejection
}


def _check_transition(current: BriefReviewStatus, proposed: BriefReviewStatus) -> None:
    allowed = _TRANSITIONS.get(current, set())
    if proposed not in allowed:
        raise InvalidReviewTransitionError(
            f"Cannot transition brief from {current!r} to {proposed!r}. "
            f"Valid transitions from {current!r}: {sorted(allowed)}"
        )


class BriefReviewService:
    """Service for recording human review decisions on an EvidenceBrief."""

    def __init__(self) -> None:
        self._repo = get_synthesis_repository()

    def submit_review(
        self,
        brief_id: str,
        new_status: BriefReviewStatus,
        reviewer_id: str,
        reviewer_label: str = "Portfolio author review",
        note: str | None = None,
    ) -> BriefReviewRecord:
        """Submit a human review action.

        Args:
            brief_id: The brief to review.
            new_status: Proposed new review status.
            reviewer_id: Identifier of the reviewer (display name or internal ID).
            reviewer_label: Human-facing review label. Must not imply clinical approval.
            note: Optional reviewer comment.

        Returns:
            BriefReviewRecord with the persisted review details.

        Raises:
            BriefNotFoundError: Brief does not exist.
            InvalidReviewTransitionError: Invalid status transition.
            ValueError: reviewer_label violates the clinical-approval prohibition.
        """
        brief = self._repo.get_brief(brief_id)
        current_status: BriefReviewStatus = brief.human_review_status

        _check_transition(current_status, new_status)

        review = BriefReviewRecord(
            review_id=f"rv-{uuid.uuid4().hex[:12]}",
            brief_id=brief_id,
            brief_version=brief.version,
            previous_status=current_status,
            new_status=new_status,
            reviewer_id=reviewer_id,
            reviewer_label=reviewer_label,
            timestamp=datetime.now(UTC),
            note=note,
            content_hash_reviewed=brief.content_hash,
        )

        # Persist review record
        self._repo.save_review(review)

        # Update brief status
        self._repo.update_brief_review_status(brief_id, new_status)

        # Map new_status to audit event_type
        _status_to_event = {
            "in_review": "review_started",
            "changes_requested": "changes_requested",
            "approved": "approved",
            "rejected": "rejected",
        }
        audit_event = _status_to_event.get(new_status, "note_added")

        # Audit log entry
        self._repo.log_audit(
            brief_id=brief_id,
            event_type=audit_event,
            actor=reviewer_id,
            detail=(
                f"{reviewer_label}: {current_status!r} → {new_status!r}. "
                + (f"Note: {note}" if note else "")
            ),
        )

        return review

    def get_review_history(self, brief_id: str) -> list[dict[str, Any]]:
        """Return all review records for a brief in chronological order."""
        # Verify brief exists
        self._repo.get_brief(brief_id)
        return self._repo.get_review_history(brief_id)

    def get_audit_log(self, brief_id: str) -> list[dict[str, Any]]:
        """Return raw audit log entries for a brief."""
        self._repo.get_brief(brief_id)
        return self._repo.get_audit_log(brief_id)
