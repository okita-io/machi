#!/usr/bin/env python3
"""Download silero_vad.onnx from the snakers4/silero-vad GitHub release.

The model is MIT-licensed and is not committed (``*.onnx`` is gitignored).
Run from the repo root:

    python tools/fetch_vad_model.py

The file lands in ``.cache/vad/silero_vad.onnx``. Point ``VAD_MODEL_PATH`` at
another path if you move it. Hands-free VAD also needs the optional extra:

    pip install -e "./orchestrator[vad]"
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

SILERO_TAG = "v6.2.3"
SILERO_URL = (
    "https://github.com/snakers4/silero-vad/raw/refs/tags/"
    f"{SILERO_TAG}/src/silero_vad/data/silero_vad.onnx"
)
MIN_BYTES = 1_000_000


def default_dest() -> Path:
    return Path.cwd() / ".cache" / "vad" / "silero_vad.onnx"


def _looks_like_onnx(payload: bytes) -> bool:
    if len(payload) < MIN_BYTES:
        return False
    return not payload.lstrip().startswith((b"<", b"{", b"version https://git-lfs"))


def fetch(dest: Path, url: str = SILERO_URL) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and _looks_like_onnx(dest.read_bytes()):
        print(f"already present: {dest}")
        return dest
    print(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as response:
        payload = response.read()
    if not _looks_like_onnx(payload):
        raise SystemExit(
            "download was not a Silero ONNX file (Git LFS pointer or HTML). "
            f"URL: {url}"
        )
    dest.write_bytes(payload)
    print(f"wrote {dest} ({len(payload)} bytes)")
    return dest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        type=Path,
        default=default_dest(),
        help="output path (default: .cache/vad/silero_vad.onnx)",
    )
    parser.add_argument("--url", default=SILERO_URL, help="override the release URL")
    args = parser.parse_args(argv)
    fetch(args.dest, args.url)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
