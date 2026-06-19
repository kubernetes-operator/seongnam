.PHONY: lint test test-unit test-integration cov run-api run-collector migrate

lint:
	ruff check src tests

test-unit:
	PYTHONPATH=src pytest tests/unit -v --cov=src --cov-report=term-missing

test-integration:
	INTEGRATION_TEST=1 PYTHONPATH=src pytest tests/integration -v -W ignore

test: test-unit

cov:
	PYTHONPATH=src pytest tests/unit --cov=src --cov-report=html:htmlcov
	@echo "Coverage report: htmlcov/index.html"

run-api:
	PYTHONPATH=src uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

run-collector:
	PYTHONPATH=src python -m collector.os_service

migrate:
	PYTHONPATH=src python src/db/migrate.py
