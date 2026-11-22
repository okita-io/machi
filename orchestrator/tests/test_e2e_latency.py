"""p95 helper, plus an in-process spoken turn selected with -m e2e_latency."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "e2e_latency.py"


def _e2e():
    spec = importlib.util.spec_from_file_location("e2e_latency", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_p95_interpolates_between_nearest_ranks():
    e2e = _e2e()
    sample = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    # rank = (10 - 1) * 0.95 = 8.55 → 90 * 0.45 + 100 * 0.55
    assert e2e.percentile(sample, 95) == pytest.approx(95.5)
    assert e2e.percentile([12.0], 95) == 12.0


def test_pcm16_tone_is_16khz_mono_int16():
    e2e = _e2e()
    pcm = e2e.pcm16_tone(duration_ms=320)
    assert len(pcm) == 16000 * 320 // 1000 * 2
    assert len(pcm) % 2 == 0


@pytest.mark.e2e_latency
def test_inprocess_spoken_turn_reports_stages_and_p95(capsys):
    e2e = _e2e()
    summary = e2e.run_latency(turns=2, in_process=True, real=False)
    assert summary["turns"] == 2
    assert summary["real"] is False
    assert summary["p95_ms"] == pytest.approx(
        e2e.percentile([row["e2e_ms"] for row in summary["rows"]], 95)
    )
    for row in summary["rows"]:
        assert row["asr_ms"] >= 0
        assert row["llm_ms"] >= 0
        assert row["tts_ms"] >= 0
        assert row["e2e_ms"] >= row["asr_ms"]
        assert row["wav_bytes"] > 44
    printed = capsys.readouterr().out
    assert "p95 e2e:" in printed
    assert "stub mode" in printed
