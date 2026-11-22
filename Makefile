.PHONY: up-cpu down test lint

up-cpu:
	docker compose --profile cpu up --build

down:
	docker compose --profile cpu down

test:
	cd orchestrator && pip install -e ".[dev]" && pytest -q

lint:
	cd orchestrator && pip install -e ".[dev]" && ruff check machi tests
	cd web && npm ci && npm run lint