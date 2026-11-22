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

        listed = client.get("/scenarios")
        assert listed.status_code == 200
        cards = listed.json()
        ramen = next(card for card in cards if card["id"] == "restaurant_ramen_01")
        assert ramen["title_ja"] == "ラーメン屋"
        assert ramen["scene"]["background"].endswith("/bg/ramen.webp")
        assert ramen["scene"]["sprite"].endswith("/sprites/sora/neutral.webp")

        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        assert created.status_code == 200
        created_body = created.json()
        sid = created_body["session_id"]
        assert created_body["scene"]["background"].endswith("/bg/ramen.webp")
        assert created_body["scene"]["guide_sprite"].endswith("/sprites/sora/neutral.webp")

        turn = client.post(
            f"/sessions/{sid}/turn",
            json={"text": "ふたりです", "skip_warmup": True},
        )
        assert turn.status_code == 200
        body = turn.json()
        assert body["goal_hits"] == ["party_size"]
        assert "npc" in body and body["npc"]["ja"]