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
| Progress | SQLite file on `./data` volume (schema v4: stars, hint peaks, completion, pitch advisory, correction cards, FSRS) |
| CPU speech | `speech-cpu` mock ASR + stub WAV TTS |
| GPU speech | `asr`, `tts` containers (stubs). `pron` is a CPU reading + F0 advisory service |
| Assets | nginx static `./assets` |

## Quick start (CPU demo — no model downloads)

```bash
cp .env.example .env
docker compose --profile cpu up --build
```

Open [http://localhost:5173](http://localhost:5173).

1. The ramen shop scene loads with the baked counter background and Sora. Open **Town** (`#/town`) to pick another building.
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

Speech placement is [docs/ADR-001-speech-placement.md](docs/ADR-001-speech-placement.md). With both machines up, run ASR/TTS on the **RTX 3090** and leave Spark for the LLM and ComfyUI (`:8188`). Start Spark speech only when the 3090 is absent. Do not leave those speech containers running on Spark beside the LLM.

**3090 + Mac mini over Tailscale:** see [docs/DEPLOY-3090-TAILSCALE.md](docs/DEPLOY-3090-TAILSCALE.md) (`cp .env.rtx3090.example .env` on the 3090).

```bash
# Desktop RTX 3090 (x86) — default speech host. ASR_ENGINE=kotoba-whisper-faster is x86 only.
docker compose --env-file .env --profile rtx3090 up

# DGX Spark (aarch64) — set GPU_BASE in .env.spark. Speech here only if the 3090 is down.
docker compose --env-file .env.spark --profile spark up
```

`GPU_MEM_FRACTION` (default 0.40, use ≤ 0.35 on Spark), `ASR_ENGINE`, and `GPU_BASE` are the speech knobs. `SPEECH_PROFILE` selects a row in `voices/voices.yaml`. GPU services are **stubbed** in this scaffold; wire Qwen3-ASR / TTS per `docs/SPEC.md`.

## Development without Docker

```bash
make test    # scenario schema + flow tests
make lint    # ruff + eslint

# Orchestrator
cd orchestrator && pip install -e ".[dev]"
SCENARIOS_PATH=../scenarios DB_PATH=../data/machi.sqlite \
  ASSETS_PATH=../assets \
  ASR_URL=http://127.0.0.1:8101 TTS_URL=http://127.0.0.1:8102 \
  uvicorn machi.main:app --reload --port 8100

# Web
cd web && npm install && npm run dev
```

The dev UI logs each captured PCM frame in the browser console. Set `VITE_LOG_PCM_FRAMES=0` to turn that off. Production builds do not log frames. The mic works on localhost or HTTPS.

### Phone mic on the LAN (HTTPS)

`getUserMedia` only runs in a [secure context](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts): `localhost`, or HTTPS. Opening `http://192.168.x.x:5173` on a phone leaves the mic blocked. Port **5173 stays plain HTTP** for the laptop demo. HTTPS is opt-in on **5174**.

```bash
./scripts/make_lan_https.sh
# optional: ./scripts/make_lan_https.sh --lan 192.168.1.20 --tailscale 100.x.y.z
docker compose --profile cpu --profile https up
```

The script writes a 100-year self-signed certificate to `.certs/` (gitignored) with SAN entries for localhost, the LAN IP, and a Tailscale IPv4 when `tailscale ip -4` works. `web-https` (profile `https`) sets `HTTPS=1` and nginx serves that certificate on `:5174`, proxying `/api` and the WebSocket the same way `:5173` does. The page is `https://`, so the browser opens `wss://` to `/api/ws/...`. Without Docker: `cd web && HTTPS=1 npm run dev` (same cert files, port 5174).

Trust the certificate, then open `https://<lan-ip>:5174`.

**iOS**

1. AirDrop `.certs/machi.crt` and open it.
2. Settings → General → VPN & Device Management (or Settings → Profile Downloaded) → Install the profile.
3. Settings → General → About → Certificate Trust Settings → enable full trust for **machi-lan**.
4. Safari → `https://<lan-ip>:5174` → allow the microphone.

**Android**

1. Copy `machi.crt` to the phone.
2. Settings → Security → Encryption & credentials → Install a certificate → **CA certificate**.
3. Chrome → `https://<lan-ip>:5174` → allow the microphone. Chrome uses the user CA store. Some in-app WebViews ignore it.

**Tailscale.** If the cert includes the tailnet IP, open `https://<tailscale-ip>:5174` from a phone on the same tailnet after the trust steps above. For a real name and no manual install, run `tailscale serve` on the Machi host in front of port 5173. That proxy is not part of Compose.

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

### End-to-end latency (M0-12)

`scripts/e2e_latency.py` posts 16 kHz mono PCM16, waits for NPC WAV bytes, and prints ASR / LLM / TTS milliseconds plus wall-clock end-to-end time. p95 is over N turns (`--turns`, or `N`, default 10).

```bash
make e2e-latency
# same command: orchestrator + speech-cpu stubs in this process
.venv/bin/python scripts/e2e_latency.py

# a stack that is already up (cpu profile listens on :8100)
ORCH_URL=http://127.0.0.1:8100 .venv/bin/python scripts/e2e_latency.py

# reference hardware: exit 1 unless p95 is under 2 s
REAL=1 ORCH_URL=http://127.0.0.1:8100 .venv/bin/python scripts/e2e_latency.py
```

`pytest -m e2e_latency` runs a two-turn in-process check of that path. A plain `pytest` deselects the marker.

The clock starts at `POST /sessions/{id}/turn`, after push-to-talk has ended the utterance, so VAD and Smart Turn are not inside the number. The spec budget ([docs/SPEC.md](docs/SPEC.md#latency-budget)) is:

| Stage | Target | Ceiling |
| --- | --- | --- |
| End of speech (VAD + Smart Turn) | 250 ms | 500 ms |
| Final ASR | 150 ms | 300 ms |
| LLM first sentence | 350 ms | 700 ms |
| TTS first audio | 150 ms | 300 ms |
| **Total learner stop → NPC speaks** | **~1.0 s** | **~1.9 s** |

On reference hardware (ASR/TTS on the RTX 3090 or DGX Spark, LLM on the LAN) `REAL=1` requires p95 under **2000 ms**, which is the M0 gate just above the ~1.9 s ceiling. CPU stubs and the mock LLM land in the tens of milliseconds; without `REAL=1` the script prints the comparison and still exits 0. No Spark or 3090 sample is checked in — run `REAL=1` on that machine when you want a recorded number.

### Beginner accent fixtures (M0-13)

`tests/fixtures/asr/` has eight clips (16 kHz mono PCM16, each under 100 KB) of phrases from `scenarios/restaurant_ramen_01.yaml` (`ふたりです`, `しょうゆラーメンをひとつ`, `お水をください`, and the other `accept` / `key_phrases` lines) plus `expected.json`. macOS Kyoko (`say -v Kyoko`) spoke them: a clear native stand-in until learner recordings replace the files. No model weights are committed.

Regenerate on a Mac that has the Kyoko voice:

```bash
python scripts/regen_asr_fixtures.py
```

Score a live engine (skipped when `ASR_URL` is unset or `/health` does not answer):

```bash
ASR_URL=http://127.0.0.1:8101 python -m pytest -m accent orchestrator/tests/test_asr_accent.py
```

Each WAV is posted to `{ASR_URL}/v1/transcribe`. The score is word error rate on cutlet romaji tokens, so a kanji line and its kana reading can match. The test fails when mean WER is above **0.35**. The speech-cpu mock returns `ふたりです` for every clip and fails that bar. A default `pytest` deselects `accent`; it still checks that the checked-in WAVs are small 16 kHz mono PCM16 and that every expected line is in the ramen scenario.

### Baked NPC lines

`scripts/bake_npc_audio.py` writes `assets/audio/{scenario_id}/{node_id}.wav` and a `manifest.json` for every fixed `npc` line. The restaurant files in git are CPU stub wavs. Start the TTS stub, then regenerate:

```bash
TTS_URL=http://127.0.0.1:8102 python scripts/bake_npc_audio.py
```

### Scenarios

Each visit is a YAML file under `scenarios/`. The orchestrator walks `flow.nodes` from the learner's lines: a goal's `accept` list (kana, kanji, or romaji) advances `on_success` or `next`. The web turn UI does not special-case branches.

A node with `kind: branch` is silent. It has `condition.level_gte` and two targets, `high` and `low`. The session's learner level (1–4) decides: level at or above the gate takes `high`, a lower level takes `low`, in the same turn. In the ramen shop, ordering at level 3 or 4 asks 硬め・普通・やわらかめ (`かため` / `ふつう` / `やわらかめ`, also `katame`, `futsuu`, `yawarakame`). Level 1 or 2 skips that question and confirms the order. A wrong firmness stays on the node; Sora's coach note tells you the three words. The firmness goal is optional, so a low-level visit still completes with party size, order, and payment.

### Scenario editor

Open `#/editor` in the web UI. The page lists `GET /scenarios`, loads a file with `GET /scenarios/{id}/raw`, and checks a draft with `POST /scenarios/validate`. Validation uses the same YAML loader and Pydantic models as the orchestrator (unknown fields and missing flow edges come back with a path and, when the parser can see it, a line). The endpoint does not write disk. **Export .yaml** downloads a blob and stays disabled until the current text validates.

### ComfyUI scene bake (offline)

`tools/comfyui_bake.py` is a one-shot. It is **never** part of `docker compose up`. House rule: do not restart ComfyUI (April shares that process). The script only queues a prompt. It refuses to open a socket unless `COMFY_BAKE_GO=1`. `--dry-run` prints the workflow and does not use the network.

```bash
COMFY_BAKE_GO=1 python tools/comfyui_bake.py \
  --prompt "ramen counter, evening" --out assets/bg/ramen.webp
# edit pass: --ref path/to/plate.png
# --server defaults to http://100.69.65.33:8188
```

Templates live in `tools/workflows/` (`qwen_image_2511_t2i.json`, `qwen_image_2511_edit.json`): UNETLoader `qwen_image_edit_2511_bf16` at `fp8_e4m3fn`, CLIPLoader `qwen_2.5_vl_7b_fp8_scaled` type `qwen_image`, VAELoader `qwen_image_vae`, euler / simple / cfg 4.0. Output is WebP via Pillow, which is not a Compose dependency.

## Repository layout

```
web/              Browser UI
orchestrator/     Session + flow engine + LLM client
speech-cpu/       CPU-profile ASR/TTS stubs
asr/ tts/         GPU-profile stubs (M0)
pron/             CPU pyopenjtalk readings and librosa.pyin pitch advisory (M2)
scenarios/        YAML scenarios (restaurant MVP included)
assets/           Scene backgrounds, sprites, and baked NPC audio
docs/SPEC.md      Product spec
docker-compose.yml
```

## What is real vs stubbed

| Component | Status |
| --- | --- |
| Scenario schema + restaurant YAML | Real |
| Flow / goal matching | Real. `kind: branch` nodes follow `high` when the learner level is at least `condition.level_gte`, and `low` otherwise. Ramen asks noodle firmness at level 3+ |
| SQLite session logging | Real. Debrief writes stars, completion, per-goal hint peaks, and weighted correction cards. Completing a scenario adds those cards to the FSRS deck. `GET /sessions/{id}/progress` reads the summary back |
| Romaji (cutlet) | Real for NPC and learner lines. The web UI shows the romaji row when the hint level is 2 or higher (selector defaults to 2) |
| Furigana | Per-token ruby from fugashi + unidic-lite for any line. Scenario `npc_kana` overrides that reading when the spoken line still matches the script |
| Mic / WebSocket audio | Push-to-talk sends 20 ms 16 kHz PCM; server acks and waits for `turn` |
| Turn pipeline | Audio-only `audio_b64` (REST or WebSocket) runs ASR → LLM → TTS. Typed text skips ASR |
| Hands-free | Silero VAD + silence heuristic (500 ms ceiling). Smart Turn v3 optional |
| Barge-in | New capture stops playback; `audio_start` or `turn` cancels the in-flight server turn |
| ASR / TTS (CPU) | Mock / stub WAV. Fixed NPC lines in `assets/audio/` play from disk when the spoken text still matches the scenario; other lines use live TTS |
| ASR / TTS (GPU) | Health stubs |
| Pronunciation | CPU `pron` service when `PRON_URL` is set. Expected reading goes to Sora. F0 advice is stored and shown; it does not change stars. Unset `PRON_URL` skips the call |
| LLM | Live when `LLM_BASE_URL` set; else mock |
| Lip flap and hint ladder | In the scene |
| Briefing, warm-up, debrief | Sora briefing, one lenient attempt per key phrase, debrief after pay |
| FSRS | Real. In-tree FSRS-4.5 (`orchestrator/machi/fsrs.py`, no extra package). Completing a visit enrolls correction cards. `GET /reviews/next` lists due cards; `POST /reviews` rates again/hard/good/easy. A new visit weaves up to two due cards that share a scenario tag into Sora's briefing and the warm-up. `POST /review/sessions` starts a two-minute spoken review (REST); `POST /review/sessions/{id}/answer` takes typed text or `audio_b64` |

## Suggested next steps

1. **M0** — Stream a real ASR (`asr/`) on the PCM the VAD already commits.
2. **GPU ASR/TTS** — Implement `asr` and `tts` services with Qwen3 or Kokoro on the `cpu`/`spark` profiles.
3. **M1** — Prompt templates and tutor JSON validation are in. Briefing, warm-up, and the debrief screen run for the ramen shop. Furigana and the level-2 romaji row are in place.
4. **Assets** — `tools/comfyui_bake.py` queues Qwen Image 2511 on a running ComfyUI and writes WebP under `assets/`. It is not part of Compose, and it must not restart ComfyUI.

## License

MIT. See [LICENSE](LICENSE).