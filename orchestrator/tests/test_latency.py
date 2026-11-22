import base64
import json
import logging
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from machi.config import settings
from machi.latency import STAGE_ASR, STAGE_LLM, STAGE_TTS, TurnLatency
from machi.main import app

settings.scenarios_path = str(Path(__file__).resolve().parents[2] / "scenarios")
settings.db_path = str(Path(__file__).resolve().parents[2] / "data" / "test_machi.sqlite")


def test_turn_latency_records_stages_skips_as_null_and_emits(caplog):
    timer = TurnLatency()
    timer.skip(STAGE_ASR)
    with timer.measure(STAGE_LLM):
        time.sleep(0.01)
    with timer.measure(STAGE_TTS):
        time.sleep(0.005)

    with caplog.at_level(logging.INFO, logger="machi.latency"):
        stages = timer.emit(session_id="sess-1")

    assert stages[STAGE_ASR] is None
    assert stages[STAGE_LLM] >= 10
    assert stages[STAGE_TTS] >= 5

    headers = timer.header_map()
    assert "X-Latency-ASR" not in headers
    assert float(headers["X-Latency-LLM"]) == stages[STAGE_LLM]
    assert float(headers["X-Latency-TTS"]) == stages[STAGE_TTS]

    payload = json.loads(caplog.records[-1].message)
    assert payload["event"] == "turn_latency"
    assert payload["session_id"] == "sess-1"
    assert payload["cancelled"] is False
    assert payload["stages_ms"]["asr"] is None
    assert payload["stages_ms"]["llm"] == stages[STAGE_LLM]
    assert payload["stages_ms"]["tts"] == stages[STAGE_TTS]


def test_text_turn_omits_asr_header_and_logs_null(caplog):
    async def fake_synthesize(text: str, voice: str = "npc") -> bytes:
        return b"RIFF"

    with (
        patch("machi.main.synthesize", new=AsyncMock(side_effect=fake_synthesize)),
        patch("machi.main.transcribe", new=AsyncMock()) as transcribe,
        TestClient(app) as client,
        caplog.at_level(logging.INFO, logger="machi.latency"),
    ):
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        assert created.status_code == 200
        sid = created.json()["session_id"]
        turn = client.post(f"/sessions/{sid}/turn", json={"text": "ふたりです"})

    assert turn.status_code == 200
    transcribe.assert_not_called()
    assert "x-latency-asr" not in turn.headers
    assert float(turn.headers["x-latency-llm"]) >= 0
    assert float(turn.headers["x-latency-tts"]) >= 0
    payload = _latency_payload(caplog, sid)
    assert payload["stages_ms"]["asr"] is None
    assert payload["stages_ms"]["llm"] == float(turn.headers["x-latency-llm"])
    assert payload["stages_ms"]["tts"] == float(turn.headers["x-latency-tts"])


def test_audio_turn_records_asr_header():
    async def fake_transcribe(
        audio_pcm: bytes | None = None,
        text_override: str | None = None,
    ) -> str:
        return "ふたりです"

    async def fake_synthesize(text: str, voice: str = "npc") -> bytes:
        return b"RIFF"

    audio_b64 = base64.b64encode(b"\x00\x01").decode("ascii")
    with (
        patch("machi.main.transcribe", new=AsyncMock(side_effect=fake_transcribe)),
        patch("machi.main.synthesize", new=AsyncMock(side_effect=fake_synthesize)),
        TestClient(app) as client,
    ):
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        sid = created.json()["session_id"]
        turn = client.post(f"/sessions/{sid}/turn", json={"audio_b64": audio_b64})

    assert turn.status_code == 200
    assert float(turn.headers["x-latency-asr"]) >= 0
    assert "x-latency-llm" in turn.headers
    assert "x-latency-tts" in turn.headers


def _latency_payload(caplog, session_id: str) -> dict:
    for record in caplog.records:
        if "turn_latency" not in record.message:
            continue
        payload = json.loads(record.message)
        if payload.get("session_id") == session_id:
            return payload
    raise AssertionError("turn_latency log line not found")
