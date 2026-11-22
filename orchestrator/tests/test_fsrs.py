"""FSRS-4.5 scheduling and weighted correction cards."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from machi.config import settings
from machi.db import (
    enroll_corrections,
    init_db,
    next_due_cards,
    record_correction,
    record_session,
)
from machi.fsrs import DEFAULT_WEIGHTS, FsrsState, schedule
from machi.main import LLM, app
from machi.session import (
    best_corrections,
    climbs_above_default,
    coaching_goal_id,
    correction_weight,
    default_tutor_payload,
)

settings.scenarios_path = str(Path(__file__).resolve().parents[2] / "scenarios")

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_default_weights_are_the_fsrs45_set():
    assert len(DEFAULT_WEIGHTS) == 19


def test_new_card_good_moves_to_review():
    card = schedule(FsrsState(), "good", _NOW)
    assert card.state == "review"
    assert card.reps == 1
    assert card.lapses == 0
    assert card.stability is not None and card.stability > 0
    assert card.interval_days >= 1
    assert card.due_at is not None and card.due_at > _NOW


def test_good_ratings_produce_monotonic_intervals():
    card = FsrsState()
    now = _NOW
    intervals: list[int] = []
    for _ in range(4):
        card = schedule(card, "good", now)
        assert card.state == "review"
        assert card.due_at is not None
        intervals.append(card.interval_days)
        now = card.due_at
    pairs = list(zip(intervals, intervals[1:]))
    assert pairs
    assert all(later > earlier for earlier, later in pairs), intervals


def test_new_card_again_stays_learning():
    card = schedule(FsrsState(), "again", _NOW)
    assert card.state == "learning"
    assert card.lapses == 1
    assert card.interval_days == 0
    assert card.due_at == _NOW + timedelta(minutes=1)


def test_repeat_miss_outranks_a_single_miss():
    assert correction_weight(2, 0) > correction_weight(1, 0)
    assert correction_weight(1, 2) == 3
    assert climbs_above_default(1, 3) == 2
    assert climbs_above_default(2, 2) == 0
    assert coaching_goal_id(["order", "ask_water"], []) == "order"
    chosen = best_corrections(
        [
            {"en": "same", "ja": "二", "weight": correction_weight(2, 0)},
            {"en": "solo-a", "ja": "一", "weight": correction_weight(1, 0)},
            {"en": "solo-b", "ja": "三", "weight": correction_weight(1, 0)},
        ]
    )
    assert [item["en"] for item in chosen] == ["same", "solo-b"]


def test_due_query_orders_soonest_first_and_skips_future_cards(tmp_path):
    path = tmp_path / "srs.sqlite"
    init_db(path)
    record_session(path, "s1", "restaurant_ramen_01", 1)
    phrases = [("一", "one"), ("二", "two"), ("三", "three")]
    correction_ids = [
        record_correction(
            path,
            session_id="s1",
            scenario_id="restaurant_ramen_01",
            goal_id="order",
            learner_text="zzz",
            correction_ja=ja,
            correction_en=en,
            kana_ruby=f"<ruby>{ja}</ruby>",
            romaji=en,
            srs_tags=["restaurant", "counters", "polite_requests"],
            weight=1,
        )
        for ja, en in phrases
    ]
    added = enroll_corrections(path, "s1", due_at="2026-01-02T00:00:00+00:00")
    assert added == 3
    again = enroll_corrections(path, "s1", due_at="2026-01-02T00:00:00+00:00")
    assert again == 0

    dues = {
        correction_ids[0]: "2026-01-01T00:00:00+00:00",
        correction_ids[1]: "2026-01-03T00:00:00+00:00",
        correction_ids[2]: "2025-12-31T00:00:00+00:00",
    }
    conn = sqlite3.connect(path)
    try:
        for correction_id, due_at in dues.items():
            conn.execute(
                "UPDATE cards SET due_at = ? WHERE correction_id = ?",
                (due_at, correction_id),
            )
        conn.commit()
    finally:
        conn.close()

    now = "2026-01-02T00:00:00+00:00"
    cards = next_due_cards(path, now=now, limit=10)
    assert [card["correction_ja"] for card in cards] == ["三", "一"]
    assert cards[0]["srs_tags"] == ["restaurant", "counters", "polite_requests"]
    assert cards[0]["state"] == "new"
    limited = next_due_cards(path, now=now, limit=1)
    assert [card["correction_ja"] for card in limited] == ["三"]


def test_two_misses_outrank_single_miss_and_store_ruby(tmp_path, monkeypatch):
    db_path = tmp_path / "reviews.sqlite"
    monkeypatch.setattr(settings, "db_path", str(db_path))

    script = [
        ("Offer the card.", "カードで大丈夫ですか"),
        ("Offer the card.", "カードで大丈夫ですか"),
        (None, None),
        ("Say two.", "二人です"),
        (None, None),
        (None, None),
        ("A short thanks is enough.", "ありがとうございます"),
        (None, None),
    ]
    cursor = {"i": 0}

    async def scripted_tutor(**kwargs):
        del kwargs
        en, ja = script[cursor["i"]]
        cursor["i"] += 1
        payload = default_tutor_payload([], coach_note="note", hint_rung=1)
        if en:
            payload["correction_en"] = en
        if ja:
            payload["correction_ja"] = ja
        return payload

    async def fake_synthesize(text: str, voice: str = "npc") -> bytes:
        del text, voice
        return b"RIFF"

    lines = [
        ("zzz", True),
        ("zzz", False),
        ("ふたりです", False),
        ("zzz", False),
        ("醤油ラーメン", False),
        ("うん", False),
        ("zzz", False),
        ("お会計お願いします", False),
    ]
    with (
        patch("machi.main.synthesize", new=AsyncMock(side_effect=fake_synthesize)),
        patch.object(LLM, "tutor_json", scripted_tutor),
        TestClient(app) as client,
    ):
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        assert created.status_code == 200
        sid = created.json()["session_id"]
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
        shown = body["corrections"]
        assert [card["en"] for card in shown] == [
            "Offer the card.",
            "A short thanks is enough.",
        ]
        assert shown[0]["weight"] == 2
        assert shown[1]["weight"] == 1
        assert shown[0]["ja"] == "カードで大丈夫ですか"
        assert shown[0]["romaji"]
        assert "<ruby>" in shown[0]["ruby_html"]
        assert "だいじょうぶ" in shown[0]["ruby_html"]
        assert body["reviews_added"] >= 1

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM corrections WHERE correction_ja = ?",
                ("カードで大丈夫ですか",),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["weight"] == 2
        assert row["romaji"]
        assert "だいじょうぶ" in row["kana_ruby"]
        assert "restaurant" in row["srs_tags"]
        assert "polite_requests" in row["srs_tags"]

        due = client.get("/reviews/next?limit=10")
        assert due.status_code == 200
        cards = due.json()["cards"]
        match = next(card for card in cards if card["correction_ja"] == "カードで大丈夫ですか")
        assert match["state"] == "new"
        assert match["srs_tags"] == ["restaurant", "counters", "polite_requests"]
        assert "二人です" in [card["correction_ja"] for card in cards]

        reviewed = client.post("/reviews", json={"card_id": match["card_id"], "rating": "good"})
        assert reviewed.status_code == 200
        assert reviewed.json()["state"] == "review"
        assert reviewed.json()["reps"] == 1
        assert reviewed.json()["interval_days"] >= 1
        again = client.get("/reviews/next?limit=10")
        later_ids = [card["card_id"] for card in again.json()["cards"]]
        assert match["card_id"] not in later_ids

        repeat = client.post(f"/sessions/{sid}/reviews")
        assert repeat.status_code == 200
        assert repeat.json()["added"] == 0
        missing = client.post("/reviews", json={"card_id": 999999, "rating": "good"})
        assert missing.status_code == 404


def test_warmup_miss_persists_the_key_phrase(tmp_path, monkeypatch):
    db_path = tmp_path / "warmup.sqlite"
    monkeypatch.setattr(settings, "db_path", str(db_path))
    with TestClient(app) as client:
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        sid = created.json()["session_id"]
        opened = client.post(f"/sessions/{sid}/turn", json={"advance": "warmup"})
        assert opened.status_code == 200
        missed = client.post(f"/sessions/{sid}/turn", json={"text": "zzz"})
        assert missed.status_code == 200
        assert missed.json()["warmup_passed"] is False
        assert missed.json()["coach"]["correction_ja"] == "二人です"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM corrections WHERE correction_ja = ?",
            ("二人です",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["learner_text"] == "zzz"
    assert row["weight"] == 1
    assert "futari" in row["romaji"]
    assert "ふたり" in row["kana_ruby"]
    assert "<ruby>" in row["kana_ruby"]
    assert row["srs_tags"] == "restaurant,counters,polite_requests"
