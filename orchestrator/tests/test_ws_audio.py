"""WebSocket binary PCM frames and JSON control events."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from machi.config import settings
from machi.main import app
from machi.ws_audio import PCM_FRAME_BYTES

settings.scenarios_path = str(Path(__file__).resolve().parents[2] / "scenarios")
settings.db_path = str(Path(__file__).resolve().parents[2] / "data" / "test_machi.sqlite")

PCM_FRAME = b"\x10\x00" * (PCM_FRAME_BYTES // 2)


def test_pcm_frame_is_20ms_int16():
    assert PCM_FRAME_BYTES == 640
    assert len(PCM_FRAME) == 640


def test_ws_typed_turn_still_works():
    async def fake_synthesize(text: str, voice: str = "npc") -> bytes:
        return b"RIFF"

    transcribe = AsyncMock(return_value="ふたりです")
    with (
        patch("machi.main.synthesize", new=AsyncMock(side_effect=fake_synthesize)),
        patch("machi.main.transcribe", new=transcribe),
        TestClient(app) as client,
    ):
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        assert created.status_code == 200
        sid = created.json()["session_id"]
        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "turn", "text": "ふたりです", "skip_warmup": True})
            result = ws.receive_json()
        assert result["type"] == "turn_result"
        assert result["goal_hits"] == ["party_size"]
        assert result["learner_text"] == "ふたりです"
        transcribe.assert_not_called()


def test_ws_pcm_frames_acked_and_start_stop():
    async def fake_synthesize(text: str, voice: str = "npc") -> bytes:
        return b"RIFF"

    async def fake_transcribe(
        audio_pcm: bytes | None = None,
        text_override: str | None = None,
    ) -> str:
        if audio_pcm:
            return "ふたりです"
        return text_override or ""

    transcribe = AsyncMock(side_effect=fake_transcribe)
    with (
        patch("machi.main.synthesize", new=AsyncMock(side_effect=fake_synthesize)),
        patch("machi.main.transcribe", new=transcribe),
        TestClient(app) as client,
    ):
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        sid = created.json()["session_id"]
        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_bytes(PCM_FRAME)
            early = ws.receive_json()
            assert early["type"] == "audio_ack"
            assert early["frames"] == 0
            assert early["accepted"] is False

            ws.send_json({"type": "audio_start", "hands_free": True})
            started = ws.receive_json()
            assert started == {
                "type": "audio_ack",
                "frames": 0,
                "event": "audio_start",
                "hands_free": True,
            }

            ws.send_bytes(b"\x00" * 100)
            rejected = ws.receive_json()
            assert rejected["type"] == "audio_ack"
            assert rejected["frames"] == 0
            assert rejected["accepted"] is False

            ws.send_bytes(PCM_FRAME)
            first = ws.receive_json()
            assert first["type"] == "audio_ack"
            assert first["frames"] == 1
            assert first["accepted"] is True
            assert first["bytes"] == 640

            ws.send_bytes(PCM_FRAME)
            second = ws.receive_json()
            assert second["frames"] == 2

            ws.send_json({"type": "audio_stop"})
            stopped = ws.receive_json()
            assert stopped["type"] == "audio_ack"
            assert stopped["event"] == "audio_stop"
            assert stopped["frames"] == 2
            assert stopped["bytes"] == 1280

            ws.send_json({"type": "turn", "skip_warmup": True})
            result = ws.receive_json()
            assert result["type"] == "turn_result"
            assert result["learner_text"] == "ふたりです"
            assert result["goal_hits"] == ["party_size"]

            ws.send_json({"type": "turn", "skip_warmup": True})
            drained = ws.receive_json()
            assert drained["type"] == "turn_result"

        assert transcribe.await_count == 2
        first_call, second_call = transcribe.await_args_list
        assert first_call.kwargs["audio_pcm"] == PCM_FRAME + PCM_FRAME
        assert "audio_pcm" not in second_call.kwargs
        assert second_call.kwargs["text_override"] == ""
