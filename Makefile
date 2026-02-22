.DEFAULT_GOAL := help
.PHONY: help install dev lint format typecheck test test-cov docker-build docker-up docker-down clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Setup ────────────────────────────────────────────────────────────
install: ## Install production dependencies
	pip install -e .
	playwright install chromium --with-deps

dev: ## Install with dev dependencies + pre-commit hooks
	pip install -e '.[dev]'
	playwright install chromium --with-deps
	pre-commit install

# ── Code Quality ─────────────────────────────────────────────────────
lint: ## Run linter and format check (matches CI)
	ruff check server/ tests/
	ruff format --check server/ tests/

format: ## Auto-format code
	ruff check --fix server/ tests/
	ruff format server/ tests/

typecheck: ## Run type checker (matches CI)
	mypy server/ --ignore-missing-imports --no-error-summary

# ── Testing ──────────────────────────────────────────────────────────
test: ## Run tests (matches CI options minus coverage upload)
	pytest tests/ -v --cov=server --cov-report=term-missing --cov-report=xml

test-cov: ## Run tests with coverage report (matches CI)
	pytest tests/ -v --cov=server --cov-report=term-missing --cov-report=xml

# ── Docker ───────────────────────────────────────────────────────────
docker-build: ## Build Docker image
	docker build -t hermes:latest .

docker-up: ## Start services with Docker Compose
	docker compose up -d

docker-down: ## Stop Docker Compose services
	docker compose down

# ── Cleanup ──────────────────────────────────────────────────────────
clean: ## Remove build artifacts and caches
	rm -rf .ruff_cache .pytest_cache .mypy_cache htmlcov .coverage coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
