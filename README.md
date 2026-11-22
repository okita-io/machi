# Machi

**Machi** (町) is a local, Docker-run Japanese conversation tutor: an anime guide (**Sora**) drops you into illustrated real-world scenes so you practice spoken role-play with STT → LLM → TTS on your LAN.

Full product and technical spec: [docs/SPEC.md](docs/SPEC.md).

## Stack (this PR)

| Layer | Choice |
| --- | --- |
| Web | Vite + React + TypeScript |
| Orchestrator | Python 3.12, FastAPI, WebSocket/REST, OpenAI SDK |
| Text tools | Optional `pip install -e ".[nlp]"` for [cutlet](https://github.com/polm/cutlet) (MIT romaji); furigana from scenario readings in CPU demo |
| Scenario data | YAML + Pydantic validation |
| Progress | SQLite file on `./data` volume |
| CPU speech | `speech-cpu` mock ASR + stub WAV TTS |
| GPU speech | `asr`, `tts`, `pron` containers (stubs; interfaces only) |
| Assets | nginx static `./assets` |

## Quick start (CPU demo — no model downloads)

```bash
cp .env.example .env
docker compose --profile cpu up --build
```

Open [http://localhost:5173](http://localhost:5173).

1. The ramen shop scene loads with a placeholder background and Sora sprite.
2. Type what you would say (e.g. `ふたりです`) and **Send turn**.
3. The orchestrator runs the scenario state machine, enriches the NPC line with romaji/ruby, calls the stub TTS, and shows coach notes.

Scene art is served at [http://localhost:8080](http://localhost:8080).

### Pointing at a real LLM

Set in `.env` (never commit secrets):

```bash
LLM_BASE_URL=http://your-host:8888/v1
LLM_MODEL=your-model-id
LLM_API_KEY=none
```

When `LLM_BASE_URL` is empty, the orchestrator uses deterministic scenario lines and mock tutor JSON.

### GPU profiles

```bash
# DGX Spark (aarch64) — set GPU_BASE in .env.spark
docker compose --env-file .env.spark --profile spark up

# Desktop RTX 3090 (x86) — ASR_ENGINE=kotoba-whisper-faster
docker compose --env-file .env.rtx3090 --profile rtx3090 up
```

GPU services are **stubbed** in this scaffold; wire Qwen3-ASR / TTS per `docs/SPEC.md`.

## Development without Docker

```bash
make test    # scenario schema + flow tests
make lint    # ruff + eslint

# Orchestrator
cd orchestrator && pip install -e ".[dev]"
SCENARIOS_PATH=../scenarios DB_PATH=../data/machi.sqlite \
  ASR_URL=http://127.0.0.1:8101 TTS_URL=http://127.0.0.1:8102 \
  uvicorn machi.main:app --reload --port 8100

# Web
cd web && npm install && npm run dev
```

## Repository layout

```
web/              Browser UI
orchestrator/     Session + flow engine + LLM client
speech-cpu/       CPU-profile ASR/TTS stubs
asr/ tts/ pron/   GPU-profile stubs (M0/M2)
scenarios/        YAML scenarios (restaurant MVP included)
assets/           Scene backgrounds and sprites
docs/SPEC.md      Product spec
docker-compose.yml
```

## What is real vs stubbed

| Component | Status |
| --- | --- |
| Scenario schema + restaurant YAML | Real |
| Flow / goal matching | Real |
| SQLite session logging | Real (minimal) |
| Romaji (cutlet) | Real |
| Furigana | From scenario kana in demo; fugashi/pyopenjtalk in M1 |
| Mic / VAD / WebSocket audio | UI uses typed text; WS route exists |
| ASR / TTS (CPU) | Mock / stub WAV |
| ASR / TTS / pron (GPU) | Health stubs |
| LLM | Live when `LLM_BASE_URL` set; else mock |
| Lip flap, hints, debrief, FSRS | Not yet (M1/M2) |

## Suggested next steps

1. **M0** — Wire Silero VAD + browser mic → orchestrator WebSocket PCM frames.
2. **GPU ASR/TTS** — Implement `asr` and `tts` services with Qwen3 or Kokoro on the `cpu`/`spark` profiles.
3. **M1** — Hint ladder UI, coach drawer, debrief screen, fugashi + unidic-lite furigana for any line.
4. **Assets** — ComfyUI bake script for WebP backgrounds and Sora expression sheet.

## License

MIT. See [LICENSE](LICENSE).