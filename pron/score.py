"""Advisory F0 contour versus the expected mora pitch pattern.

librosa.pyin (ISC) estimates F0. There is no torch. The comparison is a
shape hint (flat / rising / dropping) marked ok, low, or high. It never
produces a pass/fail score. Equal-time slices stand in until forced
alignment (M2-02).
"""

from __future__ import annotations

import base64
import binascii
import io
import math
import struct
import wave
from collections.abc import Callable
from typing import Any

Pyin = Callable[..., tuple[Any, Any, Any]]

# About two semitones. Smaller wobble stays "flat".
_RISE = 1.12


def decode_audio_b64(audio_b64: str) -> tuple[list[float], int]:
    try:
        raw = base64.b64decode(audio_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid_audio") from exc
    return decode_audio(raw)


def decode_audio(raw: bytes) -> tuple[list[float], int]:
    """16 kHz mono PCM16 WAV, or raw PCM16 interpreted as 16 kHz mono."""
    if not raw:
        raise ValueError("invalid_audio")
    if raw[:4] == b"RIFF":
        return _decode_wav(raw)
    return _pcm16_to_float(raw), 16000


def track_f0(
    samples: list[float],
    sr: int,
    *,
    pyin: Pyin | None = None,
) -> dict[str, Any]:
    """F0 track. Unvoiced frames are null. ``mean_f0`` is the voiced mean."""
    if pyin is None:
        import librosa
        import numpy as np

        y = np.asarray(samples, dtype=np.float64)
        f0, voiced_flag, _probs = librosa.pyin(
            y,
            fmin=65.0,
            fmax=400.0,
            sr=sr,
            frame_length=1024,
            hop_length=160,
        )
        pairs = zip(f0.tolist(), voiced_flag.tolist())
    else:
        f0, voiced_flag, _probs = pyin(samples, fmin=65.0, fmax=400.0, sr=sr)
        pairs = zip(f0, voiced_flag)

    frames: list[float | None] = []
    voiced = 0
    for hz, flag in pairs:
        number = _as_float(hz)
        if bool(flag) and number is not None:
            frames.append(number)
            voiced += 1
        else:
            frames.append(None)
    total = len(frames)
    mean = None
    if voiced:
        mean = sum(value for value in frames if value is not None) / voiced
    return {
        "frames_hz": frames,
        "voiced_ratio": (voiced / total) if total else 0.0,
        "mean_f0": mean,
    }


def advise(reading: dict[str, Any], frames_hz: list[float | None]) -> list[dict[str, Any]]:
    """Per-mora contour advisory. Missing F0 stays ``ok`` so silence is not a miss."""
    moras = reading.get("moras") if isinstance(reading.get("moras"), list) else []
    pattern = [str(item.get("pitch") or "L") for item in moras if isinstance(item, dict)]
    expected = contours_from_pitch(pattern)
    heard = heard_shapes(frames_hz, len(pattern))
    bands: list[dict[str, Any]] = []
    for item, shape, heard_shape in zip(moras, expected, heard):
        if not isinstance(item, dict):
            continue
        bands.append(
            {
                "mora": item.get("mora") or "",
                "expected_pitch": item.get("pitch"),
                "contour": shape,
                "heard": heard_shape,
                "advisory": advisory_label(shape, heard_shape),
            }
        )
    return bands


def contours_from_pitch(pattern: list[str]) -> list[str]:
    """Relative shape of each mora against the previous one. The first is flat."""
    shapes: list[str] = []
    for index, pitch in enumerate(pattern):
        if index == 0:
            shapes.append("flat")
            continue
        previous = pattern[index - 1]
        if previous == pitch:
            shapes.append("flat")
        elif previous == "L" and pitch == "H":
            shapes.append("rising")
        else:
            shapes.append("dropping")
    return shapes


def heard_shapes(frames_hz: list[float | None], count: int) -> list[str | None]:
    if count <= 0:
        return []
    bins: list[list[float]] = [[] for _ in range(count)]
    total = len(frames_hz)
    if total:
        for index, hz in enumerate(frames_hz):
            if hz is None:
                continue
            bin_index = min(count - 1, index * count // total)
            bins[bin_index].append(hz)
    medians = [_median(values) for values in bins]
    shapes: list[str | None] = []
    for index, median in enumerate(medians):
        if median is None:
            shapes.append(None)
            continue
        if index == 0 or medians[index - 1] is None:
            shapes.append("flat")
            continue
        previous = medians[index - 1]
        assert previous is not None
        ratio = median / previous if previous else 1.0
        if ratio >= _RISE:
            shapes.append("rising")
        elif ratio <= 1 / _RISE:
            shapes.append("dropping")
        else:
            shapes.append("flat")
    return shapes


def advisory_label(expected: str, heard: str | None) -> str:
    if heard is None:
        return "ok"
    rank = {"dropping": 0, "flat": 1, "rising": 2}
    delta = rank[heard] - rank[expected]
    if delta == 0:
        return "ok"
    if delta > 0:
        return "high"
    return "low"


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isnan(number):
            return None
        return number
    return None


def _decode_wav(raw: bytes) -> tuple[list[float], int]:
    try:
        with wave.open(io.BytesIO(raw), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.readframes(handle.getnframes())
    except (wave.Error, EOFError) as exc:
        raise ValueError("invalid_audio") from exc
    if width != 2 or rate <= 0 or channels <= 0:
        raise ValueError("invalid_audio")
    samples = _pcm16_to_float(frames)
    if channels > 1:
        samples = samples[::channels]
    if not samples:
        raise ValueError("invalid_audio")
    return samples, rate


def _pcm16_to_float(frames: bytes) -> list[float]:
    count = len(frames) // 2
    if count == 0:
        raise ValueError("invalid_audio")
    unpacked = struct.unpack("<" + "h" * count, frames[: count * 2])
    return [sample / 32768.0 for sample in unpacked]
