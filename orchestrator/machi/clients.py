"""HTTP clients for ASR and TTS services."""

from __future__ import annotations

import base64

import httpx

from machi.config import settings

STUB_WAV = base64.b64decode(
    "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAAB9AAACABAAZGF0YQAAAAA="
)


async def transcribe(audio_pcm: bytes | None = None, text_override: str | None = None) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        payload: dict = {}
        if text_override:
            payload["text"] = text_override
        if audio_pcm:
            payload["audio_b64"] = base64.b64encode(audio_pcm).decode("ascii")
        r = await client.post(f"{settings.asr_url.rstrip('/')}/v1/transcribe", json=payload)
        r.raise_for_status()
        return r.json().get("text", "")


async def synthesize(text: str, voice: str = "npc") -> bytes:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{settings.tts_url.rstrip('/')}/v1/synthesize",
            json={"text": text, "voice": voice},
        )
        r.raise_for_status()
        b64 = r.json().get("audio_b64")
        if b64:
            return base64.b64decode(b64)
        return STUB_WAV