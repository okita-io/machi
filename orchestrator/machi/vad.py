"""Silero VAD endpointing for hands-free turns.

Push-to-talk never constructs a :class:`VadEndpoint`. The WebSocket handler
only feeds frames here when ``audio_start`` set ``hands_free`` true.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from machi.ws_audio import FRAME_MS, PCM_FRAME_BYTES, SAMPLE_RATE

# Spec ceiling: end of speech within 500 ms of trailing silence.
SILENCE_CEILING_MS = 500
# Spec target. The turn scorer may HOLD a candidate until the ceiling.
CANDIDATE_SILENCE_MS = 250
SPEECH_THRESHOLD = 0.5

# Silero v5/v6 ONNX at 16 kHz: 512 new samples plus 64 of context.
SILERO_WINDOW = 512
SILERO_CONTEXT = 64

SpeechProb = Callable[[bytes], float]


@dataclass(frozen=True)
class VadUpdate:
    """One 20 ms frame after the speech probability is applied."""

    silence_ms: int
    speech: bool
    candidate: bool
    ended: bool


class VadEndpoint:
    """End an utterance after trailing silence, measured in frame time.

    ``prob_fn`` maps one 640-byte PCM frame to a speech probability in
    ``[0, 1]``. Tests inject a fake. Production passes :class:`SileroOnnxProb`.

    With ``require_speech`` false, a run of silence ends the utterance at
    ``silence_ms`` (default 500). That is the spec ceiling: 25 frames at the
    20 ms cadence. With ``require_speech`` true, silence before the first
    speech frame does not end the turn, so opening quiet does not submit audio.
    """

    def __init__(
        self,
        prob_fn: SpeechProb,
        *,
        silence_ms: int = SILENCE_CEILING_MS,
        candidate_ms: int = CANDIDATE_SILENCE_MS,
        threshold: float = SPEECH_THRESHOLD,
        frame_ms: int = FRAME_MS,
        require_speech: bool = False,
    ) -> None:
        if silence_ms < frame_ms:
            raise ValueError("silence_ms must cover at least one frame")
        if frame_ms <= 0:
            raise ValueError("frame_ms must be positive")
        self.prob_fn = prob_fn
        self.silence_limit_ms = silence_ms
        self.candidate_ms = min(candidate_ms, silence_ms)
        self.threshold = threshold
        self.frame_ms = frame_ms
        self.require_speech = require_speech
        self.silence_ms = 0
        self.speech_ms = 0
        self.heard_speech = False

    def reset(self) -> None:
        self.silence_ms = 0
        self.speech_ms = 0
        self.heard_speech = False
        reset = getattr(self.prob_fn, "reset", None)
        if callable(reset):
            reset()

    def push(self, frame: bytes) -> VadUpdate:
        if len(frame) != PCM_FRAME_BYTES:
            raise ValueError(f"expected {PCM_FRAME_BYTES}-byte PCM frame")
        prob = float(self.prob_fn(frame))
        speech = prob >= self.threshold
        if speech:
            self.heard_speech = True
            self.speech_ms += self.frame_ms
            self.silence_ms = 0
            counting = False
        elif self.heard_speech or not self.require_speech:
            self.silence_ms += self.frame_ms
            counting = True
        else:
            counting = False
        candidate = counting and self.silence_ms >= self.candidate_ms
        ended = counting and self.silence_ms >= self.silence_limit_ms
        return VadUpdate(
            silence_ms=self.silence_ms,
            speech=speech,
            candidate=candidate,
            ended=ended,
        )


def resolve_vad_model_path(explicit: str = "") -> Path:
    """Cache path for ``silero_vad.onnx``. The file is not in git."""
    if explicit:
        return Path(explicit)
    env = os.environ.get("VAD_MODEL_PATH", "")
    if env:
        return Path(env)
    return Path.cwd() / ".cache" / "vad" / "silero_vad.onnx"


class SileroOnnxProb:
    """Speech probability from the MIT Silero VAD ONNX model (CPU).

    ``onnxruntime`` and ``numpy`` are imported here so the orchestrator core
    install does not depend on them. Build a session only when the model file
    from ``tools/fetch_vad_model.py`` is present.
    """

    def __init__(self, model_path: Path, sample_rate: int = SAMPLE_RATE) -> None:
        import numpy as np
        import onnxruntime as ort

        if sample_rate != SAMPLE_RATE:
            raise ValueError("Silero streaming path expects 16 kHz")
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model_path),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self._np = np
        self._sr = np.array(sample_rate, dtype=np.int64)
        self._input_names = {item.name for item in self._session.get_inputs()}
        self.reset()

    def reset(self) -> None:
        np = self._np
        self._pending = np.zeros(0, dtype=np.float32)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, SILERO_CONTEXT), dtype=np.float32)
        self._last = 0.0

    def __call__(self, frame: bytes) -> float:
        np = self._np
        samples = np.frombuffer(frame, dtype="<i2").astype(np.float32) / 32768.0
        self._pending = np.concatenate([self._pending, samples])
        while self._pending.size >= SILERO_WINDOW:
            chunk = self._pending[:SILERO_WINDOW]
            self._pending = self._pending[SILERO_WINDOW :]
            self._last = self._infer(chunk)
        return self._last

    def _infer(self, chunk: object) -> float:
        np = self._np
        window = np.asarray(chunk, dtype=np.float32).reshape(1, SILERO_WINDOW)
        audio = np.concatenate([self._context, window], axis=1)
        feeds: dict[str, object] = {}
        if "input" in self._input_names:
            feeds["input"] = audio
        if "state" in self._input_names:
            feeds["state"] = self._state
        if "sr" in self._input_names:
            feeds["sr"] = self._sr
        missing = self._input_names - set(feeds)
        if missing:
            raise RuntimeError(f"unsupported Silero ONNX inputs: {sorted(missing)}")
        outs = self._session.run(None, feeds)
        prob = float(np.asarray(outs[0]).reshape(-1)[0])
        if len(outs) > 1:
            self._state = np.asarray(outs[1])
        self._context = audio[:, -SILERO_CONTEXT:]
        return prob
