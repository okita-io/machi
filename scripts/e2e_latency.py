"""Time a spoken turn: 16-bit PCM in, NPC WAV out.

Default mode starts the orchestrator and the speech-cpu ASR/TTS stubs in this
process and prints per-stage milliseconds plus end-to-end wall time. p95 over
N turns (default 10) is always printed. The 2 s budget is asserted only when
REAL=1 (or --real); stub runs log the comparison and exit 0 so CI stays
deterministic.

    python scripts/e2e_latency.py
    python scripts/e2e_latency.py --turns 10
    ORCH_URL=http://127.0.0.1:8100 python scripts/e2e_latency.py
    REAL=1 ORCH_URL=http://127.0.0.1:8100 python scripts/e2e_latency.py

The clock is POST /sessions/{id}/turn (ASR → LLM → TTS). Push-to-talk already
ended the utterance, so VAD and Smart Turn are outside this measurement.
See the latency budget in docs/SPEC.md.
"""

from __future__ import annotations

import argparse
import base64
import math
import os
import socket
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BUDGET_MS = 2000.0
SAMPLE_RATE = 16000
# Short 16 kHz mono PCM16 tone. The CPU stub transcribes any decodable buffer.
TONE_MS = 320


def percentile(values: list[float], pct: float) -> float:
    """Linear percentile (same rank math as a sorted-sample p95)."""
    if not values:
        raise ValueError("percentile of empty sample")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return ordered[lo]
    weight = rank - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def pcm16_tone(duration_ms: int = TONE_MS, freq: float = 220.0) -> bytes:
    """16 kHz mono little-endian PCM16."""
    count = SAMPLE_RATE * duration_ms // 1000
    frames = bytearray()
    for i in range(count):
        sample = int(8000 * math.sin(2 * math.pi * freq * i / SAMPLE_RATE))
        frames += int(sample).to_bytes(2, "little", signed=True)
    return bytes(frames)


def run_latency(
    *,
    turns: int,
    base_url: str | None = None,
    in_process: bool = False,
    real: bool = False,
) -> dict:
    """Drive ``turns`` spoken turns and print the latency table.

    Returns rows, p95, and whether the 2 s budget was enforced.
    """
    if turns < 1:
        raise ValueError("turns must be >= 1")
    pcm = pcm16_tone()
    audio_b64 = base64.b64encode(pcm).decode("ascii")
    stack = _in_process(mock_llm=not real) if in_process else _null()
    with stack as url:
        target = url if in_process else (base_url or "").rstrip("/")
        if not target:
            raise ValueError("pass --url / ORCH_URL, or run in-process")
        rows = [_one_turn(target, audio_b64, index) for index in range(1, turns + 1)]
    e2e = [row["e2e_ms"] for row in rows]
    p95 = percentile(e2e, 95)
    mode = "in-process stubs" if in_process else target
    _print_table(rows, p95, real=real, mode=mode)
    return {
        "rows": rows,
        "p95_ms": p95,
        "target_ms": BUDGET_MS,
        "real": real,
        "within_budget": p95 < BUDGET_MS,
        "turns": turns,
    }


def _one_turn(base_url: str, audio_b64: str, index: int) -> dict[str, float | int]:
    with httpx.Client(timeout=60.0) as client:
        created = client.post(
            f"{base_url}/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        if created.status_code != 200:
            raise RuntimeError(f"create session failed: {created.status_code} {created.text}")
        session_id = created.json()["session_id"]
        started = time.perf_counter()
        turn = client.post(
            f"{base_url}/sessions/{session_id}/turn",
            json={"audio_b64": audio_b64},
        )
        e2e_ms = (time.perf_counter() - started) * 1000.0
    if turn.status_code != 200:
        raise RuntimeError(f"turn {index} failed: {turn.status_code} {turn.text}")
    body = turn.json()
    audio = base64.b64decode(body.get("tts_audio_b64") or "")
    if len(audio) < 44 or not audio.startswith(b"RIFF"):
        raise RuntimeError(f"turn {index} did not return NPC WAV audio")
    headers = turn.headers
    return {
        "turn": index,
        "asr_ms": _header_ms(headers, "x-latency-asr", index),
        "llm_ms": _header_ms(headers, "x-latency-llm", index),
        "tts_ms": _header_ms(headers, "x-latency-tts", index),
        "e2e_ms": e2e_ms,
        "wav_bytes": len(audio),
    }


def _header_ms(headers: httpx.Headers, name: str, index: int) -> float:
    raw = headers.get(name)
    if raw is None:
        raise RuntimeError(f"turn {index} missing {name}")
    return float(raw)


def _print_table(rows: list[dict], p95: float, *, real: bool, mode: str) -> None:
    print(f"spoken turns: {len(rows)}  pcm: {SAMPLE_RATE} Hz mono int16  mode: {mode}")
    print(f"{'turn':>4}  {'asr_ms':>10}  {'llm_ms':>10}  {'tts_ms':>10}  {'e2e_ms':>10}  {'wav_B':>8}")
    for row in rows:
        print(
            f"{row['turn']:4d}  {row['asr_ms']:10.3f}  {row['llm_ms']:10.3f}  "
            f"{row['tts_ms']:10.3f}  {row['e2e_ms']:10.3f}  {row['wav_bytes']:8d}"
        )
    relation = "under" if p95 < BUDGET_MS else "at or over"
    if real:
        outcome = "PASS" if p95 < BUDGET_MS else "FAIL"
        print(
            f"p95 e2e: {p95:.3f} ms  target: < {BUDGET_MS:.0f} ms  "
            f"({relation} budget)  REAL=1 {outcome}"
        )
    else:
        print(
            f"p95 e2e: {p95:.3f} ms  target: < {BUDGET_MS:.0f} ms  "
            f"({relation} budget)  stub mode: logged only, not asserted "
            f"(set REAL=1 to enforce)"
        )


@contextmanager
def _null() -> Iterator[str]:
    yield ""


@contextmanager
def _in_process(*, mock_llm: bool) -> Iterator[str]:
    """Serve speech-cpu stubs and the orchestrator on loopback ports."""
    _ensure_paths()
    import uvicorn
    from machi.config import settings
    from machi.main import LLM
    from machi.main import app as orch_app
    from speech_cpu.asr_app import app as asr_app
    from speech_cpu.tts_app import app as tts_app

    asr_port = _free_port()
    tts_port = _free_port()
    orch_port = _free_port()
    tmp = tempfile.TemporaryDirectory(prefix="machi-e2e-")
    saved_settings = {
        "asr_url": settings.asr_url,
        "tts_url": settings.tts_url,
        "scenarios_path": settings.scenarios_path,
        "db_path": settings.db_path,
    }
    saved_client = LLM._client
    settings.asr_url = f"http://127.0.0.1:{asr_port}"
    settings.tts_url = f"http://127.0.0.1:{tts_port}"
    settings.scenarios_path = str(ROOT / "scenarios")
    settings.db_path = str(Path(tmp.name) / "e2e.sqlite")
    if mock_llm:
        LLM._client = None
    servers: list[uvicorn.Server] = []
    threads: list[threading.Thread] = []
    try:
        for application, port in (
            (asr_app, asr_port),
            (tts_app, tts_port),
            (orch_app, orch_port),
        ):
            server, thread = _serve(application, port)
            servers.append(server)
            threads.append(thread)
        for port in (asr_port, tts_port, orch_port):
            _wait_health(f"http://127.0.0.1:{port}/health")
        yield f"http://127.0.0.1:{orch_port}"
    finally:
        for server in servers:
            server.should_exit = True
        for thread in threads:
            thread.join(timeout=5)
        LLM._client = saved_client
        for key, value in saved_settings.items():
            setattr(settings, key, value)
        tmp.cleanup()


def _serve(application: object, port: int) -> tuple[object, threading.Thread]:
    import uvicorn

    config = uvicorn.Config(
        application,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name=f"machi-e2e-{port}", daemon=True)
    thread.start()
    return server, thread


def _wait_health(url: str) -> None:
    deadline = time.monotonic() + 15
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=0.5)
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last = exc
        time.sleep(0.05)
    raise RuntimeError(f"health check failed for {url}: {last}")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _ensure_paths() -> None:
    for entry in (ROOT / "orchestrator", ROOT / "speech-cpu"):
        path = str(entry)
        if path not in sys.path:
            sys.path.insert(0, path)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Machi spoken-turn latency (p95)")
    parser.add_argument(
        "--url",
        default=os.environ.get("ORCH_URL", ""),
        help="Running orchestrator base URL. Default: in-process stubs.",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=int(os.environ.get("N") or os.environ.get("E2E_TURNS") or 10),
        help="Number of spoken turns (default 10, or N / E2E_TURNS).",
    )
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="Start orchestrator and speech-cpu stubs in this process.",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="Assert p95 < 2000 ms. Same as REAL=1.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    real = args.real or os.environ.get("REAL") == "1"
    url = (args.url or "").strip()
    in_process = args.in_process or not url
    if url and args.in_process:
        print("pass either --url or --in-process, not both", file=sys.stderr)
        return 2
    try:
        summary = run_latency(
            turns=args.turns,
            base_url=url or None,
            in_process=in_process,
            real=real,
        )
    except (OSError, RuntimeError, ValueError, httpx.HTTPError, ImportError) as exc:
        print(f"e2e latency failed: {exc}", file=sys.stderr)
        return 1
    if real and not summary["within_budget"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
