"""GPU TTS: Qwen3-12Hz-0.6B CustomVoice (NPC + guide via voices.yaml)."""

from __future__ import annotations

import base64
import io
import logging
import os
import struct
import threading
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import soundfile as sf
import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

QWEN_REPO = os.getenv("TTS_QWEN_REPO", "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice")
VOICES_PATH = Path(os.getenv("VOICES", "/voices/voices.yaml"))
GUIDE_SPEAKER = os.getenv("TTS_GUIDE_SPEAKER", "Vivian")

_lock = threading.Lock()
_qwen: Any = None
_engine_meta: dict[str, dict[str, str]] = {}


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=800)
    voice: str = "qwen3_tts"
    language: str = "Japanese"


# Qwen3-TTS CustomVoice language tags. Anything else stays Japanese.
_TTS_LANGUAGES = frozenset(
    {
        "Auto",
        "Chinese",
        "English",
        "French",
        "German",
        "Italian",
        "Japanese",
        "Korean",
        "Portuguese",
        "Russian",
        "Spanish",
    }
)


def _stub_wav(seconds: float = 0.35, hz: int = 440) -> bytes:
    sample_rate = 24_000
    n = int(sample_rate * seconds)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for i in range(n):
            val = int(8000 * (1 if (i // (sample_rate // hz)) % 2 == 0 else -1))
            wf.writeframes(struct.pack("<h", val))
    return buf.getvalue()


def _numpy_to_wav(audio: Any, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, audio, sample_rate, format="WAV")
    return buf.getvalue()


def _load_engine_meta() -> None:
    global _engine_meta
    if not VOICES_PATH.is_file():
        _engine_meta = {
            "qwen3_tts": {"speaker": "Ono_Anna"},
            "kokoro": {"speaker": GUIDE_SPEAKER},
            "irodori": {"speaker": GUIDE_SPEAKER},
        }
        return
    raw = yaml.safe_load(VOICES_PATH.read_text(encoding="utf-8")) or {}
    engines = raw.get("engines") or {}
    for name, body in engines.items():
        if not isinstance(body, dict):
            continue
        speaker = body.get("speaker")
        if isinstance(speaker, str) and speaker:
            _engine_meta[name] = {"speaker": speaker, "repo": str(body.get("repo", ""))}
    if "irodori" not in _engine_meta:
        _engine_meta["irodori"] = {"speaker": GUIDE_SPEAKER}
    if "kokoro" not in _engine_meta:
        _engine_meta["kokoro"] = {"speaker": GUIDE_SPEAKER}


def _load_qwen() -> None:
    global _qwen
    if _qwen is not None:
        return
    import torch
    from qwen_tts import Qwen3TTSModel

    device = os.getenv("TTS_DEVICE", "cuda:0")
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    kwargs: dict[str, Any] = {"device_map": device, "dtype": dtype}
    try:
        _qwen = Qwen3TTSModel.from_pretrained(
            QWEN_REPO, attn_implementation="flash_attention_2", **kwargs
        )
    except Exception:
        logger.info("flash_attention_2 unavailable; using sdpa for Qwen3-TTS")
        _qwen = Qwen3TTSModel.from_pretrained(QWEN_REPO, attn_implementation="sdpa", **kwargs)
    logger.info("Qwen3-TTS ready (%s)", QWEN_REPO)


def _boot_models() -> None:
    _load_engine_meta()
    try:
        _load_qwen()
    except Exception:
        logger.exception("Qwen3-TTS load failed")


def _speaker_for_engine(engine: str) -> str:
    if engine in _engine_meta:
        return _engine_meta[engine].get("speaker", "Ono_Anna")
    if engine in ("kokoro", "irodori"):
        return GUIDE_SPEAKER
    return "Ono_Anna"


def _tts_language(language: str) -> str:
    if language in _TTS_LANGUAGES:
        return language
    return "Japanese"


def _synthesize_locked(text: str, engine: str, language: str = "Japanese") -> tuple[bytes, str]:
    engine = (engine or "stub").strip().lower()
    if engine == "stub":
        return _stub_wav(), "stub"
    if _qwen is None:
        raise RuntimeError("qwen3_tts not loaded")
    # kokoro/irodori still route through Qwen until those engines are wired in-container.
    if engine in ("qwen3_tts", "kokoro", "irodori", "qwen3-tts"):
        speaker = _speaker_for_engine(engine)
        wavs, sr = _qwen.generate_custom_voice(
            text=text,
            language=_tts_language(language),
            speaker=speaker,
        )
        tag = "qwen3_tts" if engine == "qwen3_tts" else f"qwen3_tts_as_{engine}"
        return _numpy_to_wav(wavs[0], sr), tag
    raise RuntimeError(f"unknown engine {engine!r}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=_boot_models, name="tts-model-load", daemon=True).start()
    yield


app = FastAPI(title="Machi TTS", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok" if _qwen is not None else "loading",
        "qwen3_tts": _qwen is not None,
        "repo": QWEN_REPO,
    }


@app.post("/v1/synthesize")
def synthesize(body: SynthesizeRequest) -> dict[str, Any]:
    try:
        with _lock:
            audio, engine_used = _synthesize_locked(body.text, body.voice, body.language)
    except RuntimeError as exc:
        logger.warning("TTS %s failed (%s); stub", body.voice, exc)
        audio, engine_used = _stub_wav(), "stub"
    except Exception:
        logger.exception("TTS synthesize failed")
        raise HTTPException(status_code=500, detail="synthesize_failed") from None
    return {
        "text": body.text,
        "voice": body.voice,
        "engine": engine_used,
        "audio_b64": base64.b64encode(audio).decode("ascii"),
        "format": "wav",
    }