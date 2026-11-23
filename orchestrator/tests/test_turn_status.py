"""Spoken-turn activity: the browser polls this while a recording is processed."""

import base64
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from machi.config import settings
from machi.main import app
from machi.turn_status import note_received, reset_status, snapshot

settings.scenarios_path = str(Path(__file__).resolve().parents[2] / "scenarios")
settings.db_path = str(Path(__file__).resolve().parents[2] / "data" / "test_machi.sqlite")


def test_received_recording_reports_duration():
    reset_status("sess")
    pcm = b"\x00\x00" * 1600
    note_received("sess", base64.b64encode(pcm).decode("ascii"))
    body = snapshot("sess")
    assert body["state"] == "received"
    assert body["audio_bytes"] == len(pcm)
    assert body["audio_ms"] == 100
    assert "0.1 s" in body["detail"]


def test_activity_describes_what_was_recognized():
    async def fake_transcribe(
        audio_pcm: bytes | None = None,
        text_override: str | None = None,
    ) -> str:
        del text_override
        assert audio_pcm
        return "ふたりです"

    async def fake_synthesize(text: str, voice: str = "npc", language: str | None = None) -> bytes:
        del text, voice, language
        return b"RIFF"

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
        idle = client.get(f"/sessions/{sid}/activity")
        assert idle.status_code == 200
        assert idle.json()["state"] == "idle"

        audio_b64 = base64.b64encode(b"\x00\x00" * 1600).decode("ascii")
        spoken = client.post(f"/sessions/{sid}/turn", json={"audio_b64": audio_b64})
        assert spoken.status_code == 200, spoken.text

        activity = client.get(f"/sessions/{sid}/activity")
        body = activity.json()
        assert body["state"] == "done"
        assert body["heard"] == "ふたりです"
        assert body["audio_ms"] == 100
        assert body["matched"] is True
        assert "instead of" not in body["interpreted"]
        assert "ふたり" in body["interpreted"]
        assert "Pronounce it" in body["pronounce"]
        assert "ふたりです" in body["pronounce"]
        assert "Two people" in body["detail"]


def test_activity_names_the_word_heard_instead():
    async def fake_transcribe(
        audio_pcm: bytes | None = None,
        text_override: str | None = None,
    ) -> str:
        del audio_pcm, text_override
        return "ひとりです"

    async def fake_synthesize(text: str, voice: str = "npc", language: str | None = None) -> bytes:
        del text, voice, language
        return b"RIFF"

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
        audio_b64 = base64.b64encode(b"\x00\x00" * 1600).decode("ascii")
        spoken = client.post(f"/sessions/{sid}/turn", json={"audio_b64": audio_b64})
        assert spoken.status_code == 200, spoken.text
        coach = spoken.json()["coach"]["coach_note_en"]
        assert "instead of" in coach
        assert "ふたりです" in coach

        body = client.get(f"/sessions/{sid}/activity").json()
        assert body["state"] == "done"
        assert body["matched"] is False
        assert body["instead"]
        assert "ひとり" in body["instead"][0]["heard"]
        assert "ふたり" in body["instead"][0]["intended"]
        assert "Pronounce it" in body["pronounce"]
