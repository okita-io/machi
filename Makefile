.PHONY: up-cpu up-rtx3090 up-rtx3090-https down test lint e2e-latency e2e-live

up-cpu:
	docker compose --profile cpu up --build

# On the RTX 3090 host. Requires .env from .env.rtx3090.example
up-rtx3090:
	docker compose --env-file .env --profile rtx3090 up --build

# Tailscale / remote mic — run make_lan_https.sh first
up-rtx3090-https:
	docker compose --env-file .env --profile rtx3090 --profile https up --build

down:
	docker compose --profile cpu down

test:
	cd orchestrator && pip install -e ".[dev]" && pytest -q

lint:
	cd orchestrator && pip install -e ".[dev]" && ruff check machi tests ../pron
	cd web && npm ci && npm run lint

# In-process orchestrator + speech-cpu stubs. REAL=1 asserts p95 < 2s.
e2e-latency:
	python scripts/e2e_latency.py

# Live 3090/Spark stack. Posts tests/fixtures/asr clips and writes data/e2e_live_report.json.
e2e-live:
	python scripts/e2e_live_speech.py