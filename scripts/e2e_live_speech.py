#!/usr/bin/env python3
"""Live speech proof: fixture WAV → ASR text → orchestrator turn → NPC WAV.

Sends the beginner clips in ``tests/fixtures/asr/`` the same way the browser
does (16 kHz mono PCM16), then checks three things:

1. ASR decodes the clip (romaji word-error rate).
2. The orchestrator accepts that PCM on ``POST /turn`` and on a WebSocket of
   20 ms frames, and returns the learner transcript.
3. The NPC reply is a real WAV (not the 0.35 s stub beep), and a direct
   ``POST /v1/synthesize`` returns Qwen audio.

Skipped services are a hard failure when you invoke this script. The pytest
marker ``e2e_live`` calls :func:`run_live` and skips when nothing is listening.

    python scripts/e2e_live_speech.py
    ORCH_URL=http://127.0.0.1:8100 python scripts/e2e_live_speech.py --report data/e2e_live_report.json
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import re
import socket
import struct
import sys
import unicodedata
import wave
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "orchestrator"))
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "asr"
EXPECTED_PATH = FIXTURE_DIR / "expected.json"
WER_THRESHOLD = 0.35
SAMPLE_RATE = 16_000
PCM_FRAME_BYTES = 640  # 20 ms at 16 kHz mono int16
# Full spoken turns. The rest of the set is ASR-only so the run stays bounded.
TURN_CLIPS = ("futari_desu.wav", "omizu_kudasai.wav")
WS_CLIP = "futari_desu.wav"
TTS_PROBE = "いらっしゃいませ。何名様ですか？"
_PUNCT = "、。！？!?.,「」『』（）()・"


def load_expected() -> dict[str, str]:
    data = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise RuntimeError(f"expected phrases missing in {EXPECTED_PATH}")
    return {str(name): str(text) for name, text in data.items()}


def wav_pcm16(data: bytes) -> tuple[bytes, int]:
    """Return mono PCM16 frames and their sample rate."""
    with wave.open(io.BytesIO(data), "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    if channels != 1 or width != 2:
        raise RuntimeError(f"need mono PCM16, got channels={channels} width={width}")
    if not frames:
        raise RuntimeError("wav has no frames")
    return frames, rate


def inspect_wav(data: bytes) -> dict[str, float | int | bool]:
    """Duration, RMS, and whether this is the speech-cpu square-wave stub."""
    if len(data) < 44 or not data.startswith(b"RIFF"):
        raise RuntimeError("response is not a RIFF wav")
    with wave.open(io.BytesIO(data), "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        frames = wf.getnframes()
        pcm = wf.readframes(frames)
    if channels != 1 or width != 2 or rate <= 0 or frames <= 0:
        raise RuntimeError(f"unplayable wav channels={channels} width={width} rate={rate}")
    count = len(pcm) // 2
    samples = struct.unpack("<" + "h" * count, pcm[: count * 2])
    mean_sq = sum(sample * sample for sample in samples) / count
    duration = frames / rate
    # The CPU stub is a 0.35 s 440 Hz square wave. Spoken lines are longer.
    stub = duration < 0.5 and len(set(samples)) <= 8
    return {
        "bytes": len(data),
        "sample_rate": rate,
        "duration_s": round(duration, 3),
        "rms": round(math.sqrt(mean_sq), 1),
        "stub": stub,
    }


def romaji_tokens(text: str) -> list[str]:
    from machi.nlp import to_romaji

    cleaned = unicodedata.normalize("NFKC", text)
    # Kotoba often writes the party size as "2人" instead of ふたり / 二人.
    cleaned = re.sub(r"(?<![0-9])2人", "二人", cleaned)
    cleaned = re.sub(r"(?<![0-9])1人", "一人", cleaned)
    cleaned = re.sub(r"(?<![0-9])1つ", "一つ", cleaned)
    for char in _PUNCT:
        cleaned = cleaned.replace(char, " ")
    return [tok for tok in to_romaji(cleaned).lower().split() if tok]


def wer(reference: str, hypothesis: str) -> float:
    ref = romaji_tokens(reference)
    hyp = romaji_tokens(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return _edit_distance(ref, hyp) / len(ref)


def _edit_distance(left: list[str], right: list[str]) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, token in enumerate(left, start=1):
        current = [i]
        for j, other in enumerate(right, start=1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            substitute = previous[j - 1] + (token != other)
            current.append(min(insert, delete, substitute))
        previous = current
    return previous[-1]


def _health(client: httpx.Client, url: str) -> dict:
    response = client.get(f"{url.rstrip('/')}/health")
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError(f"{url} /health was not an object")
    return body


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _asr_clip(client: httpx.Client, asr_url: str, wav: bytes, reference: str) -> dict:
    response = client.post(
        f"{asr_url.rstrip('/')}/v1/transcribe",
        json={"audio_b64": _b64(wav), "language": "ja"},
    )
    response.raise_for_status()
    body = response.json()
    hypothesis = str(body.get("text") or "")
    return {
        "reference": reference,
        "hypothesis": hypothesis,
        "wer": round(wer(reference, hypothesis), 3),
        "engine": body.get("engine"),
        "source": body.get("source"),
        "confidence": body.get("confidence"),
        "wav_bytes_sent": len(wav),
    }


def _turn(
    client: httpx.Client,
    orch_url: str,
    pcm: bytes,
    reference: str,
) -> dict:
    created = client.post(
        f"{orch_url.rstrip('/')}/sessions",
        json={"scenario_id": "restaurant_ramen_01", "level": 1},
    )
    created.raise_for_status()
    session_id = created.json()["session_id"]
    response = client.post(
        f"{orch_url.rstrip('/')}/sessions/{session_id}/turn",
        json={"audio_b64": _b64(pcm), "skip_warmup": True},
    )
    if response.status_code != 200:
        raise RuntimeError(f"turn failed: {response.status_code} {response.text}")
    body = response.json()
    audio = base64.b64decode(body.get("tts_audio_b64") or "")
    heard = inspect_wav(audio)
    hypothesis = str(body.get("learner_text") or "")
    npc = body.get("npc")
    npc_text = npc.get("ja") if isinstance(npc, dict) else ""
    return {
        "session_id": session_id,
        "pcm_bytes_sent": len(pcm),
        "reference": reference,
        "learner_text": hypothesis,
        "wer": round(wer(reference, hypothesis), 3),
        "goal_hits": body.get("goal_hits") or [],
        "npc_text": npc_text,
        "asr_ms": response.headers.get("x-latency-asr"),
        "llm_ms": response.headers.get("x-latency-llm"),
        "tts_ms": response.headers.get("x-latency-tts"),
        "tts_source": response.headers.get("x-latency-tts-source"),
        "playback": heard,
    }


def _tts_probe(client: httpx.Client, tts_url: str) -> dict:
    response = client.post(
        f"{tts_url.rstrip('/')}/v1/synthesize",
        json={"text": TTS_PROBE, "voice": "qwen3_tts"},
    )
    response.raise_for_status()
    body = response.json()
    audio = base64.b64decode(body.get("audio_b64") or "")
    heard = inspect_wav(audio)
    return {
        "text": TTS_PROBE,
        "engine": body.get("engine"),
        "voice": body.get("voice"),
        "playback": heard,
    }


def _ws_turn(orch_url: str, pcm: bytes, reference: str) -> dict:
    parsed = urlparse(orch_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    created = httpx.post(
        f"{orch_url.rstrip('/')}/sessions",
        json={"scenario_id": "restaurant_ramen_01", "level": 1},
        timeout=30.0,
    )
    created.raise_for_status()
    session_id = created.json()["session_id"]
    path = f"/ws/{session_id}"
    frames = _pcm_frames(pcm)
    with socket.create_connection((host, port), timeout=120) as sock:
        sock.settimeout(120)
        _ws_handshake(sock, host, port, path)
        _ws_send_text(sock, json.dumps({"type": "audio_start", "skip_warmup": True}))
        start_ack = json.loads(_ws_recv_text(sock))
        acked = 0
        for frame in frames:
            _ws_send_binary(sock, frame)
            ack = json.loads(_ws_recv_text(sock))
            if ack.get("type") == "audio_ack" and ack.get("accepted") is True:
                acked += 1
        _ws_send_text(sock, json.dumps({"type": "audio_stop"}))
        stop_ack = json.loads(_ws_recv_text(sock))
        _ws_send_text(sock, json.dumps({"type": "turn", "skip_warmup": True}))
        result = json.loads(_ws_recv_text(sock))
    if result.get("type") != "turn_result":
        raise RuntimeError(f"websocket turn returned {result!r}")
    audio = base64.b64decode(result.get("tts_audio_b64") or "")
    hypothesis = str(result.get("learner_text") or "")
    return {
        "session_id": session_id,
        "pcm_bytes_sent": len(pcm),
        "frames_sent": len(frames),
        "frames_acked": acked,
        "audio_start": start_ack,
        "audio_stop": stop_ack,
        "reference": reference,
        "learner_text": hypothesis,
        "wer": round(wer(reference, hypothesis), 3),
        "goal_hits": result.get("goal_hits") or [],
        "playback": inspect_wav(audio),
    }


def _pcm_frames(pcm: bytes) -> list[bytes]:
    frames: list[bytes] = []
    for offset in range(0, len(pcm), PCM_FRAME_BYTES):
        chunk = pcm[offset : offset + PCM_FRAME_BYTES]
        if len(chunk) < PCM_FRAME_BYTES:
            chunk = chunk + b"\x00" * (PCM_FRAME_BYTES - len(chunk))
        frames.append(chunk)
    return frames


def _ws_handshake(sock: socket.socket, host: str, port: int, path: str) -> None:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("ascii"))
    header = b""
    while b"\r\n\r\n" not in header:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("websocket handshake closed")
        header += chunk
    status = header.split(b"\r\n", 1)[0]
    if b" 101 " not in status:
        raise RuntimeError(f"websocket upgrade failed: {status!r}")


def _ws_send_text(sock: socket.socket, text: str) -> None:
    _ws_send(sock, text.encode("utf-8"), opcode=0x1)


def _ws_send_binary(sock: socket.socket, payload: bytes) -> None:
    _ws_send(sock, payload, opcode=0x2)


def _ws_send(sock: socket.socket, payload: bytes, *, opcode: int) -> None:
    mask = os.urandom(4)
    length = len(payload)
    header = bytearray([0x80 | opcode])
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header += length.to_bytes(2, "big")
    else:
        header.append(0x80 | 127)
        header += length.to_bytes(8, "big")
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    sock.sendall(bytes(header) + mask + masked)


def _ws_recv_text(sock: socket.socket) -> str:
    chunks: list[bytes] = []
    while True:
        opcode, payload = _ws_recv(sock)
        if opcode == 0x1:
            return payload.decode("utf-8")
        if opcode == 0x2:
            return payload.decode("utf-8")
        if opcode == 0x8:
            raise RuntimeError("websocket closed")
        if opcode == 0x9:
            _ws_send(sock, payload, opcode=0xA)
            continue
        if opcode == 0x0:
            chunks.append(payload)
            continue
        chunks.append(payload)
        if chunks:
            return b"".join(chunks).decode("utf-8")


def _ws_recv(sock: socket.socket) -> tuple[int, bytes]:
    first = _recv_exact(sock, 2)
    opcode = first[0] & 0x0F
    masked = bool(first[1] & 0x80)
    length = first[1] & 0x7F
    if length == 126:
        length = int.from_bytes(_recv_exact(sock, 2), "big")
    elif length == 127:
        length = int.from_bytes(_recv_exact(sock, 8), "big")
    mask = _recv_exact(sock, 4) if masked else b""
    payload = _recv_exact(sock, length)
    if mask:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return opcode, payload


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    buf = bytearray()
    while len(buf) < count:
        chunk = sock.recv(count - len(buf))
        if not chunk:
            raise RuntimeError("socket closed during websocket frame")
        buf += chunk
    return bytes(buf)


def run_live(
    *,
    orch_url: str,
    asr_url: str,
    tts_url: str,
) -> dict:
    """Drive the live stack. ``ok`` is false when any check fails; errors are listed."""
    expected = load_expected()
    errors: list[str] = []
    timeout = httpx.Timeout(180.0, connect=10.0)
    with httpx.Client(timeout=timeout) as client:
        services = {
            "orchestrator": _health(client, orch_url),
            "asr": _health(client, asr_url),
            "tts": _health(client, tts_url),
        }
        if services["asr"].get("status") != "ok":
            errors.append(f"asr not ready: {services['asr']}")
        if not services["tts"].get("qwen3_tts"):
            errors.append(f"tts not ready: {services['tts']}")

        asr_rows: list[dict] = []
        for name, reference in expected.items():
            wav = (FIXTURE_DIR / name).read_bytes()
            row = _asr_clip(client, asr_url, wav, reference)
            row["file"] = name
            asr_rows.append(row)
            if row["wer"] > WER_THRESHOLD:
                errors.append(
                    f"asr {name} wer={row['wer']} hyp={row['hypothesis']!r} ref={reference!r}"
                )

        turns: list[dict] = []
        for name in TURN_CLIPS:
            reference = expected[name]
            pcm, rate = wav_pcm16((FIXTURE_DIR / name).read_bytes())
            if rate != SAMPLE_RATE:
                errors.append(f"{name} sample rate {rate} != {SAMPLE_RATE}")
            row = _turn(client, orch_url, pcm, reference)
            row["file"] = name
            turns.append(row)
            if row["wer"] > WER_THRESHOLD:
                errors.append(
                    f"turn {name} wer={row['wer']} learner={row['learner_text']!r}"
                )
            if not row["asr_ms"]:
                errors.append(f"turn {name} missing X-Latency-ASR")
            playback = row["playback"]
            if playback["stub"] or playback["rms"] < 100:
                errors.append(f"turn {name} playback is stub or silent: {playback}")

        party = next(row for row in turns if row["file"] == "futari_desu.wav")
        if "party_size" not in party["goal_hits"]:
            errors.append(f"futari_desu did not hit party_size: {party['goal_hits']}")

        ws_pcm, _rate = wav_pcm16((FIXTURE_DIR / WS_CLIP).read_bytes())
        websocket = _ws_turn(orch_url, ws_pcm, expected[WS_CLIP])
        websocket["file"] = WS_CLIP
        if websocket["frames_acked"] != websocket["frames_sent"]:
            errors.append(
                f"websocket acked {websocket['frames_acked']} of {websocket['frames_sent']} frames"
            )
        if websocket["wer"] > WER_THRESHOLD:
            errors.append(
                f"websocket wer={websocket['wer']} learner={websocket['learner_text']!r}"
            )
        if "party_size" not in websocket["goal_hits"]:
            errors.append(f"websocket missed party_size: {websocket['goal_hits']}")
        if websocket["playback"]["stub"]:
            errors.append(f"websocket playback is stub: {websocket['playback']}")

        tts = _tts_probe(client, tts_url)
        engine = str(tts.get("engine") or "")
        if not engine.startswith("qwen3_tts"):
            errors.append(f"direct tts engine {engine!r}")
        if tts["playback"]["stub"] or tts["playback"]["duration_s"] < 0.8:
            errors.append(f"direct tts not spoken audio: {tts['playback']}")

    report = {
        "ok": not errors,
        "wer_threshold": WER_THRESHOLD,
        "services": services,
        "asr": asr_rows,
        "turns": turns,
        "websocket": websocket,
        "tts": tts,
        "errors": errors,
    }
    return report


def _print_report(report: dict) -> None:
    print("services:")
    for name, body in report["services"].items():
        print(f"  {name}: {json.dumps(body, ensure_ascii=False)}")
    print("asr:")
    for row in report["asr"]:
        print(
            f"  {row['file']}: wer={row['wer']} hyp={row['hypothesis']!r} "
            f"sent={row['wav_bytes_sent']}B"
        )
    print("turns:")
    for row in report["turns"]:
        play = row["playback"]
        print(
            f"  {row['file']}: wer={row['wer']} learner={row['learner_text']!r} "
            f"goals={row['goal_hits']} tts={row['tts_source']} "
            f"wav={play['duration_s']}s rms={play['rms']}"
        )
    ws = report["websocket"]
    print(
        f"websocket {ws['file']}: frames {ws['frames_acked']}/{ws['frames_sent']} "
        f"wer={ws['wer']} learner={ws['learner_text']!r} "
        f"wav={ws['playback']['duration_s']}s"
    )
    tts = report["tts"]
    print(
        f"tts: engine={tts['engine']} duration={tts['playback']['duration_s']}s "
        f"rms={tts['playback']['rms']}"
    )
    if report["ok"]:
        print("PASS live speech")
    else:
        print("FAIL live speech")
        for error in report["errors"]:
            print(f"  - {error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Live ASR/TTS proof against a running stack.")
    parser.add_argument("--orch-url", default=os.environ.get("ORCH_URL", "http://127.0.0.1:8100"))
    parser.add_argument("--asr-url", default=os.environ.get("ASR_URL", "http://127.0.0.1:8101"))
    parser.add_argument("--tts-url", default=os.environ.get("TTS_URL", "http://127.0.0.1:8102"))
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "data" / "e2e_live_report.json",
    )
    args = parser.parse_args()
    report = run_live(orch_url=args.orch_url, asr_url=args.asr_url, tts_url=args.tts_url)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _print_report(report)
    print(f"report: {args.report}")
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
