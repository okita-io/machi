"""Offline checks for the live speech harness, plus an opt-in stack run.

``pytest -m e2e_live`` posts ``tests/fixtures/asr/*.wav`` at the running
orchestrator, ASR, and TTS. A default ``pytest`` only checks that the clips
decode to 16 kHz PCM and that the harness can score a transcript.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = ROOT / "scripts" / "e2e_live_speech.py"


def _harness():
    spec = importlib.util.spec_from_file_location("e2e_live_speech", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _asr_audio_to_wav():
    path = ROOT / "asr" / "audio_io.py"
    spec = importlib.util.spec_from_file_location("machi_asr_audio_io", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.audio_to_wav


def test_fixture_clips_are_16k_pcm_and_frame_cleanly():
    live = _harness()
    expected = live.load_expected()
    assert expected["futari_desu.wav"] == "ふたりです"
    for name in expected:
        pcm, rate = live.wav_pcm16((live.FIXTURE_DIR / name).read_bytes())
        assert rate == 16_000
        assert len(pcm) >= live.PCM_FRAME_BYTES
        frames = live._pcm_frames(pcm)
        assert all(len(frame) == live.PCM_FRAME_BYTES for frame in frames)
        assert b"".join(frames).startswith(pcm)


def test_near_silent_clip_is_not_a_transcript():
    path = ROOT / "asr" / "audio_io.py"
    spec = importlib.util.spec_from_file_location("machi_asr_audio_io_level", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.clip_is_silent(b"\x00\x00" * 16000) is True
    assert module.pcm_peak(b"\x00\x00" * 1600) == 0
    loud = (200).to_bytes(2, "little", signed=True) * 1600
    assert module.clip_is_silent(loud) is False
    assert module.pcm_peak(loud) == 200


def test_long_empty_clip_must_be_decoded_without_vad():
    path = ROOT / "asr" / "audio_io.py"
    spec = importlib.util.spec_from_file_location("machi_asr_audio_io_policy", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # 78 frames of 20 ms is 1.56 s. An empty VAD result has not read the words.
    assert module.needs_unfiltered_decode("", 78 * 640) is True
    assert module.needs_unfiltered_decode("ふたりです", 78 * 640) is False
    assert module.needs_unfiltered_decode("", 1600) is False
    kept = module.transcript_from_segments(
        [
            {"text": " ふたりです ", "no_speech_prob": 0.1},
            {"text": "ご視聴ありがとう", "no_speech_prob": 0.9},
        ]
    )
    assert kept == "ふたりです"


def test_wav_container_is_not_rewrapped_as_pcm():
    audio_to_wav = _asr_audio_to_wav()
    wav = (ROOT / "tests" / "fixtures" / "asr" / "futari_desu.wav").read_bytes()
    assert audio_to_wav(wav) == wav
    pcm, _rate = _harness().wav_pcm16(wav)
    wrapped = audio_to_wav(pcm)
    assert wrapped.startswith(b"RIFF")
    assert wrapped != pcm


def test_stub_beep_is_flagged_and_spoken_wav_is_not():
    live = _harness()
    stub = (ROOT / "speech-cpu" / "speech_cpu" / "tts_app.py").read_text(encoding="utf-8")
    assert "0.35" in stub or "440" in stub
    spoken = (ROOT / "assets" / "audio" / "restaurant_ramen_01" / "greet.wav").read_bytes()
    info = live.inspect_wav(spoken)
    assert info["stub"] is False
    assert info["duration_s"] > 0.8
    assert info["rms"] > 100


def test_identical_phrase_has_zero_wer():
    live = _harness()
    assert live.wer("ふたりです", "二人です") == 0.0
    assert live.wer("ふたりです", "2人です。") == 0.0


def _stack_up(url: str) -> bool:
    try:
        response = httpx.get(f"{url.rstrip('/')}/health", timeout=2.0)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


@pytest.mark.e2e_live
def test_live_stack_hears_fixture_and_speaks_back(tmp_path: Path):
    orch = os.environ.get("ORCH_URL", "http://127.0.0.1:8100")
    asr = os.environ.get("ASR_URL", "http://127.0.0.1:8101")
    tts = os.environ.get("TTS_URL", "http://127.0.0.1:8102")
    if not all(_stack_up(url) for url in (orch, asr, tts)):
        pytest.skip("ORCH_URL, ASR_URL, and TTS_URL must all answer /health")
    report = _harness().run_live(orch_url=orch, asr_url=asr, tts_url=tts)
    path = tmp_path / "e2e_live_report.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    assert report["ok"], "\n".join(report["errors"])
    assert report["asr"]
    assert report["turns"][0]["playback"]["bytes"] > 1000
    assert report["websocket"]["frames_acked"] > 0
    assert str(report["tts"]["engine"]).startswith("qwen3_tts")
