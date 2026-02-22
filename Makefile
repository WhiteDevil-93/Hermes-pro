.DEFAULT_GOAL := help
.PHONY: help install dev lint format typecheck docs-check test test-cov docker-build docker-up docker-down clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Setup ────────────────────────────────────────────────────────────
install: ## Install production dependencies
	pip install -e .
	playwright install chromium

dev: ## Install with dev dependencies + pre-commit hooks
	pip install -e '.[dev]'
	playwright install chromium
	pre-commit install

# ── Code Quality ─────────────────────────────────────────────────────
lint: ## Run linter (ruff check + format check)
	ruff check .
	ruff format --check .

format: ## Auto-format code
	ruff check --fix .
	ruff format .

typecheck: ## Run type checker (mypy)
	mypy server/

# ── Documentation Checks ─────────────────────────────────────────────
docs-check: ## Validate documentation metadata consistency
	python scripts/check_license_consistency.py

# ── Testing ──────────────────────────────────────────────────────────
test: ## Run tests
	pytest

test-cov: ## Run tests with coverage report
	pytest --cov=server --cov-report=term-missing --cov-report=html

# ── Docker ───────────────────────────────────────────────────────────
docker-build: ## Build Docker image
	docker build -t hermes:latest .

docker-up: ## Start services with Docker Compose
	docker compose up -d

docker-down: ## Stop Docker Compose services
	docker compose down

# ── Cleanup ──────────────────────────────────────────────────────────
clean: ## Remove build artifacts and caches
	rm -rf .ruff_cache .pytest_cache .mypy_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
