.PHONY: install install-dev test lint format typecheck clean run-api run-app docker-build docker-up docker-down

# ── Setup ─────────────────────────────────────────────────────────────────────
install:
	pip install -e .

install-dev:
	pip install -e ".[dev,llm]"

# ── Quality ───────────────────────────────────────────────────────────────────
test:
	pytest tests/ -v --cov=src --cov-report=term-missing

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

lint:
	ruff check src/ tests/ app/ scripts/

format:
	ruff format src/ tests/ app/ scripts/

typecheck:
	mypy src/

check: lint typecheck test

# ── Run ───────────────────────────────────────────────────────────────────────
run-api:
	uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

run-app:
	streamlit run app/Home.py --server.port 8501

# ── Docker ────────────────────────────────────────────────────────────────────
docker-build:
	docker build -t clinical-evidence-studio:latest .

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

# ── Cleanup ───────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -name ".coverage" -delete 2>/dev/null || true
