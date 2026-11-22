"""Per-turn stage latency timers (ASR, LLM, TTS)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)

STAGE_ASR = "asr"
STAGE_LLM = "llm"
STAGE_TTS = "tts"


class TurnLatency:
    """Records stage durations in milliseconds.

    A stage that did not run is stored as None. It is never recorded as zero.
    """

    def __init__(self) -> None:
        self.stages_ms: dict[str, float | None] = {}

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.stages_ms[stage] = (time.perf_counter() - start) * 1000.0

    def skip(self, stage: str) -> None:
        """Mark a stage as not run (null, not 0)."""
        self.stages_ms[stage] = None

    def rounded_ms(self) -> dict[str, float | None]:
        return {
            stage: (round(ms, 3) if ms is not None else None)
            for stage, ms in self.stages_ms.items()
        }

    def header_map(self) -> dict[str, str]:
        """HTTP headers for stages that ran. Skipped stages are omitted."""
        headers: dict[str, str] = {}
        for stage, ms in self.rounded_ms().items():
            if ms is None:
                continue
            headers[f"X-Latency-{stage.upper()}"] = f"{ms:.3f}"
        return headers

    def emit(self, *, session_id: str) -> dict[str, float | None]:
        """Log one JSON line and return rounded per-stage milliseconds."""
        stages = self.rounded_ms()
        payload = {
            "event": "turn_latency",
            "session_id": session_id,
            "stages_ms": stages,
        }
        logger.info("%s", json.dumps(payload, separators=(",", ":")))
        return stages
