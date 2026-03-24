.PHONY: install dev test clean help

UV := $(shell command -v uv 2>/dev/null)
ifdef UV
  PIP := uv pip
  PYTHON := uv run python
else
  PIP := pip
  PYTHON := python3
endif

help:
	@echo "Project Forge - Available targets:"
	@echo "  make install       Install main dependencies + editable package"
	@echo "  make dev           Install with dev dependencies"
	@echo "  make test          Run pytest"
	@echo "  make clean         Remove build artifacts and cache"
	@echo "  make help          Show this help message"
	@echo ""
	@echo "Detected environment:"
ifdef UV
	@echo "  Using: uv ($(shell uv --version))"
else
	@echo "  Using: pip ($(shell pip --version))"
endif

install:
	$(PIP) install -e .

dev:
	$(PIP) install -e ".[dev]"

test:
	$(PYTHON) -m pytest tests/ --ignore=tests/test_output_analyzer.py -v

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .coverage coverage.json
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
