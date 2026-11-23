"""Turn browser PCM16 or a WAV container into a WAV blob for the ASR engine."""

from __future__ import annotations

import io
import struct
import wave

SAMPLE_RATE = 16_000
# 300 ms of 16 kHz mono s16. Shorter than this, an empty VAD result can stand.
# A push-to-talk clip at least this long still has to be decoded.
FULL_DECODE_BYTES = SAMPLE_RATE * 2 * 3 // 10
# Whisper's usual no-speech cutoff. Segments above this are not words.
NO_SPEECH_MAX = 0.6
# About -54 dBFS. kotoba-whisper answers this waveform with 「ごめん」 and a
# low no-speech probability, for silence, noise, and a tone alike.
SILENT_PEAK = 64


def pcm_peak(pcm: bytes) -> int:
    """Largest absolute int16 sample. Odd trailing bytes are ignored."""
    usable = len(pcm) - (len(pcm) % 2)
    if usable < 2:
        return 0
    count = usable // 2
    samples = struct.unpack(f"<{count}h", pcm[:usable])
    return max((sample if sample >= 0 else -sample) for sample in samples)


def clip_is_silent(pcm: bytes, peak_floor: int = SILENT_PEAK) -> bool:
    """True when the clip cannot be a new utterance.

    The model does not return an empty string for this. It returns the same
    word every time, which looks like one recording being reused.
    """
    return pcm_peak(pcm) < peak_floor


def pcm_to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def needs_unfiltered_decode(text: str, audio_bytes: int) -> bool:
    """VAD can reject a whole recording in tens of milliseconds and skip the decoder.

    An empty transcript on a clip of at least 300 ms is not an analysis of the
    samples. The caller has to decode again with the voice-activity filter off.
    """
    if (text or "").strip():
        return False
    return audio_bytes >= FULL_DECODE_BYTES


def transcript_from_segments(segments: object) -> str:
    """Join segment text, dropping segments the model marked as non-speech."""
    parts: list[str] = []
    for segment in segments or []:
        if isinstance(segment, dict):
            no_speech = segment.get("no_speech_prob", 0.0)
            piece = segment.get("text") or ""
        else:
            no_speech = getattr(segment, "no_speech_prob", 0.0)
            piece = getattr(segment, "text", "") or ""
        try:
            skip = float(no_speech or 0) >= NO_SPEECH_MAX
        except (TypeError, ValueError):
            skip = False
        if skip:
            continue
        text = str(piece).strip()
        if text:
            parts.append(text)
    return "".join(parts).strip()


def audio_to_wav(data: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Browser frames are raw PCM16. Fixture clips are already WAV containers."""
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return data
    return pcm_to_wav(data, sample_rate)
