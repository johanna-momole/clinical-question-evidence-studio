"""Consolidated schema exports for Clinical Question-Evidence Studio."""

from src.schemas.cohort import (
    CohortAttrition,
    CohortConfiguration,
    CohortProvenance,
    CohortRun,
    CohortStep,
    CohortSummary,
    DemographicSummary,
    ExclusionSummary,
    MissingnessReport,
)
from src.schemas.evidence import (
    ClinicalTrialRecord,
    CoverageRecord,
    EvidenceDeduplicationResult,
    EvidenceRecord,
    EvidenceSearchResult,
    EvidenceTag,
    NormalizedEvidenceRecord,
    PublicationRecord,
    RawEvidenceRecord,
)
from src.schemas.exports import ExportFormat, ExportManifest
from src.schemas.fhir import (
    FHIRIngestionError,
    FHIRIngestionRequest,
    FHIRIngestionResult,
    FHIRResourceSummary,
    NormalizedCondition,
    NormalizedEncounter,
    NormalizedMedication,
    NormalizedObservation,
    NormalizedPatient,
    NormalizedProcedure,
    ReferenceRange,
    SyntheticDatasetInfo,
)
from src.schemas.parsing import (
    ParseProvenance,
    ParseResult,
    PhenotypeAuditRecord,
    PhenotypeResult,
)
from src.schemas.phenotype import (
    ClinicalConcept,
    FHIRResourceMapping,
    PhenotypeDefinition,
    PhenotypeRule,
    TerminologyMapping,
)
from src.schemas.qa import ProvenanceRecord, QAResult, QASummary
from src.schemas.question import AmbiguityFlag, ClinicalQuestion, PICOFramework
from src.schemas.retrieval import (
    EvidenceQuery,
    EvidenceSourceStatus,
    RetrievalError,
    RetrievalProvenance,
    RetrievalRequest,
    RetrievalRun,
    SourceSpecificQuery,
)
from src.schemas.synthesis import Citation, EvidenceBrief, GeneratedClaim
from src.schemas.terminology_verification import (
    TerminologyVerificationAuditRecord,
    TerminologyVerificationRequest,
    TerminologyVerificationResult,
)

__all__ = [
    # Question
    "AmbiguityFlag",
    "ClinicalQuestion",
    "PICOFramework",
    # Phenotype
    "ClinicalConcept",
    "FHIRResourceMapping",
    "PhenotypeDefinition",
    "PhenotypeRule",
    "TerminologyMapping",
    # Cohort
    "CohortAttrition",
    "CohortConfiguration",
    "CohortProvenance",
    "CohortRun",
    "CohortStep",
    "CohortSummary",
    "DemographicSummary",
    "ExclusionSummary",
    "MissingnessReport",
    # FHIR
    "FHIRIngestionError",
    "FHIRIngestionRequest",
    "FHIRIngestionResult",
    "FHIRResourceSummary",
    "NormalizedCondition",
    "NormalizedEncounter",
    "NormalizedMedication",
    "NormalizedObservation",
    "NormalizedPatient",
    "NormalizedProcedure",
    "ReferenceRange",
    "SyntheticDatasetInfo",
    # Evidence (Phase 1/2 base + Phase 4 extensions)
    "ClinicalTrialRecord",
    "CoverageRecord",
    "EvidenceDeduplicationResult",
    "EvidenceRecord",
    "EvidenceSearchResult",
    "EvidenceTag",
    "NormalizedEvidenceRecord",
    "PublicationRecord",
    "RawEvidenceRecord",
    # Retrieval (Phase 4)
    "EvidenceQuery",
    "EvidenceSourceStatus",
    "RetrievalError",
    "RetrievalProvenance",
    "RetrievalRequest",
    "RetrievalRun",
    "SourceSpecificQuery",
    # Terminology verification (Phase 4)
    "TerminologyVerificationAuditRecord",
    "TerminologyVerificationRequest",
    "TerminologyVerificationResult",
    # QA
    "ProvenanceRecord",
    "QAResult",
    "QASummary",
    # Synthesis
    "Citation",
    "EvidenceBrief",
    "GeneratedClaim",
    # Parsing / provenance
    "ParseProvenance",
    "ParseResult",
    "PhenotypeAuditRecord",
    "PhenotypeResult",
    # Exports
    "ExportFormat",
    "ExportManifest",
]
