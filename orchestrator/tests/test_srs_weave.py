"""Due cards with a shared tag show up in another scenario's briefing and warm-up."""

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from machi.config import settings
from machi.main import app
from machi.scenario_loader import load_scenario

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "scenarios"
settings.scenarios_path = str(SCENARIOS)


def test_scenario_tags_form_shared_groups():
    owners: dict[str, set[str]] = {}
    for path in sorted(SCENARIOS.glob("*.yaml")):
        spec = load_scenario(path)
        for tag in spec.srs_tags:
            owners.setdefault(tag, set()).add(spec.id)
    shared = {tag: ids for tag, ids in owners.items() if len(ids) >= 2}
    assert len(shared) >= 2
    assert shared["ordering"] >= {
        "restaurant_ramen_01",
        "konbini_checkout_01",
        "taxi_01",
    }
    assert "counters" in shared
    assert len(list(SCENARIOS.glob("*.yaml"))) == 6


def test_restaurant_miss_surfaces_in_konbini_warmup(tmp_path, monkeypatch):
    db_path = tmp_path / "weave.sqlite"
    monkeypatch.setattr(settings, "db_path", str(db_path))

    async def fake_synthesize(text: str, voice: str = "npc") -> bytes:
        del text, voice
        return b"RIFF"

    with (
        patch("machi.main.synthesize", new=AsyncMock(side_effect=fake_synthesize)),
        TestClient(app) as client,
    ):
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        assert created.status_code == 200
        sid = created.json()["session_id"]
        opened = client.post(f"/sessions/{sid}/turn", json={"advance": "warmup"})
        assert opened.status_code == 200
        missed = client.post(f"/sessions/{sid}/turn", json={"text": "zzz"})
        assert missed.status_code == 200
        assert missed.json()["warmup_passed"] is False

        lines = [
            ("ふたりです", True),
            ("醤油ラーメン", False),
            ("うん", False),
            ("お会計お願いします", False),
        ]
        last = None
        for text, skip in lines:
            last = client.post(
                f"/sessions/{sid}/turn",
                json={"text": text, "skip_warmup": skip},
            )
            assert last.status_code == 200, last.text
        assert last is not None
        assert last.json()["type"] == "debrief"
        assert last.json()["reviews_added"] >= 1

        due = client.get("/reviews/next?limit=10")
        cards = due.json()["cards"]
        match = next(card for card in cards if card["correction_ja"] == "二人です")
        assert match["weight"] == 1
        assert "ordering" in match["srs_tags"]
        assert match["reps"] == 0

        konbini = client.post(
            "/sessions",
            json={"scenario_id": "konbini_checkout_01", "level": 1},
        )
        assert konbini.status_code == 200
        body = konbini.json()
        assert body["reviews_line"].startswith("From your reviews:")
        assert "二人です" in body["reviews_line"]
        assert [phrase["ja"] for phrase in body["review_phrases"]] == ["二人です"]
        assert body["warmup_total"] == len(body["key_phrases"]) + 1

        taxi = client.post("/sessions", json={"scenario_id": "taxi_01", "level": 1})
        assert "二人です" in taxi.json()["reviews_line"]
        skipped = client.post(
            f"/sessions/{taxi.json()['session_id']}/turn",
            json={"text": "駅までお願いします", "skip_warmup": True},
        )
        assert skipped.status_code == 200
        assert skipped.json()["phase"] == "roleplay"
        still = client.get("/reviews/next?limit=10")
        untouched = next(
            card for card in still.json()["cards"] if card["card_id"] == match["card_id"]
        )
        assert untouched["reps"] == 0

        laundry = client.post(
            "/sessions",
            json={"scenario_id": "coin_laundry_01", "level": 1},
        )
        assert laundry.json()["reviews_line"] == ""
        assert laundry.json()["review_phrases"] == []

        kid = body["session_id"]
        warm = client.post(f"/sessions/{kid}/turn", json={"advance": "warmup"})
        assert warm.status_code == 200
        assert warm.json()["warmup_total"] == body["warmup_total"]
        assert warm.json()["phrase"]["ja"] == body["key_phrases"][0]["ja"]
        step = warm.json()
        for phrase in body["key_phrases"]:
            step = client.post(
                f"/sessions/{kid}/turn",
                json={"text": phrase["kana"]},
            ).json()
            assert step["warmup_passed"] is True
        assert step["next_phrase"]["ja"] == "二人です"
        assert step["warmup_complete"] is False
        answered = client.post(f"/sessions/{kid}/turn", json={"text": "二人です"})
        assert answered.status_code == 200
        done = answered.json()
        assert done["review_card_id"] == match["card_id"]
        assert done["review_rating"] == "good"
        assert done["review_reps"] == 1
        assert done["warmup_complete"] is True

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT reps, last_rating FROM cards WHERE id = ?",
                (match["card_id"],),
            ).fetchone()
        finally:
            conn.close()
        assert row == (1, "good")
