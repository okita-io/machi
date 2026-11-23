"""GPU ASR: kotoba-whisper via faster-whisper (rtx3090 / x86)."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# NGC PyAV in the 25.01 image rejects metadata_errors; faster-whisper 1.2 passes it.
try:
    import av

    _av_open = av.open

    def _open_compat(*args, **kwargs):
        try:
            return _av_open(*args, **kwargs)
        except TypeError:
            kwargs.pop("metadata_errors", None)
            return _av_open(*args, **kwargs)

    av.open = _open_compat
except ImportError:
    pass

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


def _pcm_samples(data: bytes) -> bytes | None:
    """Int16 frames for a level check. None when the container is not int16 PCM."""
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        import io
        import wave

        try:
            with wave.open(io.BytesIO(data), "rb") as wf:
                if wf.getsampwidth() != 2 or wf.getnchannels() != 1:
                    return None
                return wf.readframes(wf.getnframes())
        except wave.Error:
            return None
    return data


def _float_audio(pcm: bytes):
    """Raw 16 kHz int16 as a float32 waveform the decoder reads directly."""
    import numpy as np

    from audio_io import pcm_peak

    usable = len(pcm) - (len(pcm) % 2)
    if usable < 2 or pcm_peak(pcm) == 0:
        return np.zeros(0, dtype=np.float32)
    samples = np.frombuffer(pcm[:usable], dtype="<i2").astype(np.float32)
    return np.ascontiguousarray(samples / 32768.0)


def _decode(audio: object, language: str, prompt: str | None, *, vad_filter: bool) -> str:
    from audio_io import transcript_from_segments

    segments, _info = _model.transcribe(
        audio,
        language=language,
        condition_on_previous_text=False,
        # Temperature fallback invents a word when the clip is not speech.
        temperature=0.0,
        vad_filter=vad_filter,
        initial_prompt=prompt,
    )
    return transcript_from_segments(segments)


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
    raw = base64.b64decode(body.audio_b64)
    audio_ms = len(raw) // (SAMPLE_RATE // 1000 * 2) if raw else 0
    clip = hashlib.sha256(raw).hexdigest()[:12]
    level = _pcm_samples(raw)
    if len(raw) < SAMPLE_RATE // 10 * 2:
        return {
            "text": "",
            "confidence": 0.0,
            "source": "audio",
            "audio_ms": audio_ms,
            "decode_ms": 0.0,
            "passes": 0,
            "clip": clip,
        }
    from audio_io import clip_is_silent, needs_unfiltered_decode, pcm_peak

    # A muted clip is not a new utterance. Decoding it always yields 「ごめん」.
    if level is not None and clip_is_silent(level):
        logger.info("transcribe clip=%s peak=%s silent", clip, pcm_peak(level))
        return {
            "text": "",
            "confidence": 0.0,
            "source": "silent",
            "audio_ms": audio_ms,
            "decode_ms": 0.0,
            "passes": 0,
            "clip": clip,
            "peak": pcm_peak(level),
        }
    started = time.perf_counter()
    passes = 1
    is_wav = len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WAVE"
    if is_wav:
        wav = raw
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            tmp.write(wav)
            tmp.flush()
            text = _decode(tmp.name, body.language, body.initial_prompt, vad_filter=True)
            if needs_unfiltered_decode(text, len(level or raw)):
                passes = 2
                text = _decode(tmp.name, body.language, body.initial_prompt, vad_filter=False)
    else:
        # Browser push-to-talk is raw 16 kHz PCM. Pass those samples in memory
        # so this request cannot be decoded from a previous file.
        audio = _float_audio(raw)
        text = _decode(audio, body.language, body.initial_prompt, vad_filter=True)
        if needs_unfiltered_decode(text, len(raw)):
            passes = 2
            text = _decode(audio, body.language, body.initial_prompt, vad_filter=False)
    decode_ms = (time.perf_counter() - started) * 1000.0
    logger.info(
        "transcribe clip=%s audio_ms=%s peak=%s decode_ms=%.1f passes=%s text=%r",
        clip,
        audio_ms,
        pcm_peak(level or b""),
        decode_ms,
        passes,
        text,
    )
    return {
        "text": text,
        "confidence": 1.0 if text else 0.0,
        "source": "audio",
        "engine": _engine,
        "audio_ms": audio_ms,
        "decode_ms": round(decode_ms, 1),
        "passes": passes,
        "clip": clip,
        "peak": pcm_peak(level or b""),
    }