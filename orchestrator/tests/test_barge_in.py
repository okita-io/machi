"""Barge-in cancels an in-flight WebSocket turn before its result is sent."""

import asyncio
import json
import logging
import threading
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from machi.config import settings
from machi.main import app

settings.scenarios_path = str(Path(__file__).resolve().parents[2] / "scenarios")
settings.db_path = str(Path(__file__).resolve().parents[2] / "data" / "test_machi.sqlite")


def _latency_payloads(caplog, session_id: str) -> list[dict]:
    found: list[dict] = []
    for record in caplog.records:
        if "turn_latency" not in record.message:
            continue
        payload = json.loads(record.message)
        if payload.get("session_id") == session_id:
            found.append(payload)
    return found


def test_audio_start_cancels_inflight_turn_and_logs_cancelled_flag(caplog):
    entered = threading.Event()
    calls = {"n": 0}

    async def slow_synthesize(text: str, voice: str = "npc") -> bytes:
        del text, voice
        calls["n"] += 1
        if calls["n"] == 1:
            entered.set()
            # Stay inside the TTS await until barge-in cancels this task.
            for _ in range(300):
                await asyncio.sleep(0.01)
        return b"RIFF"

    with (
        patch("machi.main.synthesize", new=AsyncMock(side_effect=slow_synthesize)),
        patch("machi.main.transcribe", new=AsyncMock()),
        TestClient(app) as client,
        caplog.at_level(logging.INFO, logger="machi.latency"),
    ):
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        assert created.status_code == 200
        sid = created.json()["session_id"]
        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "turn", "text": "ふたりです"})
            assert entered.wait(2)
            ws.send_json({"type": "audio_start"})
            ack = ws.receive_json()
            assert ack["type"] == "audio_ack"
            assert ack["event"] == "audio_start"
            ws.send_json({"type": "turn", "text": "ふたりです"})
            result = ws.receive_json()

    assert result["type"] == "turn_result"
    assert result["learner_text"] == "ふたりです"
    assert result["goal_hits"] == ["party_size"]
    payloads = _latency_payloads(caplog, sid)
    cancelled = [payload for payload in payloads if payload.get("cancelled") is True]
    finished = [payload for payload in payloads if payload.get("cancelled") is False]
    assert len(cancelled) == 1
    assert "stages_ms" in cancelled[0]
    assert len(finished) == 1
    assert calls["n"] == 2


def test_new_turn_cancels_inflight_turn():
    entered = threading.Event()
    calls = {"n": 0}

    async def slow_synthesize(text: str, voice: str = "npc") -> bytes:
        del text, voice
        calls["n"] += 1
        if calls["n"] == 1:
            entered.set()
            for _ in range(300):
                await asyncio.sleep(0.01)
        return b"RIFF"

    with (
        patch("machi.main.synthesize", new=AsyncMock(side_effect=slow_synthesize)),
        patch("machi.main.transcribe", new=AsyncMock()),
        TestClient(app) as client,
    ):
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        sid = created.json()["session_id"]
        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "turn", "text": "ふたりです"})
            assert entered.wait(2)
            ws.send_json({"type": "turn", "text": "ふたりです"})
            result = ws.receive_json()

    assert result["type"] == "turn_result"
    assert result["learner_text"] == "ふたりです"
    assert result["goal_hits"] == ["party_size"]
    assert calls["n"] == 2
