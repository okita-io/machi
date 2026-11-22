"""Baked NPC audio is preferred when the manifest has the spoken line."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from machi.config import settings
from machi.main import app
from machi.npc_audio import cached_npc_wav, fixed_npc_lines
from machi.scenario_loader import load_scenario

ROOT = Path(__file__).resolve().parents[2]
SCENARIO = load_scenario(ROOT / "scenarios" / "restaurant_ramen_01.yaml")
SEAT = SCENARIO.flow.nodes["seat"].npc or ""
CACHED = b"CACHED-WAV"
LIVE = b"LIVE-WAV"

settings.scenarios_path = str(ROOT / "scenarios")
settings.db_path = str(ROOT / "data" / "test_machi.sqlite")


def test_restaurant_fixed_lines_are_npc_fields_only():
    lines = fixed_npc_lines(SCENARIO)
    assert [node_id for node_id, _text in lines] == ["greet", "seat", "confirm_order"]
    assert "ありがとうございました！" not in {text for _node, text in lines}


def test_cache_requires_matching_text_and_a_real_file(tmp_path):
    audio_dir = tmp_path / "audio" / SCENARIO.id
    audio_dir.mkdir(parents=True)
    (audio_dir / "seat.wav").write_bytes(CACHED)
    (audio_dir / "manifest.json").write_text(
        json.dumps({"scenario_id": SCENARIO.id, "lines": {"seat": "seat.wav"}}),
        encoding="utf-8",
    )
    assert cached_npc_wav(tmp_path, SCENARIO, SEAT) == CACHED
    assert cached_npc_wav(tmp_path, SCENARIO, "別の文です") is None
    (audio_dir / "seat.wav").unlink()
    assert cached_npc_wav(tmp_path, SCENARIO, SEAT) is None


def test_manifest_hit_returns_cached_audio(tmp_path, monkeypatch, caplog):
    _write_manifest(tmp_path, {"seat": "seat.wav"})
    monkeypatch.setattr(settings, "assets_path", str(tmp_path))
    body, synthesize, turn = _seat_turn(caplog)
    assert body["tts_audio_b64"] == base64.b64encode(CACHED).decode("ascii")
    assert body["npc"]["ja"] == SEAT
    synthesize.assert_not_called()
    assert turn.headers["x-latency-tts-source"] == "cache"
    assert _latency_source(caplog, body["session_id"]) == "cache"


def test_missing_manifest_entry_uses_live_tts(tmp_path, monkeypatch, caplog):
    _write_manifest(tmp_path, {"greet": "greet.wav"})
    (tmp_path / "audio" / SCENARIO.id / "greet.wav").write_bytes(b"GREET")
    monkeypatch.setattr(settings, "assets_path", str(tmp_path))
    body, synthesize, turn = _seat_turn(caplog)
    assert body["tts_audio_b64"] == base64.b64encode(LIVE).decode("ascii")
    synthesize.assert_called()
    assert turn.headers["x-latency-tts-source"] == "live"
    assert _latency_source(caplog, body["session_id"]) == "live"


def _write_manifest(root: Path, lines: dict[str, str]) -> None:
    audio_dir = root / "audio" / SCENARIO.id
    audio_dir.mkdir(parents=True)
    if "seat" in lines:
        (audio_dir / "seat.wav").write_bytes(CACHED)
    (audio_dir / "manifest.json").write_text(
        json.dumps(
            {"scenario_id": SCENARIO.id, "voice": "qwen3_tts", "lines": lines},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _seat_turn(caplog):
    async def fake_synthesize(text: str, voice: str = "npc") -> bytes:
        del text, voice
        return LIVE

    synthesize = AsyncMock(side_effect=fake_synthesize)
    with (
        patch("machi.main.synthesize", new=synthesize),
        TestClient(app) as client,
        caplog.at_level(logging.INFO, logger="machi.latency"),
    ):
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
    return turn.json(), synthesize, turn


def _latency_source(caplog, session_id: str) -> str:
    for record in caplog.records:
        if "turn_latency" not in record.message:
            continue
        payload = json.loads(record.message)
        if payload.get("session_id") == session_id:
            return payload["sources"]["tts"]
    raise AssertionError("turn_latency log line not found")
