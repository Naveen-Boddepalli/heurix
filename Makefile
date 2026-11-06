# ==============================================================================
# Makefile for Heurix (hx) Development & Deployment
# ==============================================================================

.PHONY: help test check build docker-build docker-run clean install

VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
PYTEST = $(VENV)/bin/pytest
HX = $(VENV)/bin/hx

help:
	@echo "Heurix (hx) Development & Deployment Commands:"
	@echo "  make test          Run test suite with pytest"
	@echo "  make check         Run Heurix drift detection"
	@echo "  make build         Build Python distribution packages (wheel, sdist)"
	@echo "  make docker-build  Build local Docker container image"
	@echo "  make docker-run    Run local Docker container against current directory"
	@echo "  make clean         Clean build artifacts and temporary files"

test:
	$(PYTEST) -v

check:
	$(HX) check

build:
	$(PIP) wheel --no-deps --no-build-isolation -w dist .

docker-build:
	docker build -t heurix:latest .

docker-run:
	docker run --rm -v $(PWD):/workspace heurix:latest generate --dry-run

clean:
	rm -rf dist/ build/ *.egg-info src/*.egg-info .pytest_cache/
	find . -type d -name "__pycache__" -exec rm -rf {} +
