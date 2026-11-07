.PHONY: help install lint lint-fix format test test-cov pre-commit clean up down

PYTEST := uv run pytest
RUFF := uv run ruff
PRE_COMMIT := uv run pre-commit

help:
	@echo "Commands:"
	@echo "  install     Install all dependencies"
	@echo "  lint        Run ruff linter"
	@echo "  lint-fix    Run ruff linter with auto-fix"
	@echo "  format      Run ruff formatter"
	@echo "  test        Run tests"
	@echo "  test-cov    Run tests with coverage report"
	@echo "  pre-commit  Run pre-commit on all files"
	@echo "  clean       Remove build artifacts and caches"
	@echo "  up          Build and start the service on port 8000"
	@echo "  down        Stop the service"

install:
	uv sync

lint:
	$(RUFF) check .

lint-fix:
	$(RUFF) check --fix .

format:
	$(RUFF) format .

test:
	$(PYTEST) tests/

test-cov:
	$(PYTEST) tests/ --cov=mail_parser_api --cov-report=term-missing --cov-report=html

pre-commit:
	$(PRE_COMMIT) run --all-files

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .ruff_cache .coverage dist build htmlcov

up:
	docker compose up -d --build

down:
	docker compose down
