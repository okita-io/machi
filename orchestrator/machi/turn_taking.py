"""Turn-end decision after Silero VAD.

Push-to-talk bypasses this module. :func:`hands_free_turn_taking` is the only
gate the WebSocket handler uses: ``hands_free`` false never calls the VAD or
the scorer.

The default :class:`HeuristicTurnScorer` needs no weights, so the CPU demo
can cut turns from silence duration alone. Smart Turn v3 (BSD-2-Clause,
``pipecat-ai/smart-turn-v3``) loads only when ``SMART_TURN_ENABLED=1``.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Protocol, runtime_checkable

from machi.config import settings
from machi.vad import (
    SILENCE_CEILING_MS,
    SpeechProb,
    VadEndpoint,
    VadUpdate,
    resolve_vad_model_path,
)

logger = logging.getLogger(__name__)

# Published CPU checkpoint. BSD-2-Clause. Not bundled in the default image.
SMART_TURN_REPO = "pipecat-ai/smart-turn-v3"
SMART_TURN_FILE = "smart-turn-v3.2-cpu.onnx"
SMART_TURN_MAX_SAMPLES = 8 * 16_000


class TurnDecision(Enum):
    """CUT commits the buffered utterance. HOLD keeps listening."""

    CUT = "cut"
    HOLD = "hold"


@runtime_checkable
class TurnScorer(Protocol):
    """Decide whether a VAD candidate is a real end of turn.

    ``pcm`` is the utterance so far (16 kHz mono s16le). ``silence_ms`` is the
    current trailing-silence run. Implementations must not be required at
    import time to download weights.
    """

    def score(self, pcm: bytes, *, silence_ms: int) -> TurnDecision:
        """Return CUT to commit or HOLD to keep the microphone open."""

    def reset(self) -> None:
        """Drop scorer state at ``audio_start``."""


class HeuristicTurnScorer:
    """Cut once trailing silence reaches ``cut_ms``. No model download.

    Below the threshold the scorer HOLDs, including on an earlier VAD
    candidate, so a short learner pause is not treated as end of turn.
    """

    def __init__(self, cut_ms: int = SILENCE_CEILING_MS) -> None:
        if cut_ms <= 0:
            raise ValueError("cut_ms must be positive")
        self.cut_ms = cut_ms

    def score(self, pcm: bytes, *, silence_ms: int) -> TurnDecision:
        del pcm
        if silence_ms >= self.cut_ms:
            return TurnDecision.CUT
        return TurnDecision.HOLD

    def reset(self) -> None:
        return None


class SmartTurnV3Scorer:
    """Lazy Smart Turn v3 adapter (BSD-2-Clause).

    Weights: Hugging Face ``pipecat-ai/smart-turn-v3`` (override with
    ``SMART_TURN_MODEL``). The published CPU file is ONNX. This class imports
    ``torch``, ``transformers``, and ``onnxruntime`` on the first ``score``
    call and runs them on CPU. It is not imported by the default Docker image
    and is not a core orchestrator dependency.

    A probability at or above ``threshold`` (default 0.5) is CUT. Otherwise
    HOLD. The utterance gate still forces CUT at the 500 ms silence ceiling.
    """

    def __init__(
        self,
        *,
        repo_id: str = SMART_TURN_REPO,
        filename: str = SMART_TURN_FILE,
        model_path: str = "",
        threshold: float = 0.5,
    ) -> None:
        self.repo_id = repo_id
        self.filename = filename
        self.model_path = model_path
        self.threshold = threshold
        self._session = None
        self._extractor = None
        self._np = None
        self._torch = None

    @property
    def loaded(self) -> bool:
        return self._session is not None

    def reset(self) -> None:
        return None

    def score(self, pcm: bytes, *, silence_ms: int) -> TurnDecision:
        del silence_ms
        probability = self._probability(pcm)
        if probability >= self.threshold:
            return TurnDecision.CUT
        return TurnDecision.HOLD

    def _probability(self, pcm: bytes) -> float:
        self._ensure_loaded()
        assert self._np is not None
        assert self._extractor is not None
        assert self._session is not None
        assert self._torch is not None
        np = self._np
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        if audio.size > SMART_TURN_MAX_SAMPLES:
            audio = audio[-SMART_TURN_MAX_SAMPLES:]
        elif audio.size < SMART_TURN_MAX_SAMPLES:
            audio = np.pad(audio, (SMART_TURN_MAX_SAMPLES - audio.size, 0))
        features = self._extractor(
            audio,
            sampling_rate=16_000,
            return_tensors="np",
            padding="max_length",
            max_length=SMART_TURN_MAX_SAMPLES,
            truncation=True,
            do_normalize=True,
        )
        mel = np.asarray(features.input_features, dtype=np.float32)
        if mel.ndim == 2:
            mel = mel[None, ...]
        # Keep the feature tensor on CPU. The ONNX session is CPUExecutionProvider.
        mel = self._torch.from_numpy(mel).cpu().numpy()
        outputs = self._session.run(None, {"input_features": mel})
        return float(np.asarray(outputs[0]).reshape(-1)[0])

    def _ensure_loaded(self) -> None:
        if self._session is not None:
            return
        try:
            import numpy as np
            import onnxruntime as ort
            import torch
            from transformers import WhisperFeatureExtractor
        except ImportError as exc:
            raise ImportError(
                'Smart Turn v3 needs pip install -e "./orchestrator[smart-turn]" '
                "(torch, transformers, onnxruntime). It is not in the default image."
            ) from exc
        torch.set_num_threads(1)
        path = self.model_path or self._download()
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self._session = ort.InferenceSession(
            path,
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self._extractor = WhisperFeatureExtractor(chunk_length=8)
        self._np = np
        self._torch = torch
        logger.info("loaded Smart Turn v3 from %s on CPU", path)

    def _download(self) -> str:
        try:
            from huggingface_hub import hf_hub_download
        except ImportError as exc:
            raise ImportError(
                "Smart Turn download needs huggingface-hub from the smart-turn extra."
            ) from exc
        return hf_hub_download(repo_id=self.repo_id, filename=self.filename)


class UtteranceGate:
    """VAD candidate, then a :class:`TurnScorer`, with a hard silence ceiling.

    The scorer runs once when trailing silence first reaches ``candidate_ms``.
    HOLD keeps the turn open. A later frame at ``ceiling_ms`` (default 500)
    cuts even if the scorer returned HOLD, so a pause cannot exceed the spec.
    """

    def __init__(
        self,
        endpoint: VadEndpoint,
        scorer: TurnScorer,
        *,
        ceiling_ms: int = SILENCE_CEILING_MS,
    ) -> None:
        self.endpoint = endpoint
        self.scorer = scorer
        self.ceiling_ms = ceiling_ms
        self._holding = False

    def reset(self) -> None:
        self._holding = False
        self.endpoint.reset()
        self.scorer.reset()

    def observe(self, frame: bytes, pcm: bytes) -> TurnDecision | None:
        update = self.endpoint.push(frame)
        if update.speech:
            self._holding = False
            return None
        at_ceiling = update.ended or update.silence_ms >= self.ceiling_ms
        if at_ceiling:
            # A HOLD from an earlier candidate cannot outlast the spec ceiling.
            # If this frame is the first candidate, ask the scorer once anyway.
            if not self._holding:
                self._score(pcm, update)
            return TurnDecision.CUT
        if not update.candidate:
            return None
        if self._holding:
            return TurnDecision.HOLD
        if self._score(pcm, update) is TurnDecision.CUT:
            return TurnDecision.CUT
        self._holding = True
        return TurnDecision.HOLD

    def _score(self, pcm: bytes, update: VadUpdate) -> TurnDecision:
        try:
            return self.scorer.score(pcm, silence_ms=update.silence_ms)
        except Exception:
            logger.exception("turn scorer failed; holding until the silence ceiling")
            return TurnDecision.HOLD


def hands_free_turn_taking(hands_free: bool, gate: UtteranceGate | None) -> bool:
    """True only for a hands-free capture with a live gate.

    Push-to-talk (``hands_free`` false) returns false and must not call
    :meth:`UtteranceGate.observe`. A missing model (``gate`` is None) also
    leaves the socket on the client ``turn`` path.
    """

    return hands_free and gate is not None


def load_speech_prob() -> SpeechProb | None:
    """Silero ONNX if the model file and optional extra are available."""
    if not settings.vad_enabled:
        return None
    path = resolve_vad_model_path(settings.vad_model_path)
    if not path.is_file():
        logger.info("Silero VAD model missing at %s; hands-free endpointing off", path)
        return None
    try:
        from machi.vad import SileroOnnxProb

        return SileroOnnxProb(path)
    except Exception:
        logger.exception("Silero VAD failed to load; hands-free endpointing off")
        return None


def build_turn_gate() -> UtteranceGate | None:
    """Hands-free gate, or None when VAD is disabled or the model is absent."""
    prob = load_speech_prob()
    if prob is None:
        return None
    endpoint = VadEndpoint(
        prob,
        silence_ms=settings.vad_silence_ms,
        candidate_ms=settings.vad_candidate_ms,
        threshold=settings.vad_threshold,
        require_speech=settings.vad_require_speech,
    )
    scorer: TurnScorer
    if settings.smart_turn_enabled:
        scorer = SmartTurnV3Scorer(
            repo_id=settings.smart_turn_model or SMART_TURN_REPO,
            filename=settings.smart_turn_filename or SMART_TURN_FILE,
            model_path=settings.smart_turn_model_path,
            threshold=settings.smart_turn_threshold,
        )
        logger.info("Smart Turn v3 enabled; weights load on the first candidate")
    else:
        scorer = HeuristicTurnScorer(cut_ms=settings.vad_silence_ms)
    return UtteranceGate(endpoint, scorer, ceiling_ms=settings.vad_silence_ms)
