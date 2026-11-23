"""Live status for a spoken turn, polled by the browser once a second."""

from __future__ import annotations

import base64
import binascii
import hashlib
import time
from typing import Any

# 16 kHz mono signed 16-bit: 32 bytes is one millisecond.
_BYTES_PER_MS = 32

_STATUSES: dict[str, dict[str, Any]] = {}


def snapshot(session_id: str) -> dict[str, Any]:
    """Current processing status. Idle when this session has not spoken yet."""
    found = _STATUSES.get(session_id)
    if found is None:
        return _idle()
    return dict(found)


def note_received(session_id: str, audio_b64: str) -> None:
    """The browser posted a recording. Duration comes from the PCM byte count."""
    audio_bytes = _pcm_bytes(audio_b64)
    audio_ms = audio_bytes // _BYTES_PER_MS
    clip = _clip_id(audio_b64)
    detail = f"Received {audio_ms / 1000:.1f} s of speech"
    if clip:
        detail += f" (clip {clip})"
    detail += ". Waiting to transcribe it."
    _put(
        session_id,
        state="received",
        detail=detail,
        heard="",
        audio_bytes=audio_bytes,
        audio_ms=audio_ms,
    )


def note_stage(session_id: str, state: str, detail: str, *, heard: str | None = None) -> None:
    """Move the in-flight turn to the next stage, keeping the recording size."""
    current = _STATUSES.get(session_id) or _idle()
    _put(
        session_id,
        state=state,
        detail=detail,
        heard=current.get("heard", "") if heard is None else heard,
        audio_bytes=int(current.get("audio_bytes") or 0),
        audio_ms=int(current.get("audio_ms") or 0),
    )


def note_done(
    session_id: str,
    heard: str,
    *,
    goal_hits: list[str] | None = None,
    warmup_passed: bool | None = None,
    interpretation: dict[str, Any] | None = None,
) -> None:
    """Final coaching: words heard instead of the target, then how to say it."""
    current = _STATUSES.get(session_id) or _idle()
    audio_ms = int(current.get("audio_ms") or 0)
    text = heard.strip()
    if interpretation:
        detail = str(interpretation.get("detail") or "")
        text = str(interpretation.get("heard") or text)
    else:
        seconds = f"{audio_ms / 1000:.1f} s" if audio_ms else "the recording"
        parts = [f"Sent {seconds} of speech from the browser for recognition."]
        if text:
            parts.append(f"Recognized 「{text}」.")
        else:
            parts.append("No words were recognized.")
        if goal_hits:
            parts.append(f"Matched {', '.join(goal_hits)}.")
        elif warmup_passed is True:
            parts.append("That matched the warm-up phrase.")
        elif warmup_passed is False:
            parts.append("That did not match the warm-up phrase.")
        detail = " ".join(parts)
    _put(
        session_id,
        state="done",
        detail=detail,
        heard=text,
        audio_bytes=int(current.get("audio_bytes") or 0),
        audio_ms=audio_ms,
        interpretation=interpretation,
    )


def note_error(session_id: str, detail: str) -> None:
    current = _STATUSES.get(session_id) or _idle()
    _put(
        session_id,
        state="error",
        detail=detail or "The turn failed.",
        heard=str(current.get("heard") or ""),
        audio_bytes=int(current.get("audio_bytes") or 0),
        audio_ms=int(current.get("audio_ms") or 0),
    )


def reset_status(session_id: str | None = None) -> None:
    """Test helper. Clears one session, or every session when id is omitted."""
    if session_id is None:
        _STATUSES.clear()
        return
    _STATUSES.pop(session_id, None)


def _pcm_bytes(audio_b64: str) -> int:
    raw = _pcm(audio_b64)
    return len(raw) if raw is not None else 0


def _clip_id(audio_b64: str) -> str:
    """Short hash of this recording. A new hold has a new id."""
    raw = _pcm(audio_b64)
    if not raw:
        return ""
    return hashlib.sha256(raw).hexdigest()[:8]


def _pcm(audio_b64: str) -> bytes | None:
    try:
        return base64.b64decode(audio_b64, validate=True)
    except (binascii.Error, ValueError):
        return None


def _interpretation_fields(info: dict[str, Any] | None) -> dict[str, Any]:
    source = info or {}
    instead = source.get("instead")
    return {
        "intended_ja": str(source.get("intended_ja") or ""),
        "intended_kana": str(source.get("intended_kana") or ""),
        "intended_romaji": str(source.get("intended_romaji") or ""),
        "instead": list(instead) if isinstance(instead, list) else [],
        "interpreted": str(source.get("interpreted") or ""),
        "pronounce": str(source.get("pronounce") or ""),
        "spoken_interpreted": str(source.get("spoken_interpreted") or ""),
        "spoken_pronounce": str(source.get("spoken_pronounce") or ""),
        "matched": bool(source.get("matched")),
    }


def _idle() -> dict[str, Any]:
    return {
        "state": "idle",
        "detail": "",
        "heard": "",
        "audio_bytes": 0,
        "audio_ms": 0,
        **_interpretation_fields(None),
    }


def _put(
    session_id: str,
    *,
    state: str,
    detail: str,
    heard: str,
    audio_bytes: int,
    audio_ms: int,
    interpretation: dict[str, Any] | None = None,
) -> None:
    _STATUSES[session_id] = {
        "state": state,
        "detail": detail,
        "heard": heard,
        "audio_bytes": audio_bytes,
        "audio_ms": audio_ms,
        "updated_at": time.time(),
        **_interpretation_fields(interpretation),
    }
