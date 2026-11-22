"""Debrief writes SQLite progress and GET /sessions/{id}/progress reads it back."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from machi.config import settings
from machi.main import LLM, app

settings.scenarios_path = str(Path(__file__).resolve().parents[2] / "scenarios")
settings.db_path = str(Path(__file__).resolve().parents[2] / "data" / "test_machi.sqlite")


def test_debrief_persists_stars_completion_and_hint_peaks(tmp_path, monkeypatch):
    db_path = tmp_path / "progress.sqlite"
    monkeypatch.setattr(settings, "db_path", str(db_path))

    async def fake_synthesize(text: str, voice: str = "npc") -> bytes:
        del text, voice
        return b"RIFF"

    original = LLM.tutor_json

    async def noting_tutor(**kwargs):
        payload = dict(await original(**kwargs))
        payload["correction_en"] = "Offer the card."
        payload["correction_ja"] = "カードで大丈夫ですか"
        return payload

    lines = [
        ("ふたりです", True, {}),
        ("醤油ラーメン", False, {}),
        ("うん", False, {}),
        (
            "お会計お願いします",
            False,
            {"party_size": 2, "order": 1, "pay": 1},
        ),
    ]
    with (
        patch("machi.main.synthesize", new=AsyncMock(side_effect=fake_synthesize)),
        patch.object(LLM, "tutor_json", noting_tutor),
        TestClient(app) as client,
    ):
        missing = client.get("/sessions/does-not-exist/progress")
        assert missing.status_code == 404

        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        assert created.status_code == 200
        sid = created.json()["session_id"]

        early = client.get(f"/sessions/{sid}/progress")
        assert early.status_code == 200
        assert early.json()["stars"] is None
        assert early.json()["completed"] is False
        assert early.json()["attempts"] == []

        last = None
        for text, skip, hint_max in lines:
            last = client.post(
                f"/sessions/{sid}/turn",
                json={"text": text, "skip_warmup": skip, "hint_max": hint_max},
            )
            assert last.status_code == 200, last.text

        assert last is not None
        body = last.json()
        assert body["type"] == "debrief"
        assert body["stars"] == 2
        assert body["complete"] is True

        progress = client.get(f"/sessions/{sid}/progress")
        assert progress.status_code == 200
        saved = progress.json()
        listed = client.get("/sessions")
        assert listed.status_code == 200

    assert saved["scenario_id"] == "restaurant_ramen_01"
    assert saved["level"] == 1
    assert saved["stars"] == 2
    assert saved["completed"] is True
    assert saved["max_hint_rung"] == 2
    assert saved["hint_max"] == {"party_size": 2, "order": 1, "pay": 1}
    pay = saved["attempts"][-1]
    assert pay["utterance"] == "お会計お願いします"
    assert pay["goal_hits"] == ["pay"]
    assert pay["hint_rung"] == 2
    assert pay["correction_ja"] == "カードで大丈夫ですか"
    assert pay["correction_en"] == "Offer the card."
    assert any(row["session_id"] == sid and row["stars"] == 2 for row in listed.json())
