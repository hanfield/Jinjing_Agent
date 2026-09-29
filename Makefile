.PHONY: install test eval format lint clean

install:
	./venv/bin/pip install -e ".[dev]"

test:
	./venv/bin/pytest harness/tests/ -v

eval:
	./venv/bin/python -m harness.cli --config harness/configs/default_eval.json

format:
	./venv/bin/black harness/ engine/ test_jinshu_v2.py
	./venv/bin/isort harness/ engine/ test_jinshu_v2.py

lint:
	./venv/bin/flake8 harness/ engine/ test_jinshu_v2.py

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
