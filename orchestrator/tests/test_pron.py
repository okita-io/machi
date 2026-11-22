"""Expected readings, advisory F0, and the rule that pitch never changes stars."""

from __future__ import annotations

import asyncio
import base64
import importlib
import inspect
import io
import math
import struct
import sys
import wave
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from machi.clients import PRON_TIMEOUT_S, format_expected_reading, pron_reading, pron_score
from machi.config import settings
from machi.main import LLM, app
from machi.session import stars_earned

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

reading = importlib.import_module("pron.reading")
score = importlib.import_module("pron.score")
pron_app = importlib.import_module("pron.app")

settings.scenarios_path = str(ROOT / "scenarios")
settings.db_path = str(ROOT / "data" / "test_machi.sqlite")


def _label(phoneme: str, a1: str, a2: str, a3: str, f1: str, f2: str) -> str:
    return (
        f"xx^xx-{phoneme}+x=x"
        f"/A:{a1}+{a2}+{a3}"
        f"/B:xx-xx_xx/C:xx_xx+xx/D:xx+xx_xx/E:xx_xx!xx_xx-xx"
        f"/F:{f1}_{f2}#0_xx@1_1|1_{f1}"
        f"/G:xx_xx%xx_xx_xx/H:xx_xx"
        f"/I:xx-xx@xx+xx&xx-xx|xx+xx/J:xx_xx/K:1+1-{f1}"
    )


def _hashi_reader(text: str) -> dict:
    del text
    return {
        "kana": "ハシ",
        "labels": [
            _label("h", "0", "1", "2", "2", "1"),
            _label("a", "0", "1", "2", "2", "1"),
            _label("sh", "1", "2", "1", "2", "1"),
            _label("i", "1", "2", "1", "2", "1"),
        ],
    }


def _flat_pyin(samples, *, fmin, fmax, sr):
    del samples, fmin, fmax, sr
    frames = [200.0, 200.0, 200.0, 200.0]
    return frames, [True, True, True, True], [1.0, 1.0, 1.0, 1.0]


def _sine_wav(freq: float = 220.0, sr: int = 16000, seconds: float = 0.6) -> bytes:
    count = int(sr * seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        frames = b"".join(
            struct.pack(
                "<h",
                int(0.4 * 32767 * math.sin(2 * math.pi * freq * index / sr)),
            )
            for index in range(count)
        )
        handle.writeframes(frames)
    return buffer.getvalue()


def test_fake_reader_builds_accent_and_pitch():
    got = reading.expected_reading("箸", reader=_hashi_reader)
    assert got["kana"] == "ハシ"
    assert got["accent_type"] == 1
    assert got["pitch_pattern"] == ["H", "L"]
    assert [mora["mora"] for mora in got["moras"]] == ["ハ", "シ"]

    heiban = reading.build_reading(
        "橋",
        [
            _label("h", "-1", "1", "2", "2", "2"),
            _label("a", "-1", "1", "2", "2", "2"),
            _label("sh", "0", "2", "1", "2", "2"),
            _label("i", "0", "2", "1", "2", "2"),
        ],
        "ハシ",
    )
    assert heiban["accent_type"] == 0
    assert heiban["pitch_pattern"] == ["L", "H"]


def test_flat_f0_against_a_drop_is_advisory_high():
    pattern = reading.expected_reading("箸", reader=_hashi_reader)
    bands = score.advise(pattern, [200.0] * 8)
    assert [band["contour"] for band in bands] == ["flat", "dropping"]
    assert [band["advisory"] for band in bands] == ["ok", "high"]
    assert score.advisory_label("dropping", None) == "ok"


def test_reading_and_score_endpoints_use_injected_fakes(monkeypatch):
    monkeypatch.setattr(pron_app, "reader_override", _hashi_reader)
    monkeypatch.setattr(pron_app, "pyin_override", _flat_pyin)
    monkeypatch.setattr(pron_app, "dictionary_ready", lambda: False)
    audio_b64 = base64.b64encode(b"\x00\x10" * 160).decode("ascii")
    with TestClient(pron_app.app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "degraded"
        assert health.json()["engine"] == "pyopenjtalk"
        assert health.json()["f0"] == "librosa.pyin"
        assert health.json()["advisory_only"] is True

        monkeypatch.setattr(pron_app, "dictionary_ready", lambda: True)
        assert client.get("/health").json()["status"] == "ok"

        reading_body = client.post("/reading", json={"text": "箸"})
        assert reading_body.status_code == 200
        assert reading_body.json()["pitch_pattern"] == ["H", "L"]

        tracked = client.post("/f0", json={"audio_b64": audio_b64})
        assert tracked.status_code == 200
        assert tracked.json()["mean_f0"] == 200.0
        assert tracked.json()["voiced_ratio"] == 1.0
        assert tracked.json()["frames_hz"] == [200.0, 200.0, 200.0, 200.0]

        scored = client.post("/score", json={"audio_b64": audio_b64, "target_text": "箸"})
        assert scored.status_code == 200
        body = scored.json()
        assert body["is_advisory"] is True
        assert body["blocks_turn"] is False
        assert body["bands"][1]["advisory"] == "high"
        assert "passed" not in body

        assert client.post("/f0", json={"audio_b64": "!!!!"}).status_code == 400


def test_pron_client_degrades_when_unset_or_down(monkeypatch):
    monkeypatch.setattr(settings, "pron_url", "")

    class Boom:
        def __init__(self, *args, **kwargs):
            del args, kwargs
            raise AssertionError("pron client should not open without PRON_URL")

    monkeypatch.setattr("machi.clients.httpx.AsyncClient", Boom)
    assert asyncio.run(pron_reading("あ")) is None
    assert asyncio.run(pron_score(b"\x00\x00", "あ")) is None
    assert format_expected_reading(None) == "unavailable"

    monkeypatch.setattr(settings, "pron_url", "http://pron:8103")
    seen: dict[str, object] = {}

    class Down:
        def __init__(self, timeout=None, *args, **kwargs):
            del args, kwargs
            seen["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            del exc
            return False

        async def post(self, url, json=None):
            del url, json
            raise httpx.ConnectError("down")

    monkeypatch.setattr("machi.clients.httpx.AsyncClient", Down)
    assert asyncio.run(pron_reading("あ")) is None
    assert asyncio.run(pron_score(b"\x00\x00", "あ")) is None
    assert seen["timeout"] == PRON_TIMEOUT_S
    assert PRON_TIMEOUT_S == 1.5


def test_pitch_advisory_does_not_change_stars(monkeypatch):
    """A low advisory is stored and shown, and stars stay on the hint ladder."""
    assert set(inspect.signature(stars_earned).parameters) == {"level", "hint_max"}
    assert stars_earned(1, {}) == 3

    monkeypatch.setattr(settings, "pron_url", "http://pron:8103")
    calls: list[str] = []
    original = LLM.tutor_json

    async def spy_tutor(**kwargs):
        calls.append(kwargs["user"])
        return await original(**kwargs)

    async def fake_reading(text: str):
        del text
        return {
            "kana": "フタリデス",
            "accent_type": 1,
            "pitch_pattern": ["L", "H", "H", "L", "H"],
        }

    async def fake_score(audio: bytes, target_text: str):
        del audio, target_text
        return {
            "is_advisory": True,
            "blocks_turn": False,
            "bands": [
                {"mora": "フ", "contour": "flat", "advisory": "low", "expected_pitch": "L"},
            ],
        }

    async def fake_synthesize(text: str, voice: str = "npc") -> bytes:
        del text, voice
        return b"RIFF"

    monkeypatch.setattr(LLM, "tutor_json", spy_tutor)
    monkeypatch.setattr("machi.main.pron_reading", fake_reading)
    monkeypatch.setattr("machi.main.pron_score", fake_score)
    monkeypatch.setattr("machi.main.synthesize", fake_synthesize)

    audio_b64 = base64.b64encode(b"\x00\x10" * 32).decode("ascii")
    lines = [
        ("ふたりです", True),
        ("醤油ラーメン", False),
        ("うん", False),
        ("お会計お願いします", False),
    ]
    with TestClient(app) as client:
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        assert created.status_code == 200
        sid = created.json()["session_id"]
        first = None
        last = None
        for text, skip in lines:
            last = client.post(
                f"/sessions/{sid}/turn",
                json={"text": text, "skip_warmup": skip, "audio_b64": audio_b64},
            )
            assert last.status_code == 200, last.text
            if first is None:
                first = last
        assert first is not None and last is not None
        opened = first.json()
        assert opened["accepted"] is True
        assert opened["goal_hits"] == ["party_size"]
        assert opened["pitch_advisory"]["is_advisory"] is True
        assert opened["pitch_advisory"]["blocks_turn"] is False
        assert opened["pitch_advisory"]["bands"][0]["advisory"] == "low"
        assert opened["coach"]["pitch_advisory"]["bands"][0]["advisory"] == "low"

        closed = last.json()
        assert closed["type"] == "debrief"
        assert closed["stars"] == 3
        assert closed["pitch_advisory"]["bands"][0]["advisory"] == "low"
        assert closed["stars"] == stars_earned(1, {})

        progress = client.get(f"/sessions/{sid}/progress")
        assert progress.status_code == 200
        stored = progress.json()["attempts"]
        assert stored
        assert stored[-1]["pitch_advisory"]["is_advisory"] is True
        assert stored[-1]["pitch_advisory"]["bands"][0]["advisory"] == "low"

    assert calls
    assert "フタリデス" in calls[0]
    assert "unavailable" not in calls[0]


@pytest.mark.pron_model
def test_openjtalk_reading_and_pyin_on_sine():
    if not reading.dictionary_ready():
        pytest.skip("OpenJTalk dictionary is not installed")
    pytest.importorskip("librosa")
    got = reading.expected_reading("こんにちは")
    assert "コン" in got["kana"]
    assert got["pitch_pattern"]
    assert got["moras"]
    samples, rate = score.decode_audio(_sine_wav(220.0))
    tracked = score.track_f0(samples, rate)
    assert tracked["voiced_ratio"] > 0.2
    assert tracked["mean_f0"] == pytest.approx(220.0, rel=0.2)
    assert tracked["frames_hz"]
