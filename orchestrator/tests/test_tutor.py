"""Tutor payload: Sora expression and hint_max echoed on the turn."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from machi.config import settings
from machi.main import app
from machi.session import default_tutor_payload, expression_from_tutor, normalize_tutor_payload

settings.scenarios_path = str(Path(__file__).resolve().parents[2] / "scenarios")
settings.db_path = str(Path(__file__).resolve().parents[2] / "data" / "test_machi.sqlite")


def test_expression_follows_sentiment_and_explicit_id():
    hit = default_tutor_payload(["party_size"], coach_note="Nice!", hint_rung=1)
    assert hit["sora_expression"] == "cheer"
    assert hit["sentiment"] == "success"
    assert hit["coach_note_sentiment"] == "success"

    miss = default_tutor_payload([], coach_note="Good try!", hint_rung=2)
    assert miss["sora_expression"] == "think"
    assert miss["sentiment"] == "encourage"

    assert expression_from_tutor({"sora_expression": "surprised"}) == "surprised"
    assert expression_from_tutor({"coach_note_sentiment": "sorry"}) == "sorry"
    assert expression_from_tutor({"correction": "ふたりです", "sentiment": "correction"}) == "point"
    merged = normalize_tutor_payload(
        {"coach_note_en": "Almost.", "sentiment": "sorry"},
        fallback=miss,
    )
    assert merged["coach_note_en"] == "Almost."
    assert merged["sora_expression"] == "sorry"


def test_turn_echoes_hint_max_per_goal():
    async def fake_synthesize(text: str, voice: str = "npc") -> bytes:
        del text, voice
        return b"RIFF"

    with (
        patch("machi.main.synthesize", new=AsyncMock(side_effect=fake_synthesize)),
        TestClient(app) as client,
    ):
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 2},
        )
        sid = created.json()["session_id"]
        assert created.json()["stars"]["3"] == "no hints above level default"
        assert created.json()["node_expects"] == ["party_size"]
        turn = client.post(
            f"/sessions/{sid}/turn",
            json={"text": "nope", "hint_max": {"party_size": 3}},
        )

    assert turn.status_code == 200
    body = turn.json()
    assert body["accepted"] is False
    assert body["hint_max"] == {"party_size": 3}
    assert body["coach"]["hint_rung"] == 3
    assert body["coach"]["sora_expression"] == "think"
