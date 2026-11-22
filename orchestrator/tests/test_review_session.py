"""Spoken review session: three cards, fuzzy grades, and a shrinking due list."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from machi.config import settings
from machi.db import enroll_corrections, init_db, record_correction, record_session
from machi.fsrs import format_dt
from machi.llm import PROMPTS_DIR, render_prompt
from machi.main import REVIEWS, app
from machi.nlp import match_strength

PHRASES = [
    ("醤油ラーメンを一つ", "One shoyu ramen.", "shouyu raamen o hitotsu"),
    ("お水をください", "Water, please.", "omizu o kudasai"),
    ("カードで大丈夫ですか", "Is card OK?", "kaado de daijoubu desu ka"),
]


def _seed(path: Path) -> None:
    init_db(path)
    record_session(path, "visit", "restaurant_ramen_01", 1)
    for ja, en, romaji in PHRASES:
        record_correction(
            path,
            session_id="visit",
            scenario_id="restaurant_ramen_01",
            goal_id="order",
            learner_text="zzz",
            correction_ja=ja,
            correction_en=en,
            kana_ruby=f"<ruby>{ja}</ruby>",
            romaji=romaji,
            srs_tags=["restaurant", "ordering"],
            weight=1,
        )
    enroll_corrections(path, "visit", due_at=format_dt(datetime.now(UTC)))


def test_fragment_is_hard_and_a_miss_is_again():
    assert match_strength("ラーメン", ["醤油ラーメンを一つ"]) == "hard"
    assert match_strength("醤油ラーメンを一つお願いします", ["醤油ラーメンを一つ"]) == "good"
    assert match_strength("zzz", ["醤油ラーメンを一つ"]) == "again"


def test_situation_templates_render():
    found = list(PROMPTS_DIR.glob("review_situation_*.md"))
    assert len(found) >= 2
    values = {
        "phrase_ja": "二人です",
        "phrase_en": "Two people.",
        "phrase_romaji": "futari desu",
    }
    for path in found:
        text = render_prompt(path.name, values)
        assert "二人です" in text


def test_review_session_lifecycle(tmp_path, monkeypatch):
    db_path = tmp_path / "review.sqlite"
    monkeypatch.setattr(settings, "db_path", str(db_path))
    _seed(db_path)

    with TestClient(app) as client:
        before = client.get("/reviews/next?limit=10")
        assert before.status_code == 200
        due_ids = [card["card_id"] for card in before.json()["cards"]]
        assert len(due_ids) == 3

        created = client.post("/review/sessions")
        assert created.status_code == 200
        body = created.json()
        assert body["card_total"] == 3
        assert body["budget_s"] == 120
        assert body["complete"] is False
        assert body["situation_tag"] == "ordering"
        assert "Sora sets a small order" in body["situation"]
        assert body["card"]["ja"] == PHRASES[0][0]
        rid = body["review_id"]

        good = client.post(
            f"/review/sessions/{rid}/answer",
            json={"text": PHRASES[0][0]},
        )
        assert good.status_code == 200
        good_body = good.json()
        assert good_body["last"]["match"] == "good"
        assert good_body["last"]["rating"] == "good"
        assert good_body["last"]["reps"] == 1
        assert good_body["index"] == 1
        assert good_body["complete"] is False
        assert good_body["card"]["ja"] == PHRASES[1][0]

        progress = client.get(f"/review/sessions/{rid}")
        assert progress.status_code == 200
        assert progress.json()["index"] == 1
        assert progress.json()["card"]["ja"] == PHRASES[1][0]

        hard = client.post(
            f"/review/sessions/{rid}/answer",
            json={"text": "お水"},
        )
        assert hard.status_code == 200
        assert hard.json()["last"]["match"] == "hard"
        assert hard.json()["last"]["rating"] == "hard"
        assert hard.json()["card"]["ja"] == PHRASES[2][0]

        miss = client.post(
            f"/review/sessions/{rid}/answer",
            json={"text": "zzz"},
        )
        assert miss.status_code == 200
        done = miss.json()
        assert done["last"]["match"] == "again"
        assert done["last"]["rating"] == "again"
        assert done["complete"] is True
        assert done["card"] is None
        assert done["summary"]["cards_reviewed"] == 3
        assert len(done["summary"]["next_due"]) == 3
        assert all(row["due_at"] for row in done["summary"]["next_due"])

        again = client.post(f"/review/sessions/{rid}/answer", json={"text": "zzz"})
        assert again.status_code == 409

        missing = client.get("/review/sessions/missing")
        assert missing.status_code == 404

        after = client.get("/reviews/next?limit=10")
        remaining = {card["card_id"] for card in after.json()["cards"]}
        assert not remaining.intersection(due_ids)
        assert len(after.json()["cards"]) < len(due_ids)


def test_self_rating_overrides_a_miss(tmp_path, monkeypatch):
    db_path = tmp_path / "override.sqlite"
    monkeypatch.setattr(settings, "db_path", str(db_path))
    _seed(db_path)
    with TestClient(app) as client:
        created = client.post("/review/sessions")
        rid = created.json()["review_id"]
        answered = client.post(
            f"/review/sessions/{rid}/answer",
            json={"text": "zzz", "self_rating": "easy"},
        )
        assert answered.status_code == 200
        last = answered.json()["last"]
        assert last["match"] == "again"
        assert last["rating"] == "easy"
        assert last["reps"] == 1


def test_audio_answer_uses_asr(tmp_path, monkeypatch):
    db_path = tmp_path / "audio.sqlite"
    monkeypatch.setattr(settings, "db_path", str(db_path))
    _seed(db_path)

    async def fake_transcribe(
        audio_pcm: bytes | None = None,
        text_override: str | None = None,
    ) -> str:
        del audio_pcm, text_override
        return PHRASES[0][0]

    with (
        patch("machi.main.transcribe", new=AsyncMock(side_effect=fake_transcribe)),
        TestClient(app) as client,
    ):
        created = client.post("/review/sessions")
        rid = created.json()["review_id"]
        answered = client.post(
            f"/review/sessions/{rid}/answer",
            json={"audio_b64": "AAAA"},
        )
        assert answered.status_code == 200
        assert answered.json()["last"]["utterance"] == PHRASES[0][0]
        assert answered.json()["last"]["rating"] == "good"


def test_soft_budget_stops_after_the_current_card(tmp_path, monkeypatch):
    db_path = tmp_path / "budget.sqlite"
    monkeypatch.setattr(settings, "db_path", str(db_path))
    _seed(db_path)
    with TestClient(app) as client:
        created = client.post("/review/sessions")
        rid = created.json()["review_id"]
        REVIEWS[rid].started_at = datetime.now(UTC) - timedelta(seconds=121)
        answered = client.post(
            f"/review/sessions/{rid}/answer",
            json={"text": PHRASES[0][0]},
        )
        body = answered.json()
        assert body["complete"] is True
        assert body["summary"]["cards_reviewed"] == 1
        assert body["card_total"] == 3
