"""Phase 3 API tests for /fhir and /cohorts routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


class TestFHIRRoutes:
    def test_list_datasets(self) -> None:
        response = client.get("/fhir/datasets")
        assert response.status_code == 200
        data = response.json()
        assert "datasets" in data
        assert len(data["datasets"]) >= 1
        assert "synthetic" in data["note"].lower()

    def test_ingest_known_dataset(self) -> None:
        response = client.post("/fhir/ingest", json={"dataset_id": "synthetic-cohort-v1"})
        assert response.status_code == 200
        data = response.json()
        assert data["patient_count"] == 160
        assert data["dataset_id"] == "synthetic-cohort-v1"

    def test_ingest_unknown_dataset_404(self) -> None:
        response = client.post("/fhir/ingest", json={"dataset_id": "nonexistent-dataset"})
        assert response.status_code == 404

    def test_get_dataset_status_after_ingest(self) -> None:
        client.post("/fhir/ingest", json={"dataset_id": "synthetic-cohort-v1"})
        response = client.get("/fhir/datasets/synthetic-cohort-v1")
        assert response.status_code == 200

    def test_get_dataset_status_never_ingested_404(self) -> None:
        response = client.get("/fhir/datasets/never-touched-dataset-xyz")
        assert response.status_code == 404


class TestCohortRoutes:
    def test_run_cohort_requires_approval_by_default(self) -> None:
        response = client.post(
            "/cohorts/run",
            json={
                "phenotype_id": "pheno-sglt2-ckd-t2dm-001",
                "dataset_id": "synthetic-cohort-v1",
                "approve_for_demo": False,
            },
        )
        assert response.status_code == 422

    def test_run_cohort_with_approval_succeeds(self) -> None:
        response = client.post(
            "/cohorts/run",
            json={
                "phenotype_id": "pheno-sglt2-ckd-t2dm-001",
                "dataset_id": "synthetic-cohort-v1",
                "approve_for_demo": True,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["cohort_run"]["summary"]["final_cohort_count"] > 0
        assert "synthetic" in data["synthetic_data_notice"].lower()

    def test_run_cohort_unknown_phenotype_404(self) -> None:
        response = client.post(
            "/cohorts/run",
            json={
                "phenotype_id": "nonexistent-phenotype",
                "dataset_id": "synthetic-cohort-v1",
                "approve_for_demo": True,
            },
        )
        assert response.status_code == 404

    def test_get_cohort_run_by_id(self) -> None:
        run_response = client.post(
            "/cohorts/run",
            json={
                "phenotype_id": "pheno-sglt2-ckd-t2dm-001",
                "dataset_id": "synthetic-cohort-v1",
                "approve_for_demo": True,
            },
        )
        run_id = run_response.json()["cohort_run"]["run_id"]
        response = client.get(f"/cohorts/runs/{run_id}")
        assert response.status_code == 200
        assert response.json()["run_id"] == run_id

    def test_get_cohort_run_unknown_404(self) -> None:
        response = client.get("/cohorts/runs/nonexistent-run-id")
        assert response.status_code == 404

    def test_list_cohort_runs(self) -> None:
        client.post(
            "/cohorts/run",
            json={
                "phenotype_id": "pheno-sglt2-ckd-t2dm-001",
                "dataset_id": "synthetic-cohort-v1",
                "approve_for_demo": True,
            },
        )
        response = client.get("/cohorts/runs")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
        assert len(response.json()) >= 1

    def test_run_cohort_with_medication_filter_returns_warning(self) -> None:
        response = client.post(
            "/cohorts/run",
            json={
                "phenotype_id": "pheno-sglt2-ckd-t2dm-001",
                "dataset_id": "synthetic-cohort-v1",
                "approve_for_demo": True,
                "include_medication_exposure_filter": True,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["cohort_run"]["warnings"]) >= 1
