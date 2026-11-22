.PHONY: up-cpu down test lint e2e-latency

up-cpu:
	docker compose --profile cpu up --build

down:
	docker compose --profile cpu down

test:
	cd orchestrator && pip install -e ".[dev]" && pytest -q

lint:
	cd orchestrator && pip install -e ".[dev]" && ruff check machi tests
	cd web && npm ci && npm run lint

# In-process orchestrator + speech-cpu stubs. REAL=1 asserts p95 < 2s.
e2e-latency:
	python scripts/e2e_latency.py