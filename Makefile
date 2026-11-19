# ==============================================================================
# Makefile for Heurix (hx) Development & Deployment
# ==============================================================================

.PHONY: help test cov lint format typecheck qa check build docker-build docker-run site-dev site-build clean install

VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
PYTEST = $(VENV)/bin/pytest
RUFF = $(VENV)/bin/ruff
MYPY = $(VENV)/bin/mypy
HX = $(VENV)/bin/hx

help:
	@echo "Heurix (hx) Development & Deployment Commands:"
	@echo "  make test          Run test suite with pytest"
	@echo "  make cov           Run tests with coverage (fails below the pyproject.toml floor)"
	@echo "  make lint          Lint with ruff"
	@echo "  make format        Format code with ruff"
	@echo "  make typecheck     Type check with mypy"
	@echo "  make qa            Run every CI gate: lint, format check, mypy, coverage"
	@echo "  make check         Run Heurix drift detection"
	@echo "  make build         Build Python distribution packages (wheel, sdist)"
	@echo "  make docker-build  Build local Docker container image"
	@echo "  make docker-run    Run local Docker container against current directory"
	@echo "  make site-dev      Run the interactive web frontend dev server"
	@echo "  make site-build    Sync llms.txt/docs and build the web frontend"
	@echo "  make clean         Clean build artifacts and temporary files"

test:
	$(PYTEST) -v

cov:
	$(PYTEST) --cov=heurix --cov-report=term-missing:skip-covered

lint:
	$(RUFF) check .

format:
	$(RUFF) format .

typecheck:
	$(MYPY)

qa: lint typecheck cov
	$(RUFF) format --check .

check:
	$(HX) check

build:
	$(PYTHON) -c "from setuptools.build_meta import build_sdist; build_sdist('dist')"
	$(PIP) wheel --no-deps --no-build-isolation -w dist .

measure-size:
	@echo "=== Distribution Artifact Sizes ==="
	@ls -lh dist/ 2>/dev/null || echo "No dist/ directory found. Run 'make build' first."
	@echo "\n=== Source Tree Size ==="
	@du -sh src/heurix

docker-build:
	docker build -t heurix:latest .

docker-run:
	docker run --rm -v $(PWD):/workspace heurix:latest generate --dry-run

site-dev:
	pnpm --dir site dev

site-build:
	pnpm --dir site build

clean:
	rm -rf dist/ build/ *.egg-info src/*.egg-info .pytest_cache/ .ruff_cache/ .mypy_cache/ .coverage htmlcov/
	find . -type d -name "__pycache__" -exec rm -rf {} +
