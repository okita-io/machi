# ADR-001: Where ASR and TTS run

## Status

Accepted. Resolves INFRA-01.

## Context

Machi has three compose profiles:

| Profile | Host | Speech |
| --- | --- | --- |
| `cpu` | any dev machine | `speech-cpu` stubs. No weights. |
| `rtx3090` | x86 desktop, RTX 3090 | ASR and TTS |
| `spark` | DGX Spark, aarch64 | ASR and TTS only when the 3090 is down |

The LLM is an OpenAI-compatible server (`LLM_BASE_URL`), usually on Spark. Both machines are shared with April. ComfyUI listens on `:8188` for art work. Speech weights plus a local LLM plus ComfyUI do not fit on Spark at the same time. Spark also cannot run CTranslate2 kotoba-whisper (x86 only).

## Decision

**Default: put ASR and TTS on the RTX 3090.** Spark keeps its memory for the LLM and for ComfyUI.

- Both GPUs up: `docker compose --env-file .env.rtx3090 --profile rtx3090 up` on the 3090. Point that orchestrator at Spark only for `LLM_BASE_URL`. Do not start `asr` / `tts` on Spark.
- 3090 absent (travel, box off, driver down): `docker compose --env-file .env.spark --profile spark up` so Spark runs speech as well as the LLM. This is the exception, not the steady state.
- No GPU: `docker compose --profile cpu up`. Demo and CI. Stubs only.

Split the other way (ASR on one box, TTS on the other) is not the default. It adds a hop to a budget that is already ~1 s. Revisit only if a measured `REAL=1` latency run shows the 3090 path missing the 2 s gate.

## Keep load off Spark

When the 3090 is available, Spark should not keep ASR or TTS weights resident.

- Leave the Spark `asr` and `tts` containers stopped. Stopping the containers is how those models unload.
- One learner session at a time on whichever box is serving speech.
- Do not point Machi at ComfyUI `:8188`. Art stays on that port; speech stays on `:8101` and `:8102`.
- If April is rendering on the 3090, pause Machi speech or lower `GPU_MEM_FRACTION` on that box. Do not move speech back onto Spark next to the LLM to "get out of the way" unless the 3090 cannot run speech at all.
- If speech must run on Spark, start it only for that session and stop it when the session is over. Prefer the smaller ASR (`ASR_ENGINE=qwen3-asr-0.6b`, not 1.7B) and keep `GPU_MEM_FRACTION` at or below **0.35** per speech process so the LLM and ComfyUI still have room. A measured Spark budget is INFRA-05; until then treat ~12–16 GB as the ceiling for both speech processes together.

## Environment knobs

Set these in `.env`, `.env.spark`, or `.env.rtx3090`. None of them are secrets. Do not commit real hostnames.

| Variable | Role |
| --- | --- |
| `GPU_MEM_FRACTION` | Fraction of one GPU for each of `asr` and `tts`. Compose default **0.40**. Use **≤ 0.35** on Spark when speech has to run there. The CPU profile does not read it. |
| `ASR_ENGINE` | `qwen3-asr-0.6b` (default, both GPUs) or `qwen3-asr-1.7b` (Spark only, when speech is the exception). `kotoba-whisper-faster` is **rtx3090 / x86 only**. |
| `GPU_BASE` | NGC PyTorch base image for the GPU Dockerfiles. Spark (aarch64) and the 3090 (x86) need the matching tag. Default `nvcr.io/nvidia/pytorch:25.01-py3`. |
| `SPEECH_PROFILE` | `rtx3090`, `spark`, `cpu`, or `stub`. The orchestrator walks `voices/voices.yaml` and keeps the first engine that lists this profile. Empty uses each voice's first engine (Irodori for Sora, Qwen3-TTS for NPCs). `cpu` and `stub` are the same bucket: Sora falls through to Kokoro, NPCs to the stub. |
| `ASR_URL` / `TTS_URL` | Where the orchestrator sends audio. CPU defaults are `asr-cpu` and `tts-cpu`. GPU profiles use `http://asr:8101` and `http://tts:8102` on the box that is actually running speech. |
| `LLM_BASE_URL` | Spark (or another OpenAI-compatible host). Unset means the mock tutor. |

Voice engines and licenses live in `voices/voices.yaml`. Sora prefers Irodori-TTS v4.1 Small, then Kokoro-82M, then the stub. NPCs use Qwen3-TTS CustomVoice (`Ono_Anna`).

## Consequences

- The 3090 is the speech host operators should document in the shell they leave up.
- Spark images stay aarch64-safe: transformers / SDPA, no FlashAttention requirement, no CTranslate2. That build note is INFRA-04.
- Kokoro on the CPU profile is declared in the voice map now and wired into `speech-cpu` later (M4-05). Until then the CPU stub accepts the engine name and returns the demo WAV.
- Latency numbers for the 2 s gate are taken on the 3090 speech path (`REAL=1` in `scripts/e2e_latency.py`), with the LLM on the LAN.
