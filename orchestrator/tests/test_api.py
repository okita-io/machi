from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from machi.config import settings
from machi.main import app

settings.scenarios_path = str(Path(__file__).resolve().parents[2] / "scenarios")
settings.db_path = str(Path(__file__).resolve().parents[2] / "data" / "test_machi.sqlite")


def test_health_and_session_flow():
    async def fake_synthesize(text: str, voice: str = "npc") -> bytes:
        return b"RIFF"

    with (
        patch("machi.main.synthesize", new=AsyncMock(side_effect=fake_synthesize)),
        TestClient(app) as client,
    ):
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        assert created.status_code == 200
        sid = created.json()["session_id"]

        turn = client.post(
            f"/sessions/{sid}/turn",
            json={"text": "ふたりです", "skip_warmup": True},
        )
        assert turn.status_code == 200
        body = turn.json()
        assert body["goal_hits"] == ["party_size"]
        assert "npc" in body and body["npc"]["ja"]