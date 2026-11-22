#!/usr/bin/env python3
"""Bake fixed NPC lines to ``assets/audio/{scenario_id}/{node_id}.wav``.

Calls ``TTS_URL/v1/synthesize`` for every ``flow.nodes.*.npc`` line and writes
``manifest.json`` (``lines`` maps node id to the wav filename). CPU stub voices
are enough for the restaurant scenario; re-run against a real TTS service to
replace the files.

    TTS_URL=http://127.0.0.1:8102 python scripts/bake_npc_audio.py
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "orchestrator"))

from machi.npc_audio import fixed_npc_lines, write_manifest  # noqa: E402
from machi.scenario_loader import load_all_scenarios  # noqa: E402


def synthesize(tts_url: str, text: str, voice: str) -> bytes:
    url = f"{tts_url.rstrip('/')}/v1/synthesize"
    with httpx.Client(timeout=60.0) as client:
        response = client.post(url, json={"text": text, "voice": voice})
        response.raise_for_status()
        payload = response.json()
    audio_b64 = payload.get("audio_b64")
    if not isinstance(audio_b64, str) or not audio_b64:
        raise RuntimeError(f"TTS response missing audio_b64 for voice={voice}")
    return base64.b64decode(audio_b64)


def bake(scenarios_dir: Path, assets_dir: Path, tts_url: str) -> int:
    scenarios = load_all_scenarios(scenarios_dir)
    if not scenarios:
        raise SystemExit(f"no scenarios in {scenarios_dir}")
    written = 0
    for spec in scenarios.values():
        lines = fixed_npc_lines(spec)
        if not lines:
            continue
        voice = spec.npc.voice.engine
        out_dir = assets_dir / "audio" / spec.id
        out_dir.mkdir(parents=True, exist_ok=True)
        files: dict[str, str] = {}
        for node_id, text in lines:
            if "/" in node_id or "\\" in node_id:
                raise SystemExit(f"unsafe node id {node_id!r}")
            wav = synthesize(tts_url, text, voice)
            name = f"{node_id}.wav"
            (out_dir / name).write_bytes(wav)
            files[node_id] = name
            written += 1
            print(f"{spec.id}/{name} {len(wav)} bytes voice={voice}")
        manifest = write_manifest(out_dir, spec.id, voice, files)
        print(f"wrote {manifest}")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Bake fixed NPC lines to assets/audio.")
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=Path(os.environ.get("SCENARIOS_PATH", ROOT / "scenarios")),
    )
    parser.add_argument(
        "--assets",
        type=Path,
        default=Path(os.environ.get("ASSETS_PATH", ROOT / "assets")),
    )
    parser.add_argument(
        "--tts-url",
        default=os.environ.get("TTS_URL", "http://127.0.0.1:8102"),
    )
    args = parser.parse_args()
    count = bake(args.scenarios, args.assets, args.tts_url)
    print(f"baked {count} lines via {args.tts_url}")


if __name__ == "__main__":
    main()
