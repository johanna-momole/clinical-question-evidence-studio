"""Domain exceptions for Clinical Question-Evidence Studio."""


class UnsupportedQuestionError(ValueError):
    """Raised when a question does not match any curated demo question."""


class PhenotypeNotFoundError(ValueError):
    """Raised when no phenotype fixture exists for the given question."""


class ApprovalRequiredError(ValueError):
    """Raised when an operation requires an approved question but receives a draft."""


class FixtureLoadError(RuntimeError):
    """Raised when a fixture file cannot be loaded or parsed."""


class UnapprovedPhenotypeError(ValueError):
    """Raised when cohort execution is attempted against an unapproved phenotype."""


class UnresolvedConceptError(ValueError):
    """Raised when a required phenotype rule references a concept with no usable mapping."""


class CohortExecutionError(RuntimeError):
    """Raised when cohort execution fails for reasons other than approval/resolution gates."""


class DatasetNotFoundError(ValueError):
    """Raised when a requested synthetic FHIR dataset_id is not registered."""


class CohortRunNotFoundError(ValueError):
    """Raised when a requested cohort run_id has no saved record."""


# ── Evidence retrieval exceptions ──────────────────────────────────────────────


class EvidenceQueryBuildError(ValueError):
    """Raised when query-builder preconditions are not met (unapproved question/phenotype)."""


class RetrievalRunNotFoundError(ValueError):
    """Raised when a requested evidence retrieval run_id has no saved record."""


class EvidenceNotFoundError(ValueError):
    """Raised when a requested evidence_id has no saved record."""


class RetrievalSourceError(RuntimeError):
    """Base for errors from an individual evidence-source adapter."""


class RetrievalTimeoutError(RetrievalSourceError):
    """Raised when an adapter request times out."""


class RetrievalRateLimitError(RetrievalSourceError):
    """Raised when an adapter receives a rate-limit response."""


class RetrievalParseError(RetrievalSourceError):
    """Raised when an adapter cannot parse a well-formed API or fixture response."""


class FixtureManifestError(RuntimeError):
    """Raised when an evidence fixture or its manifest file cannot be loaded or parsed."""


class UnsupportedSourceError(ValueError):
    """Raised when a requested evidence source name is not registered."""
