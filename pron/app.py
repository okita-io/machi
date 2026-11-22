"""CPU pronunciation HTTP API.

``POST /reading`` is the expected mora pattern from pyopenjtalk.
``POST /f0`` and ``POST /score`` compare a learner recording with librosa.pyin.
``/score`` is advisory only: ``is_advisory`` is true and nothing here fails a turn.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

if __package__:
    from .reading import Reader, dictionary_ready, expected_reading
    from .score import advise, decode_audio_b64, track_f0
else:
    from reading import Reader, dictionary_ready, expected_reading
    from score import advise, decode_audio_b64, track_f0

app = FastAPI(title="Machi Pronunciation", version="0.2.0")

reader_override: Reader | None = None
pyin_override: Any = None


class ReadingIn(BaseModel):
    text: str = Field(min_length=1, max_length=400)


class AudioIn(BaseModel):
    audio_b64: str = Field(min_length=1)


class ScoreIn(BaseModel):
    audio_b64: str = Field(min_length=1)
    target_text: str = Field(min_length=1, max_length=400)


@app.get("/health")
def health() -> dict[str, Any]:
    ready = dictionary_ready()
    return {
        "status": "ok" if ready else "degraded",
        "engine": "pyopenjtalk",
        "dictionary": ready,
        "f0": "librosa.pyin",
        "advisory_only": True,
    }


@app.post("/reading")
def reading(body: ReadingIn) -> dict[str, Any]:
    try:
        return expected_reading(body.text, reader=reader_override)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="reading_unavailable") from exc


@app.post("/f0")
def f0(body: AudioIn) -> dict[str, Any]:
    samples, rate = _samples(body.audio_b64)
    try:
        return track_f0(samples, rate, pyin=pyin_override)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="f0_unavailable") from exc


@app.post("/score")
def score(body: ScoreIn) -> dict[str, Any]:
    samples, rate = _samples(body.audio_b64)
    try:
        pattern = expected_reading(body.target_text, reader=reader_override)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="reading_unavailable") from exc
    try:
        tracked = track_f0(samples, rate, pyin=pyin_override)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="f0_unavailable") from exc
    return {
        "is_advisory": True,
        "blocks_turn": False,
        "target_text": body.target_text,
        "bands": advise(pattern, tracked["frames_hz"]),
        "reading": {
            "kana": pattern.get("kana"),
            "accent_type": pattern.get("accent_type"),
            "pitch_pattern": pattern.get("pitch_pattern"),
        },
        "voiced_ratio": tracked["voiced_ratio"],
        "mean_f0": tracked["mean_f0"],
    }


def _samples(audio_b64: str) -> tuple[list[float], int]:
    try:
        samples, rate = decode_audio_b64(audio_b64)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_audio") from exc
    if not samples:
        raise HTTPException(status_code=400, detail="invalid_audio")
    return samples, rate
