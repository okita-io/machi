"""Silero VAD endpoint: silence budget, disabled path, injected probability."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from machi.config import settings
from machi.main import app
from machi.turn_taking import HeuristicTurnScorer, UtteranceGate
from machi.vad import FRAME_MS, SileroOnnxProb, VadEndpoint, resolve_vad_model_path
from machi.ws_audio import PCM_FRAME_BYTES

settings.scenarios_path = str(Path(__file__).resolve().parents[2] / "scenarios")
settings.db_path = str(Path(__file__).resolve().parents[2] / "data" / "test_machi.sqlite")

SILENCE = b"\x00" * PCM_FRAME_BYTES
SILENCE_FRAMES = 500 // FRAME_MS


def _silero_ready() -> bool:
    if not resolve_vad_model_path().is_file():
        return False
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def test_pure_silence_ends_within_500ms_budget():
    """Zero PCM is silence. The endpoint fires on the frame that hits 500 ms."""
    endpoint = VadEndpoint(lambda frame: 0.0)
    ended_at = None
    for index in range(40):
        update = endpoint.push(SILENCE)
        if update.ended:
            ended_at = index + 1
            break
        assert update.silence_ms == (index + 1) * FRAME_MS
    assert ended_at == SILENCE_FRAMES
    assert ended_at * FRAME_MS <= 500


def test_speech_resets_the_silence_run():
    def prob(frame: bytes) -> float:
        del frame
        prob.n += 1
        return 1.0 if prob.n == 10 else 0.0

    prob.n = 0
    endpoint = VadEndpoint(prob, silence_ms=500, frame_ms=20, require_speech=False)
    ended_at = None
    for index in range(50):
        if endpoint.push(SILENCE).ended:
            ended_at = index + 1
            break
    # 9 silence frames, one speech frame, then 25 silence frames.
    assert ended_at == 10 + (500 // 20)


def test_require_speech_ignores_opening_silence():
    endpoint = VadEndpoint(lambda frame: 0.0, require_speech=True)
    for _ in range(40):
        update = endpoint.push(SILENCE)
        assert update.ended is False
        assert update.candidate is False


def test_injected_prob_ends_500ms_after_speech():
    def prob(frame: bytes) -> float:
        del frame
        prob.n += 1
        return 1.0 if prob.n <= 3 else 0.0

    prob.n = 0
    endpoint = VadEndpoint(prob, require_speech=True, silence_ms=500, candidate_ms=250)
    for _ in range(3):
        assert endpoint.push(SILENCE).ended is False
    ended_at = None
    for index in range(40):
        if endpoint.push(SILENCE).ended:
            ended_at = index + 1
            break
    assert ended_at == 500 // FRAME_MS
    assert ended_at * FRAME_MS <= 500


@pytest.mark.skipif(not _silero_ready(), reason="silero_vad.onnx not downloaded")
def test_real_silero_model_scores_silence_below_threshold():
    model = SileroOnnxProb(resolve_vad_model_path())
    probs = [model(SILENCE) for _ in range(50)]
    assert max(probs) < 0.5


def _session(client: TestClient) -> str:
    created = client.post(
        "/sessions",
        json={"scenario_id": "restaurant_ramen_01", "level": 1},
    )
    assert created.status_code == 200
    return created.json()["session_id"]


def _patches():
    async def fake_synthesize(text: str, voice: str = "npc") -> bytes:
        del text, voice
        return b"RIFF"

    async def fake_transcribe(
        audio_pcm: bytes | None = None,
        text_override: str | None = None,
    ) -> str:
        if audio_pcm:
            return "ふたりです"
        return text_override or ""

    return (
        patch("machi.main.synthesize", new=AsyncMock(side_effect=fake_synthesize)),
        patch("machi.main.transcribe", new=AsyncMock(side_effect=fake_transcribe)),
    )


def test_vad_disabled_hands_free_does_not_auto_commit():
    synth, asr = _patches()
    disabled = patch("machi.main.build_turn_gate", return_value=None)
    with synth, asr, disabled, TestClient(app) as client:
        sid = _session(client)
        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "audio_start", "hands_free": True, "skip_warmup": True})
            assert ws.receive_json()["event"] == "audio_start"
            for _ in range(30):
                ws.send_bytes(SILENCE)
                ack = ws.receive_json()
                assert ack["type"] == "audio_ack"
                assert ack["accepted"] is True
            ws.send_json({"type": "turn"})
            result = ws.receive_json()
            assert result["type"] == "turn_result"
            assert result["learner_text"] == "ふたりです"


def test_hands_free_fake_vad_emits_turn_result_within_budget():
    calls = {"score": 0}

    class Counting(HeuristicTurnScorer):
        def score(self, pcm: bytes, *, silence_ms: int):
            calls["score"] += 1
            return super().score(pcm, silence_ms=silence_ms)

    def prob(frame: bytes) -> float:
        del frame
        prob.n += 1
        return 1.0 if prob.n <= 4 else 0.0

    prob.n = 0
    gate = UtteranceGate(
        VadEndpoint(prob, require_speech=True, silence_ms=500, candidate_ms=250),
        Counting(cut_ms=500),
        ceiling_ms=500,
    )
    synth, asr = _patches()
    injected = patch("machi.main.build_turn_gate", return_value=gate)
    with synth, asr, injected, TestClient(app) as client:
        sid = _session(client)
        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "audio_start", "hands_free": True, "skip_warmup": True})
            assert ws.receive_json()["hands_free"] is True
            for _ in range(4 + 24):
                ws.send_bytes(SILENCE)
                ack = ws.receive_json()
                assert ack["type"] == "audio_ack"
            ws.send_bytes(SILENCE)
            ack = ws.receive_json()
            assert ack["accepted"] is True
            result = ws.receive_json()
            assert result["type"] == "turn_result"
            assert result["learner_text"] == "ふたりです"
            # Next utterance stays open; one quiet frame is not another cut.
            ws.send_bytes(SILENCE)
            follow = ws.receive_json()
            assert follow["type"] == "audio_ack"
            assert follow["frames"] == 1
    assert calls["score"] >= 1
