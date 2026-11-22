"""HTTP clients for ASR and TTS services."""

from __future__ import annotations

import base64

import httpx

from machi.config import settings

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
            text = r.json().get("text", "")
    except httpx.HTTPError as exc:
        raise SpeechError("asr") from exc
    return text if isinstance(text, str) else ""


async def synthesize(text: str, voice: str = "npc") -> bytes:
    """POST the NPC line to ``TTS_URL`` ``/v1/synthesize`` and return WAV bytes."""
    url = f"{settings.tts_url.rstrip('/')}/v1/synthesize"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json={"text": text, "voice": voice})
            r.raise_for_status()
            b64 = r.json().get("audio_b64")
    except httpx.HTTPError as exc:
        raise SpeechError("tts") from exc
    if isinstance(b64, str) and b64:
        return base64.b64decode(b64)
    return STUB_WAV