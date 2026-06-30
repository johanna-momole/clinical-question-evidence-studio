"""Phase 2 API endpoint tests — questions and phenotypes routes."""

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


class TestQuestionsParseEndpoint:
    def test_parse_q1_by_id_returns_200(self) -> None:
        response = client.post(
            "/questions/parse",
            json={"text": "", "question_id": "q-sglt2-ckd-t2dm-001"},
        )
        assert response.status_code == 200

    def test_parse_q1_is_supported_question(self) -> None:
        data = client.post(
            "/questions/parse",
            json={"text": "", "question_id": "q-sglt2-ckd-t2dm-001"},
        ).json()
        assert data["is_supported_question"] is True

    def test_parse_q1_returns_run_id(self) -> None:
        data = client.post(
            "/questions/parse",
            json={"text": "", "question_id": "q-sglt2-ckd-t2dm-001"},
        ).json()
        assert "run_id" in data
        assert len(data["run_id"]) == 36

    def test_parse_unsupported_text_returns_is_supported_false(self) -> None:
        data = client.post(
            "/questions/parse",
            json={"text": "What causes hypertension?"},
        ).json()
        assert data["is_supported_question"] is False

    def test_parse_with_no_text_or_id_returns_422(self) -> None:
        response = client.post("/questions/parse", json={"text": ""})
        assert response.status_code == 422

    def test_parse_returns_provenance_block(self) -> None:
        data = client.post(
            "/questions/parse",
            json={"text": "", "question_id": "q-sglt2-ckd-t2dm-001"},
        ).json()
        assert "provenance" in data
        assert data["provenance"]["is_demo_mode"] is True


class TestQuestionsCuratedEndpoint:
    def test_list_curated_returns_200(self) -> None:
        response = client.get("/questions/curated")
        assert response.status_code == 200

    def test_list_curated_returns_three_questions(self) -> None:
        data = client.get("/questions/curated").json()
        assert len(data) == 3

    def test_get_curated_q1_by_id(self) -> None:
        response = client.get("/questions/curated/q-sglt2-ckd-t2dm-001")
        assert response.status_code == 200
        assert response.json()["id"] == "q-sglt2-ckd-t2dm-001"

    def test_get_unknown_curated_returns_404(self) -> None:
        response = client.get("/questions/curated/q-does-not-exist")
        assert response.status_code == 404


class TestPhenotypesBuildEndpoint:
    def test_build_q1_phenotype_returns_200(self) -> None:
        response = client.post(
            "/phenotypes/build",
            json={"question_id": "q-sglt2-ckd-t2dm-001"},
        )
        assert response.status_code == 200

    def test_build_q1_is_available(self) -> None:
        data = client.post(
            "/phenotypes/build",
            json={"question_id": "q-sglt2-ckd-t2dm-001"},
        ).json()
        assert data["is_available"] is True

    def test_build_unknown_question_returns_404(self) -> None:
        response = client.post(
            "/phenotypes/build",
            json={"question_id": "q-does-not-exist"},
        )
        assert response.status_code == 404

    def test_build_returns_phenotype_with_concepts(self) -> None:
        data = client.post(
            "/phenotypes/build",
            json={"question_id": "q-sglt2-ckd-t2dm-001"},
        ).json()
        phenotype = data.get("phenotype", {})
        assert "concepts" in phenotype
        assert len(phenotype["concepts"]) >= 4

    def test_build_returns_run_id(self) -> None:
        data = client.post(
            "/phenotypes/build",
            json={"question_id": "q-sglt2-ckd-t2dm-001"},
        ).json()
        assert "run_id" in data
