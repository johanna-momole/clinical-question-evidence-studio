"""FHIR ingestion service: loads datasets, normalizes, and stores to DuckDB.

Idempotent: re-ingesting the same dataset_id wipes and reloads all tables for that dataset.
All data is synthetic; no real patient data is processed.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import duckdb

from src.fhir.loader import load_directory, load_file
from src.fhir.normalizer import NormalizedDataset, normalize
from src.schemas.fhir import (
    FHIRIngestionError,
    FHIRIngestionResult,
    FHIRResourceSummary,
    SyntheticDatasetInfo,
)
from src.utils.exceptions import DatasetNotFoundError

_FIXTURES_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "fixtures" / "fhir"


# ---------------------------------------------------------------------------
# Dataset catalog
# ---------------------------------------------------------------------------

_DATASET_CATALOG: dict[str, Path] = {
    "synthetic-cohort-v1": _FIXTURES_ROOT / "synthetic_cohort_v1",
}


def list_datasets() -> list[SyntheticDatasetInfo]:
    """Return metadata for all registered synthetic FHIR datasets."""
    result = []
    for dataset_id, path in _DATASET_CATALOG.items():
        info_file = path / "dataset_info.json"
        if info_file.exists():
            raw = json.loads(info_file.read_text(encoding="utf-8"))
            result.append(
                SyntheticDatasetInfo(
                    dataset_id=dataset_id,
                    name=raw.get("name", dataset_id),
                    description=raw.get("description", ""),
                    patient_count=raw.get("patient_count", 0),
                )
            )
        else:
            result.append(
                SyntheticDatasetInfo(
                    dataset_id=dataset_id,
                    name=dataset_id,
                    description="Bundled synthetic FHIR dataset",
                    patient_count=0,
                )
            )
    return result


# ---------------------------------------------------------------------------
# DuckDB schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS ingestion_provenance (
    run_id          VARCHAR PRIMARY KEY,
    dataset_id      VARCHAR NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL,
    patient_count   INTEGER NOT NULL,
    total_resources INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestion_errors (
    run_id        VARCHAR NOT NULL,
    dataset_id    VARCHAR NOT NULL,
    file_name     VARCHAR,
    resource_id   VARCHAR,
    resource_type VARCHAR,
    error_type    VARCHAR NOT NULL,
    message       TEXT NOT NULL,
    is_fatal      BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS patients (
    run_id           VARCHAR NOT NULL,
    dataset_id       VARCHAR NOT NULL,
    patient_id       VARCHAR NOT NULL,
    birth_date       DATE,
    sex              VARCHAR,
    race             VARCHAR,
    ethnicity        VARCHAR,
    deceased         BOOLEAN NOT NULL DEFAULT FALSE,
    deceased_date    DATE,
    source_resource_id VARCHAR NOT NULL,
    PRIMARY KEY (run_id, patient_id)
);

CREATE TABLE IF NOT EXISTS conditions (
    run_id              VARCHAR NOT NULL,
    dataset_id          VARCHAR NOT NULL,
    patient_id          VARCHAR NOT NULL,
    condition_id        VARCHAR NOT NULL,
    code                VARCHAR NOT NULL,
    code_system         VARCHAR,
    display             VARCHAR,
    onset_date          DATE,
    recorded_date       DATE,
    clinical_status     VARCHAR,
    verification_status VARCHAR,
    source_resource_id  VARCHAR NOT NULL,
    PRIMARY KEY (run_id, condition_id)
);

CREATE TABLE IF NOT EXISTS encounters (
    run_id           VARCHAR NOT NULL,
    dataset_id       VARCHAR NOT NULL,
    patient_id       VARCHAR NOT NULL,
    encounter_id     VARCHAR NOT NULL,
    encounter_class  VARCHAR,
    start_date       DATE,
    end_date         DATE,
    status           VARCHAR,
    source_resource_id VARCHAR NOT NULL,
    PRIMARY KEY (run_id, encounter_id)
);

CREATE TABLE IF NOT EXISTS observations (
    run_id              VARCHAR NOT NULL,
    dataset_id          VARCHAR NOT NULL,
    patient_id          VARCHAR NOT NULL,
    observation_id      VARCHAR NOT NULL,
    code                VARCHAR NOT NULL,
    code_system         VARCHAR,
    display             VARCHAR,
    value_numeric       DOUBLE,
    value_text          VARCHAR,
    unit                VARCHAR,
    effective_date      DATE,
    status              VARCHAR,
    ref_range_low       DOUBLE,
    ref_range_high      DOUBLE,
    source_resource_id  VARCHAR NOT NULL,
    PRIMARY KEY (run_id, observation_id)
);

CREATE TABLE IF NOT EXISTS medications (
    run_id               VARCHAR NOT NULL,
    dataset_id           VARCHAR NOT NULL,
    patient_id           VARCHAR NOT NULL,
    medication_record_id VARCHAR NOT NULL,
    code                 VARCHAR NOT NULL,
    code_system          VARCHAR,
    display              VARCHAR,
    start_date           DATE,
    end_date             DATE,
    status               VARCHAR,
    source_resource_type VARCHAR NOT NULL,
    source_resource_id   VARCHAR NOT NULL,
    PRIMARY KEY (run_id, medication_record_id)
);

CREATE TABLE IF NOT EXISTS procedures (
    run_id             VARCHAR NOT NULL,
    dataset_id         VARCHAR NOT NULL,
    patient_id         VARCHAR NOT NULL,
    procedure_id       VARCHAR NOT NULL,
    code               VARCHAR,
    code_system        VARCHAR,
    display            VARCHAR,
    performed_date     DATE,
    status             VARCHAR,
    source_resource_id VARCHAR NOT NULL,
    PRIMARY KEY (run_id, procedure_id)
);
"""


class FHIRService:
    """Singleton FHIR ingestion service backed by an in-process DuckDB database."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = duckdb.connect(db_path)
        self._conn.execute(_DDL)
        # Track last successful run per dataset for idempotent re-use
        self._last_run: dict[str, FHIRIngestionResult] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self, dataset_id: str, force_reload: bool = False) -> FHIRIngestionResult:
        """Ingest a registered synthetic FHIR dataset into DuckDB.

        If already loaded and force_reload=False, returns the cached result.
        """
        if not force_reload and dataset_id in self._last_run:
            return self._last_run[dataset_id]

        path = _DATASET_CATALOG.get(dataset_id)
        if path is None:
            raise DatasetNotFoundError(f"Dataset '{dataset_id}' is not registered")

        run_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        if path.is_dir():
            load_result = load_directory(path)
        elif path.is_file():
            load_result = load_file(path)
        else:
            raise DatasetNotFoundError(f"Dataset path does not exist: {path}")

        dataset = normalize(load_result.resources)
        all_errors: list[FHIRIngestionError] = load_result.errors + dataset.warnings

        # Delete any previous data for this dataset_id (idempotent reload)
        for table in [
            "ingestion_provenance",
            "ingestion_errors",
            "patients",
            "conditions",
            "encounters",
            "observations",
            "medications",
            "procedures",
        ]:
            self._conn.execute(f"DELETE FROM {table} WHERE dataset_id = ?", [dataset_id])

        self._store(run_id, dataset_id, now, dataset, all_errors)

        resource_summaries = [
            FHIRResourceSummary(resource_type="Patient", count=len(dataset.patients)),
            FHIRResourceSummary(resource_type="Condition", count=len(dataset.conditions)),
            FHIRResourceSummary(resource_type="Encounter", count=len(dataset.encounters)),
            FHIRResourceSummary(resource_type="Observation", count=len(dataset.observations)),
            FHIRResourceSummary(resource_type="Medication", count=len(dataset.medications)),
            FHIRResourceSummary(resource_type="Procedure", count=len(dataset.procedures)),
        ]

        warnings = [e.message for e in all_errors if not e.is_fatal]

        ingestion_result = FHIRIngestionResult(
            run_id=run_id,
            dataset_id=dataset_id,
            ingestion_timestamp=now,
            resource_counts=resource_summaries,
            patient_count=len(dataset.patients),
            warnings=warnings,
            errors=[e for e in all_errors if e.is_fatal],
        )
        self._last_run[dataset_id] = ingestion_result
        return ingestion_result

    def get_last_ingestion_result(self, dataset_id: str) -> FHIRIngestionResult | None:
        """Return the most recent ingestion result for a dataset, or None if never ingested."""
        return self._last_run.get(dataset_id)

    def get_dataset(self, dataset_id: str) -> NormalizedDataset:
        """Return a NormalizedDataset reconstructed from DuckDB for the last ingestion run.

        Triggers ingestion if not yet loaded.
        """
        if dataset_id not in self._last_run:
            self.ingest(dataset_id)
        run_id = self._last_run[dataset_id].run_id
        return self._reconstruct(run_id, dataset_id)

    def last_run_id(self, dataset_id: str) -> str | None:
        result = self._last_run.get(dataset_id)
        return result.run_id if result else None

    # ------------------------------------------------------------------
    # Storage helpers
    # ------------------------------------------------------------------

    def _store(
        self,
        run_id: str,
        dataset_id: str,
        ingested_at: datetime,
        dataset: NormalizedDataset,
        errors: list[FHIRIngestionError],
    ) -> None:
        total = (
            len(dataset.patients)
            + len(dataset.conditions)
            + len(dataset.encounters)
            + len(dataset.observations)
            + len(dataset.medications)
            + len(dataset.procedures)
        )
        self._conn.execute(
            "INSERT INTO ingestion_provenance VALUES (?, ?, ?, ?, ?)",
            [run_id, dataset_id, ingested_at, len(dataset.patients), total],
        )
        for e in errors:
            self._conn.execute(
                "INSERT INTO ingestion_errors VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    run_id,
                    dataset_id,
                    e.file_name,
                    e.resource_id,
                    e.resource_type,
                    e.error_type,
                    e.message,
                    e.is_fatal,
                ],
            )
        for pt in dataset.patients:
            self._conn.execute(
                "INSERT OR IGNORE INTO patients VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    run_id,
                    dataset_id,
                    pt.patient_id,
                    pt.birth_date,
                    pt.sex,
                    pt.race,
                    pt.ethnicity,
                    pt.deceased,
                    pt.deceased_date,
                    pt.source_resource_id,
                ],
            )
        for c in dataset.conditions:
            self._conn.execute(
                "INSERT OR IGNORE INTO conditions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    run_id,
                    dataset_id,
                    c.patient_id,
                    c.condition_id,
                    c.code,
                    c.code_system,
                    c.display,
                    c.onset_date,
                    c.recorded_date,
                    c.clinical_status,
                    c.verification_status,
                    c.source_resource_id,
                ],
            )
        for enc in dataset.encounters:
            self._conn.execute(
                "INSERT OR IGNORE INTO encounters VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    run_id,
                    dataset_id,
                    enc.patient_id,
                    enc.encounter_id,
                    enc.encounter_class,
                    enc.start_date,
                    enc.end_date,
                    enc.status,
                    enc.source_resource_id,
                ],
            )
        for obs in dataset.observations:
            rr_low = obs.reference_range.low if obs.reference_range else None
            rr_high = obs.reference_range.high if obs.reference_range else None
            self._conn.execute(
                "INSERT OR IGNORE INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    run_id,
                    dataset_id,
                    obs.patient_id,
                    obs.observation_id,
                    obs.code,
                    obs.code_system,
                    obs.display,
                    obs.value_numeric,
                    obs.value_text,
                    obs.unit,
                    obs.effective_date,
                    obs.status,
                    rr_low,
                    rr_high,
                    obs.source_resource_id,
                ],
            )
        for med in dataset.medications:
            self._conn.execute(
                "INSERT OR IGNORE INTO medications VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    run_id,
                    dataset_id,
                    med.patient_id,
                    med.medication_record_id,
                    med.code,
                    med.code_system,
                    med.display,
                    med.start_date,
                    med.end_date,
                    med.status,
                    med.source_resource_type,
                    med.source_resource_id,
                ],
            )
        for proc in dataset.procedures:
            self._conn.execute(
                "INSERT OR IGNORE INTO procedures VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    run_id,
                    dataset_id,
                    proc.patient_id,
                    proc.procedure_id,
                    proc.code,
                    proc.code_system,
                    proc.display,
                    proc.performed_date,
                    proc.status,
                    proc.source_resource_id,
                ],
            )

    def _reconstruct(self, run_id: str, dataset_id: str) -> NormalizedDataset:
        """Reconstruct a NormalizedDataset from DuckDB for a given run."""
        from src.fhir.normalizer import NormalizedDataset as ND
        from src.schemas.fhir import (
            NormalizedCondition,
            NormalizedEncounter,
            NormalizedMedication,
            NormalizedObservation,
            NormalizedPatient,
            ReferenceRange,
        )

        ds = ND()
        rows = self._conn.execute(
            "SELECT patient_id,birth_date,sex,race,ethnicity,deceased,deceased_date,source_resource_id "
            "FROM patients WHERE run_id=? AND dataset_id=?",
            [run_id, dataset_id],
        ).fetchall()
        for r in rows:
            ds.patients.append(
                NormalizedPatient(
                    patient_id=r[0],
                    birth_date=r[1],
                    sex=r[2],
                    race=r[3],
                    ethnicity=r[4],
                    deceased=bool(r[5]),
                    deceased_date=r[6],
                    source_resource_id=r[7],
                )
            )

        rows = self._conn.execute(
            "SELECT patient_id,condition_id,code,code_system,display,onset_date,recorded_date,"
            "clinical_status,verification_status,source_resource_id "
            "FROM conditions WHERE run_id=? AND dataset_id=?",
            [run_id, dataset_id],
        ).fetchall()
        for r in rows:
            ds.conditions.append(
                NormalizedCondition(
                    patient_id=r[0],
                    condition_id=r[1],
                    code=r[2],
                    code_system=r[3],
                    display=r[4],
                    onset_date=r[5],
                    recorded_date=r[6],
                    clinical_status=r[7],
                    verification_status=r[8],
                    source_resource_id=r[9],
                )
            )

        rows = self._conn.execute(
            "SELECT patient_id,encounter_id,encounter_class,start_date,end_date,status,source_resource_id "
            "FROM encounters WHERE run_id=? AND dataset_id=?",
            [run_id, dataset_id],
        ).fetchall()
        for r in rows:
            ds.encounters.append(
                NormalizedEncounter(
                    patient_id=r[0],
                    encounter_id=r[1],
                    encounter_class=r[2],
                    start_date=r[3],
                    end_date=r[4],
                    status=r[5],
                    source_resource_id=r[6],
                )
            )

        rows = self._conn.execute(
            "SELECT patient_id,observation_id,code,code_system,display,value_numeric,value_text,"
            "unit,effective_date,status,ref_range_low,ref_range_high,source_resource_id "
            "FROM observations WHERE run_id=? AND dataset_id=?",
            [run_id, dataset_id],
        ).fetchall()
        for r in rows:
            rr = (
                ReferenceRange(low=r[10], high=r[11])
                if (r[10] is not None or r[11] is not None)
                else None
            )
            ds.observations.append(
                NormalizedObservation(
                    patient_id=r[0],
                    observation_id=r[1],
                    code=r[2],
                    code_system=r[3],
                    display=r[4],
                    value_numeric=r[5],
                    value_text=r[6],
                    unit=r[7],
                    effective_date=r[8],
                    status=r[9],
                    reference_range=rr,
                    source_resource_id=r[12],
                )
            )

        rows = self._conn.execute(
            "SELECT patient_id,medication_record_id,code,code_system,display,start_date,end_date,"
            "status,source_resource_type,source_resource_id "
            "FROM medications WHERE run_id=? AND dataset_id=?",
            [run_id, dataset_id],
        ).fetchall()
        for r in rows:
            ds.medications.append(
                NormalizedMedication(
                    patient_id=r[0],
                    medication_record_id=r[1],
                    code=r[2],
                    code_system=r[3],
                    display=r[4],
                    start_date=r[5],
                    end_date=r[6],
                    status=r[7],
                    source_resource_type=r[8],
                    source_resource_id=r[9],
                )
            )

        return ds


@lru_cache(maxsize=1)
def get_fhir_service() -> FHIRService:
    """Singleton FHIR service backed by an in-process (non-persistent) DuckDB instance."""
    return FHIRService(db_path=":memory:")
