"""Turn scorer contract, heuristic hold/cut, and push-to-talk bypass."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from machi.config import settings
from machi.main import app
from machi.turn_taking import (
    HeuristicTurnScorer,
    SmartTurnV3Scorer,
    TurnDecision,
    TurnScorer,
    UtteranceGate,
    hands_free_turn_taking,
)
from machi.vad import VadEndpoint
from machi.ws_audio import PCM_FRAME_BYTES

settings.scenarios_path = str(Path(__file__).resolve().parents[2] / "scenarios")
settings.db_path = str(Path(__file__).resolve().parents[2] / "data" / "test_machi.sqlite")

SILENCE = b"\x00" * PCM_FRAME_BYTES


def test_scorer_protocol_and_heuristic_hold_cut():
    heuristic = HeuristicTurnScorer(cut_ms=500)
    assert isinstance(heuristic, TurnScorer)
    assert heuristic.score(b"", silence_ms=250) is TurnDecision.HOLD
    assert heuristic.score(SILENCE, silence_ms=499) is TurnDecision.HOLD
    assert heuristic.score(SILENCE, silence_ms=500) is TurnDecision.CUT

    smart = SmartTurnV3Scorer()
    assert isinstance(smart, TurnScorer)
    assert smart.loaded is False


def test_gate_holds_on_candidate_and_cuts_at_ceiling():
    def prob(frame: bytes) -> float:
        del frame
        prob.n += 1
        return 1.0 if prob.n == 1 else 0.0

    prob.n = 0
    scores: list[int] = []

    class Recording(HeuristicTurnScorer):
        def score(self, pcm: bytes, *, silence_ms: int) -> TurnDecision:
            scores.append(silence_ms)
            return super().score(pcm, silence_ms=silence_ms)

    gate = UtteranceGate(
        VadEndpoint(prob, require_speech=True, silence_ms=500, candidate_ms=250),
        Recording(cut_ms=500),
        ceiling_ms=500,
    )
    assert gate.observe(SILENCE, SILENCE) is None  # speech
    held_at = None
    cut_at = None
    pcm = bytearray(SILENCE)
    for index in range(1, 40):
        pcm.extend(SILENCE)
        decision = gate.observe(SILENCE, bytes(pcm))
        silence_frames = index
        if decision is TurnDecision.HOLD and held_at is None:
            held_at = silence_frames
        if decision is TurnDecision.CUT:
            cut_at = silence_frames
            break
    assert held_at is not None
    assert held_at * 20 >= 250
    assert held_at * 20 < 500
    assert cut_at == 25
    assert cut_at * 20 <= 500
    assert scores[0] < 500
    assert all(value < 500 for value in scores)


def test_scorer_cut_before_ceiling_is_honored():
    def prob(frame: bytes) -> float:
        del frame
        prob.n += 1
        return 0.0 if prob.n > 1 else 1.0

    prob.n = 0

    class AlwaysCut:
        def score(self, pcm: bytes, *, silence_ms: int) -> TurnDecision:
            del pcm, silence_ms
            return TurnDecision.CUT

        def reset(self) -> None:
            return None

    gate = UtteranceGate(
        VadEndpoint(prob, require_speech=True, candidate_ms=250, silence_ms=500),
        AlwaysCut(),
        ceiling_ms=500,
    )
    gate.observe(SILENCE, SILENCE)
    cut_at = None
    for index in range(1, 40):
        if gate.observe(SILENCE, SILENCE * (index + 1)) is TurnDecision.CUT:
            cut_at = index
            break
    assert cut_at is not None
    assert 250 <= cut_at * 20 < 500


def test_ceiling_overrides_a_hold_scorer():
    def prob(frame: bytes) -> float:
        del frame
        prob.n += 1
        return 0.0 if prob.n > 1 else 1.0

    prob.n = 0

    class AlwaysHold:
        def score(self, pcm: bytes, *, silence_ms: int) -> TurnDecision:
            del pcm, silence_ms
            return TurnDecision.HOLD

        def reset(self) -> None:
            return None

    assert isinstance(AlwaysHold(), TurnScorer)
    gate = UtteranceGate(
        VadEndpoint(prob, require_speech=True, candidate_ms=250, silence_ms=500),
        AlwaysHold(),
        ceiling_ms=500,
    )
    gate.observe(SILENCE, SILENCE)
    cut_at = None
    for index in range(1, 40):
        decision = gate.observe(SILENCE, SILENCE)
        if decision is TurnDecision.CUT:
            cut_at = index
            break
    assert cut_at == 25


def test_push_to_talk_helper_bypasses_gate():
    gate = UtteranceGate(VadEndpoint(lambda frame: 0.0), HeuristicTurnScorer())
    assert hands_free_turn_taking(False, gate) is False
    assert hands_free_turn_taking(True, None) is False
    assert hands_free_turn_taking(True, gate) is True


def test_push_to_talk_websocket_does_not_call_vad_or_scorer():
    touches = {"vad": 0, "score": 0, "reset": 0}

    def prob(frame: bytes) -> float:
        del frame
        touches["vad"] += 1
        return 0.0

    class TouchScorer:
        def score(self, pcm: bytes, *, silence_ms: int) -> TurnDecision:
            del pcm, silence_ms
            touches["score"] += 1
            return TurnDecision.CUT

        def reset(self) -> None:
            touches["reset"] += 1

    gate = UtteranceGate(
        VadEndpoint(prob, require_speech=False, silence_ms=500, candidate_ms=20),
        TouchScorer(),
        ceiling_ms=500,
    )

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

    with (
        patch("machi.main.synthesize", new=AsyncMock(side_effect=fake_synthesize)),
        patch("machi.main.transcribe", new=AsyncMock(side_effect=fake_transcribe)),
        patch("machi.main.build_turn_gate", return_value=gate),
        TestClient(app) as client,
    ):
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        sid = created.json()["session_id"]
        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "audio_start", "hands_free": False})
            started = ws.receive_json()
            assert started["hands_free"] is False
            for _ in range(30):
                ws.send_bytes(SILENCE)
                ack = ws.receive_json()
                assert ack["type"] == "audio_ack"
                assert "turn_result" not in ack["type"]
            ws.send_json({"type": "turn", "skip_warmup": True})
            result = ws.receive_json()
            assert result["type"] == "turn_result"
            assert result["learner_text"] == "ふたりです"
    assert touches == {"vad": 0, "score": 0, "reset": 0}
