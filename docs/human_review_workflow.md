# Human Review Workflow (Phase 5)

## Overview

Phase 5 includes a human review service that records portfolio-author review decisions on generated evidence briefs. The system enforces valid status transitions and prohibits language that could imply clinical validation.

## Review Status Lifecycle

```
not_reviewed
     │
     ▼
  in_review ──────────► changes_requested ──► in_review (cycle)
     │
     ├──────────────► approved ──► in_review (re-review allowed)
     │
     └──────────────► rejected ──► in_review (re-review allowed)
```

## Valid Transitions

| From | To (allowed) |
|------|--------------|
| `not_reviewed` | `in_review` |
| `in_review` | `changes_requested`, `approved`, `rejected` |
| `changes_requested` | `in_review` |
| `approved` | `in_review` |
| `rejected` | `in_review` |

Any other transition raises `InvalidReviewTransitionError`.

## Reviewer Label Constraint

The `reviewer_label` field must not imply clinical approval:

**Prohibited:** "clinically approved", "clinical approval", "clinically validated"

**Allowed:** "Portfolio author review", "Technical review", "Peer review"

This is enforced by a Pydantic `field_validator` on `BriefReviewRecord.reviewer_label`.

## Audit Trail

Every review action creates a `BriefAuditRecord` entry in the `brief_audit_log` table. The audit log is append-only and includes:

- `event_type`: `created`, `review_started`, `changes_requested`, `approved`, `rejected`, `note_added`, `qa_run`, `content_changed`
- `actor`: the reviewer identifier
- `detail`: description of the action taken
- `timestamp`: ISO 8601 UTC timestamp

## Disclaimer Persistence

Review approval does not remove or suppress the brief's disclaimer. The disclaimer is immutable and always present in the serialized brief.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/briefs/{id}/review` | Submit a review action |
| GET | `/briefs/{id}/review-history` | Retrieve full review history |

## Streamlit UI

The Evidence Brief page (Page 6) includes a review form with:
- Status selector (only valid transitions shown)
- Label selector (pre-approved safe values)
- Optional reviewer note
- Reviewer ID input

Review actions are immediately reflected in the brief's `human_review_status`.
