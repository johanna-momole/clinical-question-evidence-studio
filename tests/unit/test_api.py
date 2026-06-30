"""Unit tests for the FastAPI application.

Uses FastAPI's TestClient (backed by httpx) so no live server is required.
Tests the health endpoint and basic API metadata — no external dependencies.
"""

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_200(self) -> None:
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_status_is_ok(self) -> None:
        data = client.get("/health").json()
        assert data["status"] == "ok"

    def test_health_contains_required_fields(self) -> None:
        data = client.get("/health").json()
        required = {"status", "timestamp", "version", "demo_mode", "environment"}
        assert required.issubset(data.keys())

    def test_health_version_is_string(self) -> None:
        data = client.get("/health").json()
        assert isinstance(data["version"], str)
        assert len(data["version"]) > 0

    def test_health_demo_mode_is_bool(self) -> None:
        data = client.get("/health").json()
        assert isinstance(data["demo_mode"], bool)

    def test_health_timestamp_is_iso_string(self) -> None:
        data = client.get("/health").json()
        ts = data["timestamp"]
        assert isinstance(ts, str)
        assert "T" in ts  # ISO 8601 format


class TestInfoEndpoint:
    def test_info_returns_200(self) -> None:
        response = client.get("/info")
        assert response.status_code == 200

    def test_info_contains_disclaimer(self) -> None:
        data = client.get("/info").json()
        assert "disclaimer" in data
        assert "synthetic" in data["disclaimer"].lower()

    def test_info_endpoints_list_not_empty(self) -> None:
        data = client.get("/info").json()
        assert isinstance(data["endpoints"], list)
        assert len(data["endpoints"]) > 0

    def test_health_endpoint_listed_as_implemented(self) -> None:
        data = client.get("/info").json()
        health_entry = next((e for e in data["endpoints"] if e["path"] == "/health"), None)
        assert health_entry is not None
        assert health_entry["status"] == "implemented"


class TestOpenAPIDoc:
    def test_openapi_schema_accessible(self) -> None:
        response = client.get("/openapi.json")
        assert response.status_code == 200

    def test_docs_page_accessible(self) -> None:
        response = client.get("/docs")
        assert response.status_code == 200

    def test_redoc_page_accessible(self) -> None:
        response = client.get("/redoc")
        assert response.status_code == 200


class TestNotFoundBehavior:
    def test_unknown_route_returns_404(self) -> None:
        response = client.get("/nonexistent-route")
        assert response.status_code == 404
