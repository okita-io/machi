"""HTTP clients for ASR, TTS, and the pronunciation service."""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Any

import httpx

from machi.config import settings

logger = logging.getLogger(__name__)

PRON_TIMEOUT_S = 1.5

STUB_WAV = base64.b64decode(
    "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAAB9AAACABAAZGF0YQAAAAA="
)


class SpeechError(Exception):
    """ASR or TTS request failed before a usable result came back."""

    def __init__(self, service: str) -> None:
        self.service = service
        super().__init__(service)


async def transcribe(audio_pcm: bytes | None = None, text_override: str | None = None) -> str:
    """POST PCM (or a text override) to ``ASR_URL`` ``/v1/transcribe``."""
    payload: dict = {}
    if text_override:
        payload["text"] = text_override
    if audio_pcm is not None:
        payload["audio_b64"] = base64.b64encode(audio_pcm).decode("ascii")
    url = f"{settings.asr_url.rstrip('/')}/v1/transcribe"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            payload = r.json()
            text = payload.get("text", "")
            digest = hashlib.sha256(audio_pcm).hexdigest()[:8] if audio_pcm else ""
            logging.getLogger("uvicorn.error").info(
                "asr bytes=%s clip=%s audio_ms=%s passes=%s peak=%s text=%r",
                len(audio_pcm or b""),
                digest,
                payload.get("audio_ms"),
                payload.get("passes"),
                payload.get("peak"),
                text if isinstance(text, str) else "",
            )
    except httpx.HTTPError as exc:
        raise SpeechError("asr") from exc
    return text if isinstance(text, str) else ""


async def synthesize(text: str, voice: str = "npc", *, language: str | None = None) -> bytes:
    """POST a line to ``TTS_URL`` ``/v1/synthesize`` and return WAV bytes.

    ``language`` is optional. NPC lines leave it unset so the service stays on
    Japanese. The interpretation reply passes ``Auto`` so English coaching and
    the Japanese phrase can share one clip.
    """
    url = f"{settings.tts_url.rstrip('/')}/v1/synthesize"
    payload: dict[str, str] = {"text": text, "voice": voice}
    if language:
        payload["language"] = language
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            b64 = r.json().get("audio_b64")
    except httpx.HTTPError as exc:
        raise SpeechError("tts") from exc
    if isinstance(b64, str) and b64:
        return base64.b64decode(b64)
    return STUB_WAV


def format_expected_reading(reading: dict[str, Any] | None) -> str:
    """One line for the tutor prompt. Empty or failed readings say unavailable."""
    if not reading:
        return "unavailable"
    kana = reading.get("kana")
    kana_text = kana.strip() if isinstance(kana, str) else ""
    accent = reading.get("accent_type")
    pattern = reading.get("pitch_pattern")
    if isinstance(pattern, list) and pattern:
        pitches = "-".join(str(item) for item in pattern)
    else:
        pitches = ""
    parts: list[str] = []
    if kana_text:
        parts.append(kana_text)
    if accent is not None:
        parts.append(f"accent {accent}")
    if pitches:
        parts.append(f"pitch {pitches}")
    return " ".join(parts) if parts else "unavailable"


async def pron_reading(text: str) -> dict[str, Any] | None:
    """POST ``PRON_URL`` ``/reading``. A blank URL or any failure returns None."""
    return await _pron_post("/reading", {"text": text}, require=text)


async def pron_score(audio: bytes, target_text: str) -> dict[str, Any] | None:
    """POST ``PRON_URL`` ``/score``. Advisory only. Failure returns None."""
    if not audio:
        return None
    body = {
        "audio_b64": base64.b64encode(audio).decode("ascii"),
        "target_text": target_text,
    }
    result = await _pron_post("/score", body, require=target_text)
    if result is None:
        return None
    result["is_advisory"] = True
    return result


async def _pron_post(path: str, payload: dict[str, Any], *, require: str) -> dict[str, Any] | None:
    base = settings.pron_url.strip()
    if not base or not require.strip():
        return None
    url = f"{base.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=PRON_TIMEOUT_S) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        logger.debug("pron %s unavailable", path, exc_info=True)
        return None
    return data if isinstance(data, dict) else None