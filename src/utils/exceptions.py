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
