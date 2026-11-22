# Machi

**Machi** (町) is a local, Docker-run Japanese conversation tutor: an anime guide (**Sora**) drops you into illustrated real-world scenes so you practice spoken role-play with STT → LLM → TTS on your LAN.

Full product and technical spec: [docs/SPEC.md](docs/SPEC.md).

## Stack (this PR)

| Layer | Choice |
| --- | --- |
| Web | Vite + React + TypeScript |
| Orchestrator | Python 3.12, FastAPI, WebSocket/REST, OpenAI SDK |
| Text tools | [cutlet](https://github.com/polm/cutlet) romaji and fugashi + unidic-lite furigana (MIT / BSD), default in the orchestrator image. `npc_kana` in YAML is an optional whole-line override |
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
3. The orchestrator runs the scenario state machine, enriches the NPC line with romaji/ruby, calls the stub TTS, and shows coach notes when the tutor JSON is ready (NPC audio is not held for that note). Help, a wrong line, or ~45s of silence climbs the hint rung. Sora's mouth opens with the playback loudness.

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

The dev UI logs each captured PCM frame in the browser console. Set `VITE_LOG_PCM_FRAMES=0` to turn that off. Production builds do not log frames. The mic works on localhost or HTTPS.

### Hands-free turn taking

Push-to-talk (`hands_free: false`) never runs VAD or a turn scorer. Release the button; the client sends `turn`.

Hands-free (`hands_free: true` on `audio_start`) runs **Silero VAD** (MIT, ONNX, CPU) on each 20 ms frame. After the learner has spoken, about 250 ms of silence is a candidate end-of-turn. The default scorer is a silence-duration heuristic: it holds through pauses shorter than **500 ms** and cuts at that ceiling, which is the spec budget. No model download is required for the heuristic. The server then emits `turn_result` on its own. Fetch Silero once if you want that path live:

```bash
python tools/fetch_vad_model.py
pip install -e "./orchestrator[vad]"
```

The ONNX file is written to `.cache/vad/silero_vad.onnx` and is gitignored. Without that file, hands-free stays on the client `turn` path.

**Smart Turn v3** is optional and off by default. The weights are [pipecat-ai/smart-turn-v3](https://huggingface.co/pipecat-ai/smart-turn-v3) (BSD-2-Clause). They are not in the default Docker image. The adapter loads `torch` and `transformers` lazily, on CPU, only when `SMART_TURN_ENABLED=1`, and only after VAD raises a candidate. Install the extra yourself:

```bash
pip install -e "./orchestrator[smart-turn]"
# SMART_TURN_ENABLED=1
# SMART_TURN_MODEL=pipecat-ai/smart-turn-v3
```

Push-to-talk bypasses Smart Turn as well. A hold from the model still cannot outlast the 500 ms silence ceiling.

### Barge-in

Pressing talk (or starting a hands-free capture) stops NPC audio in the browser immediately. The same `audio_start` — and any new `turn` — cancels that session's in-flight server turn. ASR, LLM, and TTS awaits are aborted, the cancelled result is dropped, and scenario progress from that turn is rolled back. The latency log still records the turn with `"cancelled": true`. A turn that already delivered `turn_result` is left as-is; only playback stops.

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
| Romaji (cutlet) | Real for NPC and learner lines. The web UI shows the romaji row when the hint level is 2 or higher (selector defaults to 2) |
| Furigana | Per-token ruby from fugashi + unidic-lite for any line. Scenario `npc_kana` overrides that reading when the spoken line still matches the script |
| Mic / WebSocket audio | Push-to-talk sends 20 ms 16 kHz PCM; server acks and waits for `turn` |
| Turn pipeline | Audio-only `audio_b64` (REST or WebSocket) runs ASR → LLM → TTS. Typed text skips ASR |
| Hands-free | Silero VAD + silence heuristic (500 ms ceiling). Smart Turn v3 optional |
| Barge-in | New capture stops playback; `audio_start` or `turn` cancels the in-flight server turn |
| ASR / TTS (CPU) | Mock / stub WAV |
| ASR / TTS / pron (GPU) | Health stubs |
| LLM | Live when `LLM_BASE_URL` set; else mock |
| Lip flap, hints, debrief, FSRS | Not yet (M1/M2) |

## Suggested next steps

1. **M0** — Stream a real ASR (`asr/`) on the PCM the VAD already commits.
2. **GPU ASR/TTS** — Implement `asr` and `tts` services with Qwen3 or Kokoro on the `cpu`/`spark` profiles.
3. **M1** — Hint ladder UI, coach drawer, debrief screen. Furigana and the level-2 romaji row are in place.
4. **Assets** — ComfyUI bake script for WebP backgrounds and Sora expression sheet.

## License

MIT. See [LICENSE](LICENSE).