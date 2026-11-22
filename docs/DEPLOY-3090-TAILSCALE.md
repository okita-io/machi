# Deploy Machi on the RTX 3090, test from the Mac mini (Tailscale)

Two halves:

| Where | Role |
| --- | --- |
| **RTX 3090** | Docker stack: `web`, `orchestrator`, GPU `asr`/`tts`, `pron`, `assets`. Inference and APIs run here. |
| **Mac mini (M4)** | Browser only. No Machi containers required for a smoke test. |

The Mac mini reaches the 3090 over **Tailscale** (or LAN). Speech placement: [ADR-001-speech-placement.md](ADR-001-speech-placement.md) — default is ASR/TTS on the 3090, LLM on Spark via `LLM_BASE_URL`.

## Prerequisites

### On the 3090 (x86 + NVIDIA)

- Docker Engine with [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
- `nvidia-smi` works on the host
- Repo cloned; `cp .env.rtx3090.example .env` and edit `LLM_BASE_URL` to Spark's **Tailscale** URL (e.g. `http://100.x.x.x:8888/v1`)
- Hugging Face cache for first GPU build (large downloads when real ASR/TTS are wired; stubs still validate the layout)
- **Tailscale** installed and same tailnet as the Mac mini
- Firewall allows inbound **5173**, **5174** (and optionally **8080**) from the tailnet

### On the Mac mini

- Tailscale connected
- Repo optional (only for reading docs); testing is in the browser

### On Spark (LLM only)

- OpenAI-compatible server on `:8888` (or your port), reachable from the 3090 over Tailscale
- Do **not** start Machi `asr`/`tts` on Spark when the 3090 is up (see ADR-001)

## 1. HTTPS cert on the 3090 (for microphone from another machine)

Browsers only allow the mic on `localhost` or **HTTPS**. A Mac mini hitting `http://100.x.x.x:5173` will not get a mic.

On the **3090**, from the repo root:

```bash
./scripts/make_lan_https.sh --tailscale "$(tailscale ip -4)"
# optional: --lan <3090-lan-ip>
```

This writes `.certs/machi.crt` / `.certs/machi.key` with SANs for localhost, LAN IP, and Tailscale IPv4.

## 2. Start the stack on the 3090

```bash
docker compose --env-file .env --profile rtx3090 --profile https up --build
```

Services:

| Port | Service |
| --- | --- |
| 5173 | HTTP UI (LAN / quick checks) |
| 5174 | HTTPS UI + `/api` + `/assets` (use from Mac mini for mic) |
| 8100 | Orchestrator (direct API; normally use `/api` via web) |
| 8101–8103 | ASR / TTS / pron (internal + exposed for debugging) |
| 8080 | Assets (optional direct; prefer `/assets` via web) |

`ASSETS_BASE_URL=/assets` in `.env.rtx3090.example` makes the orchestrator return **same-origin** paths so backgrounds and sprites load through nginx (required when the browser is not on the 3090).

## 3. Open on the Mac mini

1. Note the 3090 Tailscale IP: on the 3090, `tailscale ip -4`
2. On the Mac mini, Safari or Chrome: `https://<3090-tailscale-ip>:5174`
3. **Trust the cert** (see README § Phone mic on the LAN) if the browser warns
4. Allow the microphone when prompted
5. Pick a scenario (e.g. Town → ramen). Use push-to-talk or hands-free if VAD models are installed

HTTP-only smoke test (no mic): `http://<3090-tailscale-ip>:5173` — typed turns still work.

## 4. What is real vs stub today

| Piece | `rtx3090` profile |
| --- | --- |
| UI + orchestrator + SQLite | Real |
| LLM | Real when `LLM_BASE_URL` set |
| `asr` / `tts` | **Stubs** until M0-06 / M0-10 are implemented — use **`cpu` profile on the 3090** for a full typed demo with mock speech, or wire models per `docs/SPEC.md` |
| `pron` | CPU advisory service (partial M2) |

For an end-to-end **GPU speech** test later: keep this compose layout, replace stub images with real Qwen3/kotoba containers, pre-pull weights into `hf-cache`, and run `scripts/e2e_latency.py` with `REAL=1`.

## 5. Tailscale Serve (optional)

Instead of self-signed HTTPS on 5174, you can run on the 3090:

```bash
tailscale serve https / http://127.0.0.1:5173
```

That gives a tailnet HTTPS URL without manual cert install on phones. Mic + WebSocket must still be tested on your target device. Machi does not configure Serve in compose.

## 6. Prune stale git branches (Mac mini)

```bash
cd ~/git_repos/machi
git fetch origin --prune
git remote prune origin
```

Only `main` should remain if all agent branches were merged and deleted on GitHub.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Broken images / 404 on backgrounds | `ASSETS_BASE_URL=/assets`; rebuild `web`; hit `https://host:5174/assets/bg/ramen.webp` |
| API errors | `curl -s http://localhost:8100/health` on 3090 |
| LLM failures | From 3090: `curl -s "$LLM_BASE_URL/models"` or your server's health |
| No GPU in container | `docker compose ... exec asr nvidia-smi` |
| Mic blocked | Must use **:5174** HTTPS, not HTTP from a remote host |
| Spark OOM | Stop Spark `asr`/`tts`; keep only LLM on Spark |