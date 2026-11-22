"""Regenerate beginner-phrase WAVs with macOS say (Kyoko).

Reads tests/fixtures/asr/expected.json and writes 16 kHz mono PCM16 WAVs next
to it. No model weights. Requires the Kyoko voice plus afconvert (macOS).

    python scripts/regen_asr_fixtures.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "asr"
EXPECTED = FIXTURE_DIR / "expected.json"
MAX_BYTES = 100 * 1024
# Drop digital silence Kyoko leaves on either side, then keep 50 ms of pad.
_SILENCE = 400
_PAD_FRAMES = 800


def main() -> int:
    if sys.platform != "darwin":
        print("regen_asr_fixtures.py needs macOS say and afconvert", file=sys.stderr)
        return 1
    for tool in ("say", "afconvert"):
        if shutil.which(tool) is None:
            print(f"missing {tool}", file=sys.stderr)
            return 1
    phrases: dict[str, str] = json.loads(EXPECTED.read_text(encoding="utf-8"))
    if not 5 <= len(phrases) <= 8:
        print(f"expected.json must list 5–8 files, found {len(phrases)}", file=sys.stderr)
        return 1
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in phrases.items():
        if not name.endswith(".wav") or not text.strip():
            print(f"bad entry {name!r}: {text!r}", file=sys.stderr)
            return 1
        dest = FIXTURE_DIR / name
        _speak(text, dest)
        _trim_silence(dest)
        size = dest.stat().st_size
        if size >= MAX_BYTES:
            print(f"{name} is {size} bytes (limit {MAX_BYTES})", file=sys.stderr)
            return 1
        _check_wave(dest)
        print(f"{name}: {size} bytes  {text}")
    return 0


def _speak(text: str, dest: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        aiff = Path(tmp) / "phrase.aiff"
        subprocess.run(["say", "-v", "Kyoko", "-o", str(aiff), text], check=True)
        subprocess.run(
            [
                "afconvert",
                "-f",
                "WAVE",
                "-d",
                "LEI16@16000",
                "-c",
                "1",
                str(aiff),
                str(dest),
            ],
            check=True,
        )


def _trim_silence(path: Path) -> None:
    with wave.open(str(path), "rb") as wf:
        params = wf.getparams()
        raw = wf.readframes(wf.getnframes())
    samples = memoryview(raw).cast("h")
    count = len(samples)
    start = 0
    while start < count and abs(samples[start]) < _SILENCE:
        start += 1
    end = count
    while end > start and abs(samples[end - 1]) < _SILENCE:
        end -= 1
    if start >= end:
        return
    start = max(0, start - _PAD_FRAMES)
    end = min(count, end + _PAD_FRAMES)
    trimmed = raw[start * 2 : end * 2]
    with wave.open(str(path), "wb") as wf:
        wf.setparams(params)
        wf.writeframes(trimmed)


def _check_wave(path: Path) -> None:
    with wave.open(str(path), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
            raise SystemExit(f"{path.name} is not 16 kHz mono PCM16")
        if wf.getnframes() <= 0:
            raise SystemExit(f"{path.name} has no frames")


if __name__ == "__main__":
    raise SystemExit(main())
