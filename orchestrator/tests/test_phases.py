"""Briefing gate, warm-up, and the debrief screen payload."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from machi.config import settings
from machi.main import LLM, app
from machi.session import stars_earned

settings.scenarios_path = str(Path(__file__).resolve().parents[2] / "scenarios")
settings.db_path = str(Path(__file__).resolve().parents[2] / "data" / "test_machi.sqlite")

PAIRS = [
    ("Say it as 二人です.", "二人です"),
    ("Add を一つ.", "醤油ラーメンを一つお願いします"),
    ("A short thanks is enough.", "ありがとうございます"),
    ("Offer the card.", "カードで大丈夫ですか"),
]


def test_stars_follow_climbs_above_the_level_default():
    assert stars_earned(1, {}) == 3
    assert stars_earned(1, {"party_size": 2}) == 2
    assert stars_earned(1, {"party_size": 4}) == 1
    assert stars_earned(2, {"order": 2}) == 3
    assert stars_earned(2, {"order": 3}) == 2


def test_turn_does_not_score_until_warmup_completes():
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
        body = created.json()
        assert body["phase"] == "briefing"
        assert len(body["key_phrases"]) == 5
        sid = body["session_id"]

        blocked = client.post(f"/sessions/{sid}/turn", json={"text": "ふたりです"})
        assert blocked.status_code == 409
        assert blocked.json()["detail"] == "warmup_incomplete"

        opened = client.post(f"/sessions/{sid}/turn", json={"advance": "warmup"})
        assert opened.status_code == 200
        assert opened.json()["phase"] == "warmup"
        assert opened.json()["goal_hits"] == []

        phrases = body["key_phrases"]
        review_phrases = body.get("review_phrases") or []
        queue = phrases + review_phrases
        assert opened.json()["warmup_total"] == len(queue)
        last = None
        for index, phrase in enumerate(queue):
            if index < len(phrases):
                text = phrase["kana"] if index % 2 == 0 else "zzz"
            else:
                text = phrase["ja"]
            last = client.post(f"/sessions/{sid}/turn", json={"text": text})
            assert last.status_code == 200
            step = last.json()
            assert step["goal_hits"] == []
            assert step["completed_goals"] == []
            assert step["node_id"] == "greet"
            if index < len(phrases) and index % 2 == 0:
                assert step["warmup_passed"] is True
            elif index < len(phrases):
                assert step["warmup_passed"] is False

        assert last is not None
        done = last.json()
        assert done["phase"] == "roleplay"
        assert done["warmup_complete"] is True

        played = client.post(f"/sessions/{sid}/turn", json={"text": "ふたりです"})
        assert played.status_code == 200
        assert played.json()["goal_hits"] == ["party_size"]
        assert played.json()["node_id"] == "seat"


def test_scripted_playthrough_reaches_debrief_with_tutor_corrections():
    async def fake_synthesize(text: str, voice: str = "npc") -> bytes:
        del text, voice
        return b"RIFF"

    notes: list[tuple[str, str]] = []
    original = LLM.tutor_json

    async def noting_tutor(**kwargs):
        payload = dict(await original(**kwargs))
        en, ja = PAIRS[min(len(notes), len(PAIRS) - 1)]
        notes.append((en, ja))
        payload["correction_en"] = en
        payload["correction_ja"] = ja
        return payload

    with (
        patch("machi.main.synthesize", new=AsyncMock(side_effect=fake_synthesize)),
        patch.object(LLM, "tutor_json", noting_tutor),
        TestClient(app) as client,
    ):
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        sid = created.json()["session_id"]
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
    body = last.json()
    assert body["type"] == "debrief"
    assert body["phase"] == "debrief"
    assert body["stars"] == 3
    assert body["complete"] is True
    assert body["goals_completed"] == ["party_size", "order", "pay"]
    assert body["npc"]["ja"] == "ありがとうございました！"
    assert [card["en"] for card in body["corrections"]] == [PAIRS[2][0], PAIRS[3][0]]
    assert body["corrections"][1]["ja"] == "カードで大丈夫ですか"
    assert body["corrections"][1]["romaji"]
    ruby = body["corrections"][1]["ruby_html"]
    assert "<ruby>" in ruby and "<rt>" in ruby
    assert "だいじょうぶ" in ruby


FIRMNESS_COACH = "Say かため (firm), ふつう (regular), or やわらかめ (soft)."


def _play(client, level: int, lines: list[str]) -> list[dict]:
    created = client.post(
        "/sessions",
        json={"scenario_id": "restaurant_ramen_01", "level": level},
    )
    assert created.status_code == 200
    sid = created.json()["session_id"]
    bodies: list[dict] = []
    for index, text in enumerate(lines):
        response = client.post(
            f"/sessions/{sid}/turn",
            json={"text": text, "skip_warmup": index == 0},
        )
        assert response.status_code == 200, response.text
        bodies.append(response.json())
    return bodies


def test_level2_playthrough_skips_firmness():
    async def fake_synthesize(text: str, voice: str = "npc") -> bytes:
        del text, voice
        return b"RIFF"

    with (
        patch("machi.main.synthesize", new=AsyncMock(side_effect=fake_synthesize)),
        TestClient(app) as client,
    ):
        bodies = _play(
            client,
            2,
            ["ふたりです", "醤油ラーメン", "うん", "お会計お願いします"],
        )

    assert [body["node_id"] for body in bodies] == ["seat", "confirm_order", "pay", "debrief"]
    assert all("硬め" not in body["npc"]["ja"] for body in bodies)
    assert all("noodle_firmness" not in body["goal_hits"] for body in bodies)
    assert bodies[-1]["type"] == "debrief"
    assert bodies[-1]["goals_completed"] == ["party_size", "order", "pay"]


def test_level4_firmness_advances_and_wrong_retries_with_coach_note():
    async def fake_synthesize(text: str, voice: str = "npc") -> bytes:
        del text, voice
        return b"RIFF"

    with (
        patch("machi.main.synthesize", new=AsyncMock(side_effect=fake_synthesize)),
        TestClient(app) as client,
    ):
        bodies = _play(
            client,
            4,
            [
                "ふたりです",
                "醤油ラーメン",
                "わからない",
                "yawarakame",
                "うん",
                "お会計お願いします",
            ],
        )

    assert bodies[1]["node_id"] == "noodle_firmness"
    assert "硬め" in bodies[1]["npc"]["ja"]
    assert "普通" in bodies[1]["npc"]["ja"]
    assert "やわらかめ" in bodies[1]["npc"]["ja"]
    missed = bodies[2]
    assert missed["accepted"] is False
    assert missed["node_id"] == "noodle_firmness"
    assert missed["goal_hits"] == []
    assert missed["coach"]["coach_note_en"] == FIRMNESS_COACH
    assert bodies[3]["accepted"] is True
    assert bodies[3]["goal_hits"] == ["noodle_firmness"]
    assert bodies[3]["node_id"] == "confirm_order"
    assert bodies[-1]["type"] == "debrief"
    assert bodies[-1]["goals_completed"] == ["party_size", "order", "pay"]
