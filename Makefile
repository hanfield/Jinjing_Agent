.PHONY: install test eval format lint clean docker-build

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
PYTEST ?= $(PYTHON) -m pytest
RUFF ?= $(PYTHON) -m ruff

install:
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt pytest pytest-asyncio ruff

test:
	$(PYTEST) harness/tests/ -v

eval:
	$(PYTHON) -m harness.cli --config harness/configs/default_eval.json

format:
	$(RUFF) format .

lint:
	$(RUFF) check .

docker-build:
	docker build -t jinshu-os:latest .

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
