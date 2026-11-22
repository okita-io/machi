# AGENTS.md — Machi

Guide for coding agents working on **Machi** (`okita-io/machi`): a local, Docker-run Japanese conversation tutor (STT → LLM → TTS) with scenario-driven role-play and anime guide **Sora**.

Canonical product spec: **[docs/SPEC.md](docs/SPEC.md)**.

---

## Project overview

Machi drops an English-speaking learner into illustrated real-world Japanese scenes (restaurant, konbini, station, laundry, taxi, tickets). The learner **speaks** to progress; the stack runs on the LAN: browser → orchestrator → VAD/ASR/LLM/TTS/text tools → SQLite progress.

**Design constraint:** Pipeline speech (VAD → ASR → LLM → TTS), not end-to-end speech-to-speech. The tutor must see exact learner text, score goals, render furigana, and drive the hint ladder.

**LLM:** Any OpenAI-compatible API via `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` in `.env`. Never hardcode hosts or secrets. When `LLM_BASE_URL` is unset, the orchestrator uses scenario-scripted NPC lines and mock tutor JSON.

---

## Repository map

| Path | Role |
| --- | --- |
| `web/` | Vite + React UI — scene, subtitles, mic (future), coach panel |
| `orchestrator/` | FastAPI — sessions, flow engine, WebSocket/REST, LLM client, SQLite |
| `speech-cpu/` | CPU profile: mock ASR + stub WAV TTS (`asr-cpu` / `tts-cpu` containers) |
| `asr/` | GPU ASR service stub → Qwen3-ASR / kotoba-whisper |
| `tts/` | GPU TTS stub → Qwen3-TTS / Irodori / Kokoro |
| `pron/` | Pronunciation scoring stub (M2) |
| `scenarios/` | One YAML per scenario; Pydantic schema in `orchestrator/machi/schema.py` |
| `assets/` | Static backgrounds, sprites (nginx `:8080`) |
| `docs/SPEC.md` | Full architecture, models, latency budgets, milestones |
| `docker-compose.yml` | Profiles: `cpu`, `spark`, `rtx3090` |
| `.env.example` | Documented env vars — copy to `.env`, never commit `.env` |
| `Makefile` | `make up-cpu`, `make test`, `make lint` |

---

## Run

```bash
cp .env.example .env
docker compose --profile cpu up --build      # demo, no model weights
docker compose --env-file .env.spark --profile spark up      # DGX Spark aarch64
docker compose --env-file .env.rtx3090 --profile rtx3090 up  # x86 + 3090 speech
```

- Web UI: http://localhost:5173  
- Orchestrator: http://localhost:8100/health  
- Assets: http://localhost:8080  

---

## Test and lint (match [.github/workflows/ci.yml](.github/workflows/ci.yml))

```bash
# Python (from repo root)
pip install -e "./orchestrator[dev]"
python -m ruff check orchestrator/machi orchestrator/tests
python -m pytest -q orchestrator/tests

# Web
cd web && npm ci && npm run lint && npm run build

# Convenience
make test
make lint
```

Optional romaji: `pip install -e "./orchestrator[nlp]"` (cutlet + MeCab; MIT only).

---

## Conventions and licensing

**Allowed in the default stack:** MIT, Apache-2.0, BSD (commercial-safe).

**Do not add to default dependencies or Docker images:**

| Avoid | Reason |
| --- | --- |
| pykakasi | GPL-3.0 — use **cutlet** + **fugashi** / unidic-lite instead |
| Style-Bert-VITS2 | AGPL |
| Fish Speech, OpenAudio S1-mini, F5-TTS, OmniVoice TTS weights | CC-BY-NC |
| Voxtral 4B TTS | CC-BY-NC |
| Qwen2.5-Omni-3B | Qwen research-only license |

Non-commercial models may only appear behind an explicit research flag if ever added — not in default `cpu` / `spark` / `rtx3090` profiles.

**Secrets:** Never commit `.env`, API keys, or fixed LAN hostnames in code. Use env vars and `.env.example` placeholders.

**Commits:** Conventional commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`). Small, focused PRs.

**Model weights:** Never commit weights; use Hugging Face cache volumes (`hf-cache` in compose).

---

## Hardware and deployment notes

- **Spark (aarch64):** Qwen3-ASR 0.6B/1.7B via transformers/vLLM; avoid CTranslate2 kotoba-whisper (x86). Cap `GPU_MEM_FRACTION` per service.
- **RTX 3090 (x86):** kotoba-whisper-faster or Qwen3-ASR; LLM often remote on Spark via `LLM_BASE_URL`.
- **Both boxes are shared with April** (ComfyUI `:8188`, art workloads). Keep speech service memory and concurrent sessions low; document which profile runs speech where in compose README.
- **CPU demo:** `speech-cpu` only — no large downloads.

Open question **INFRA-01:** Default speech placement when Spark and 3090 are both available — prefer 3090 for ASR/TTS to spare Spark LLM/ComfyUI headroom unless latency tests say otherwise.

---

## Milestone task list

Status: `[x]` done in scaffold (PR #1), `[ ]` not started, `[-]` in progress.

### Scaffold (S0) — largely complete in PR #1

| ID | Status | Specification | Dependencies | Acceptance criteria |
| --- | --- | --- | --- | --- |
| S0-01 | [x] | `docs/SPEC.md` from product canvas | — | Spec covers architecture, models, milestones, license watch |
| S0-02 | [x] | Pydantic scenario schema + `scenarios/restaurant_ramen_01.yaml` | — | `pytest orchestrator/tests/test_scenario_schema.py` passes |
| S0-03 | [x] | Orchestrator flow engine, REST `/sessions`, WS `/ws/{id}`, goal fuzzy match | S0-02 | `test_flow.py`, `test_api.py` pass; `POST /turn` advances greet → seat on `ふたりです` |
| S0-04 | [x] | SQLite sessions + attempts (`orchestrator/machi/db.py`) | S0-03 | File created at `DB_PATH`; rows on session create and turn |
| S0-05 | [x] | OpenAI-compatible LLM client + mock fallback (`llm.py`) | — | `GET /health` reports `llm_mock: true` when `LLM_BASE_URL` empty |
| S0-06 | [x] | `docker-compose.yml` profiles cpu/spark/rtx3090, `.env.example`, `Makefile` | — | `docker compose --profile cpu config` validates |
| S0-07 | [x] | Web CPU demo: scene, sprite, typed turn, stub TTS playback | S0-03, assets | `npm run build` succeeds; manual: send turn shows NPC + audio |
| S0-08 | [x] | `speech-cpu` mock ASR/TTS HTTP API | — | `POST /v1/transcribe` with `text`; `POST /v1/synthesize` returns WAV b64 |
| S0-09 | [x] | GPU stubs `asr/`, `tts/`, `pron/` | — | `/health` returns stub message; not used in `cpu` profile |
| S0-10 | [x] | CI: ruff, pytest, eslint, vite build | — | Workflow in `.github/workflows/ci.yml`; all commands pass locally |
| S0-11 | [x] | Latency logging on orchestrator turns (stages: ASR, LLM, TTS) | S0-03 | Structured log or `X-Latency-*` headers; unit test on timer hooks |

---

### M0 — Voice loop

**Done when:** Talk to a Japanese NPC with **&lt; 2 s** from end of speech to first NPC audio (spec ceiling ~1.9 s; target ~1.0 s on LAN).

| ID | Status | Specification | Dependencies | Acceptance criteria |
| --- | --- | --- | --- | --- |
| M0-01 | [x] | Browser mic: AudioWorklet 16 kHz PCM, push-to-talk + optional hands-free flag | — | `web/src/audio/` captures mic on localhost/https; frames logged in dev |
| M0-02 | [x] | WebSocket binary PCM + JSON events to orchestrator | M0-01, S0-03 | Client sends 20 ms frames; server acks; integration test with fake PCM |
| M0-03 | [ ] | Orchestrator wires turn pipeline: audio → ASR URL → LLM → TTS URL | S0-08 | `session_turn` uses ASR for audio_b64; no typed-only requirement |
| M0-04 | [ ] | **Silero VAD** (onnx, CPU) in orchestrator or `speech-cpu` | M0-02 | End-of-utterance within **500 ms** silence ceiling per spec |
| M0-05 | [ ] | **Smart Turn v3** (BSD-2, CPU) after VAD | M0-04 | Turn-end reduces false cuts on learner pauses; push-to-talk bypass documented |
| M0-06 | [ ] | **Qwen3-ASR-0.6B** streaming in `asr/` (`spark` profile) | S0-09, GPU | `POST /v1/transcribe` returns Japanese text; warm-start &lt; 3 s; streaming partials optional v0 |
| M0-07 | [ ] | **Qwen3-ASR-1.7B** optional via `ASR_ENGINE` env | M0-06 | Switch engine without code change |
| M0-08 | [ ] | **kotoba-whisper-v2.0-faster** on `rtx3090` profile only | M0-06 | x86 compose up; Japanese transcript on sample clip test |
| M0-09 | [ ] | ASR phrase bias from scenario `key_phrases` / `accept` lists | M0-06, S0-02 | Context prompt passed to ASR; test shows better match on beginner phrase |
| M0-10 | [ ] | **Qwen3-TTS 0.6B CustomVoice** streaming in `tts/` | S0-09 | First audio chunk **&lt; 300 ms** ceiling after text; Apache-2.0 |
| M0-11 | [ ] | Barge-in: cancel in-flight TTS/LLM on new speech | M0-02, M0-10 | Web stops playback; server aborts pending calls |
| M0-12 | [ ] | E2E latency test script or pytest marker | M0-03–M0-10 | Documented command; p95 logged; target under **2 s** on reference hardware |
| M0-13 | [ ] | Beginner accent test set (small WAV + expected text) | M0-06 | `tests/fixtures/asr/` checked in (no weights); tracks ASR regressions |

---

### M1 — MVP: ramen shop

**Done when:** Beginner completes restaurant with hints; returning learner can run with default hint level only; debrief persists.

| ID | Status | Specification | Dependencies | Acceptance criteria |
| --- | --- | --- | --- | --- |
| M1-01 | [ ] | **fugashi** + unidic-lite furigana for any NPC line | S0-03 | `nlp.py` token ruby; not only `npc_kana` from YAML; MIT/BSD deps |
| M1-02 | [ ] | **cutlet** romaji on all displayed Japanese (optional extra or default in Docker) | M1-01 | NPC + learner lines show romaji row when hint ≥ 2 |
| M1-03 | [ ] | Hint ladder UI (EN → romaji → kana → none) + Help button | S0-07 | Rung climb on timeout/wrong/help; stars logic stub wired to `success.stars` |
| M1-04 | [ ] | Coach side panel (Sora out-of-role); never block NPC audio | S0-05 | Tutor JSON populates coach; parallel LLM call pattern from spec |
| M1-05 | [ ] | **Irodori-TTS v4.1 Small** for Sora (`guide` voice in YAML) | M0-10 | Distinct voice id for guide vs NPC |
| M1-06 | [ ] | Lip flap via Web Audio analyser on TTS output | S0-07, M0-10 | Mouth sprite cycles with loudness |
| M1-07 | [ ] | Pre-baked WebP background + sprite sheet for ramen (`assets/`) | — | Replace SVG placeholders; `scene.background` paths in YAML |
| M1-08 | [ ] | Scenario flow: debrief node (stars, goals, two corrections) | S0-03 | UI screen after `pay.end`; required goals from `success.required` |
| M1-09 | [ ] | Briefing + warm-up steps before role-play | S0-02 | Key phrases with tap-to-hear (TTS) |
| M1-10 | [ ] | Expand SQLite: stars, hint max per goal, completion flag | S0-04 | Schema migration or version table; debrief writes summary |
| M1-11 | [ ] | LLM NPC + tutor prompt templates from spec | S0-05 | Template files under `orchestrator/prompts/`; JSON tutor schema validated |
| M1-12 | [ ] | Pre-rendered NPC line audio at bake time for fixed `flow.nodes.*.npc` | M0-10, M1-07 | `assets/audio/` map; orchestrator prefers file over live TTS when present |

---

### M2 — Coaching

**Done when:** Debrief shows per-mora pronunciation feedback; FSRS review deck works (spoken mini-drill).

| ID | Status | Specification | Dependencies | Acceptance criteria |
| --- | --- | --- | --- | --- |
| M2-01 | [ ] | **pron/** service: **pyopenjtalk-plus** expected kana/accent | S0-09 | HTTP API returns reading for target phrase |
| M2-02 | [ ] | **Qwen3-ForcedAligner-0.6B** mora timestamps (async) | M2-01 | Scoring off critical path; results within **1–2 s** per spec |
| M2-03 | [ ] | **japanese-hubert-base-phoneme-ctc-v4** actual phonemes | M2-01 | Compare learner ASR audio vs expected; advisory strip in UI |
| M2-04 | [ ] | F0 / pitch-accent advisory (torchcrepe or librosa pyin) | M2-01 | No fail on accent alone |
| M2-05 | [ ] | Correction cards in SQLite + debrief “best two” | M1-08, M2-01 | Phrases from tutor `correction` persisted |
| M2-06 | [ ] | **FSRS** scheduling in SQLite | M2-05 | Due cards query; `srs_tags` from scenarios honored |
| M2-07 | [ ] | 2-minute spoken review mode (Sora mini-situation) | M2-06, M0-10 | End-to-end review session API |

---

### M3 — Neighborhood

**Done when:** Six scenarios on town map; konbini, directions, laundry, taxi, train ticket playable.

| ID | Status | Specification | Dependencies | Acceptance criteria |
| --- | --- | --- | --- | --- |
| M3-01 | [ ] | Town map UI — pick building / locked scenarios | M1-07 | New route in `web/`; lists `GET /scenarios` |
| M3-02 | [ ] | YAML: konbini checkout | S0-02 | Validates; playthrough with CPU or GPU stack |
| M3-03 | [ ] | YAML: directions + **SVG mini-map** + ghost path | M3-01 | Hotspots + pin movement per NPC directions |
| M3-04 | [ ] | YAML: coin laundry (signage goals) | S0-02 | Tappable hotspots from `scene.hotspots` |
| M3-05 | [ ] | YAML: taxi | S0-02 | Win: arrive + pay |
| M3-06 | [ ] | YAML: train ticket | S0-02 | Win: ticket + platform |
| M3-07 | [ ] | Cross-scenario SRS weaving (failed phrase resurfaces) | M2-06, M3-02+ | Integration test with tagged cards |

---

### M4 — Polish

| ID | Status | Specification | Dependencies | Acceptance criteria |
| --- | --- | --- | --- | --- |
| M4-01 | [ ] | Level 3/4 curveballs (`flow.branch` when `level_gte`) | M1-11 | Restaurant firmness question at L3+ |
| M4-02 | [ ] | Sora expression set (6–8) + per-NPC voice map | M1-07, M1-05 | `voices/voices.yaml` complete |
| M4-03 | [ ] | Phone layout (9:16 crop) | M1-07 | Responsive CSS; playable on mobile browser |
| M4-04 | [ ] | HTTPS for LAN (self-signed or Tailscale) | M0-01 | Mic works on phone; documented in README |
| M4-05 | [ ] | **Kokoro-82M** CPU fallback in `speech-cpu` or `tts` | M0-10 | `cpu` profile optional real TTS without GPU |

---

### M5 — Optional / experiments

| ID | Status | Specification | Dependencies | Acceptance criteria |
| --- | --- | --- | --- | --- |
| M5-01 | [ ] | Offline Omni judge on recorded attempts (not live loop) | — | Behind `RESEARCH_OMNI=1`; NC models not in default image |
| M5-02 | [ ] | Scenario editor (YAML + validate in browser) | S0-02 | Export valid scenario file |
| M5-03 | [ ] | ComfyUI bake script (never in `compose up`) | M1-07 | One-shot generates assets to `assets/` |

---

### Infrastructure (INFRA)

| ID | Status | Specification | Dependencies | Acceptance criteria |
| --- | --- | --- | --- | --- |
| INFRA-01 | [ ] | Document speech host strategy (Spark vs 3090 vs split) | S0-06 | ADR in `docs/` or AGENTS update; compose comments |
| INFRA-02 | [ ] | Wire `spark` profile: real ASR+TTS containers, `hf-cache`, GPU limits | M0-06, M0-10 | `docker compose --profile spark up` uses GPU not stubs |
| INFRA-03 | [ ] | Wire `rtx3090` profile: kotoba + Qwen TTS; LLM remote | M0-08, INFRA-02 | `.env.rtx3090` example works |
| INFRA-04 | [ ] | aarch64 Docker: NGC base, sdpa not flash-attn, no arm64 CTranslate2 | INFRA-02 | Multi-arch buildx doc in README |
| INFRA-05 | [ ] | Memory budget table per service on Spark (~12–16 GB speech) | INFRA-02 | `docs/SPEC.md` or `docs/hardware.md` updated with measured notes |

---

## Definition of done (every task)

1. **CI green** — same commands as [.github/workflows/ci.yml](.github/workflows/ci.yml); fix org Actions billing if runners do not start (not a code skip).
2. **Tests** — pytest and/or web tests covering new behavior; no regression in existing suite.
3. **Docs** — update `README.md`, `docs/SPEC.md`, and/or this file when behavior or env vars change.
4. **License check** — new dependencies/models verified Apache/MIT/BSD (or documented research-only flag); no GPL/NC/AGPL in default profile.
5. **No secrets** — `.env.example` only; no committed keys or private hostnames required to run CPU demo.
6. **PR** — focused diff; conventional commit message; not merged unless requested.

---

## Quick reference: spec latency budget (M0+)

| Stage | Target | Ceiling |
| --- | --- | --- |
| End of speech (VAD + Smart Turn) | 250 ms | 500 ms |
| Final ASR | 150 ms | 300 ms |
| LLM first sentence | 350 ms | 700 ms |
| TTS first audio | 150 ms | 300 ms |
| **Total learner stop → NPC speaks** | **~1.0 s** | **~1.9 s** |

---

## Task summary

| Milestone | Tasks | Done in PR #1 |
| --- | ---: | ---: |
| S0 Scaffold | 11 | 10 |
| M0 Voice loop | 13 | 0 |
| M1 Ramen MVP | 12 | 0 |
| M2 Coaching | 7 | 0 |
| M3 Neighborhood | 7 | 0 |
| M4 Polish | 5 | 0 |
| M5 Optional | 3 | 0 |
| INFRA | 5 | 0 |
| **Total** | **63** | **10** |

_Last updated with M0-01 and M0-02 (browser mic + WebSocket PCM). Scaffold baseline remains PR #1._