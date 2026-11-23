"""GPU ASR: kotoba-whisper via faster-whisper (rtx3090 / x86)."""

from __future__ import annotations

import base64
import io
import logging
import os
import tempfile
import threading
import wave
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000

ENGINE_MODELS: dict[str, str] = {
    "kotoba-whisper-faster": "kotoba-tech/kotoba-whisper-v2.0-faster",
}

_engine = os.getenv("ASR_ENGINE", "kotoba-whisper-faster").strip()
_model: Any = None


class TranscribeRequest(BaseModel):
    text: str | None = None
    audio_b64: str | None = None
    language: str = "ja"
    initial_prompt: str | None = None


def _pcm_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


def _load_model() -> None:
    global _model
    model_id = ENGINE_MODELS.get(_engine)
    if not model_id:
        logger.warning("ASR engine %s is not wired", _engine)
        return
    from faster_whisper import WhisperModel

    device = os.getenv("ASR_DEVICE", "cuda")
    compute = os.getenv("ASR_COMPUTE_TYPE", "float16")
    logger.info("loading ASR model=%s device=%s compute=%s", model_id, device, compute)
    _model = WhisperModel(model_id, device=device, compute_type=compute)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    def _boot() -> None:
        try:
            _load_model()
        except Exception:
            logger.exception("ASR model load failed")

    threading.Thread(target=_boot, name="asr-model-load", daemon=True).start()
    yield


app = FastAPI(title="Machi ASR", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, Any]:
    wired = _engine in ENGINE_MODELS
    if wired and _model is not None:
        return {
            "status": "ok",
            "engine": _engine,
            "model": ENGINE_MODELS[_engine],
        }
    if wired:
        return {"status": "loading", "engine": _engine}
    return {
        "status": "stub",
        "engine": _engine,
        "message": "Set ASR_ENGINE=kotoba-whisper-faster on x86",
    }


@app.post("/v1/transcribe")
def transcribe(body: TranscribeRequest) -> dict[str, Any]:
    if body.text:
        return {"text": body.text, "confidence": 1.0, "source": "typed"}
    if not body.audio_b64:
        return {"text": "", "confidence": 0.0, "source": "empty"}
    if _model is None:
        raise HTTPException(status_code=503, detail="model_not_ready")
    pcm = base64.b64decode(body.audio_b64)
    if len(pcm) < SAMPLE_RATE // 10 * 2:
        return {"text": "", "confidence": 0.0, "source": "audio"}
    wav = _pcm_to_wav(pcm)
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        tmp.write(wav)
        tmp.flush()
        segments, info = _model.transcribe(
            tmp.name,
            language=body.language,
            condition_on_previous_text=False,
            vad_filter=True,
            initial_prompt=body.initial_prompt or None,
        )
        text = "".join(segment.text for segment in segments).strip()
    confidence = float(getattr(info, "language_probability", 0.0) or 0.0)
    return {
        "text": text,
        "confidence": confidence,
        "source": "audio",
        "engine": _engine,
    }