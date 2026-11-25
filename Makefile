.DEFAULT_GOAL := help

# Unit tests only: no Docker, no dataset, no GPU (SPEC-00.7).
PYTEST_UNIT := uv run pytest -m "not integration and not data and not gpu"

STUBS := data index eval final-eval results ci-baseline serve \
         cloud-up cloud-down cloud-load-index loadtest cost-snapshot

.PHONY: help check test test-data up-local down-local $(STUBS)

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'

check: ## lint + format check + types + unit tests (must pass before every commit)
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	$(PYTEST_UNIT)

test: check ## check + integration tests (run make up-local first)
	uv run pytest -m integration || [ $$? -eq 5 ]

test-data: ## tests that need the real ESCI download
	uv run pytest -m data || [ $$? -eq 5 ]

up-local: ## start local Postgres+pgvector and DynamoDB Local
	docker compose up -d --wait

down-local: ## stop local services (the Postgres volume is kept)
	docker compose down

$(STUBS):
	@echo "make $@: not implemented yet (see docs/ROADMAP.md)" >&2; exit 1
