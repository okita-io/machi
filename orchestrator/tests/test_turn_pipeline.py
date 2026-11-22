"""Audio-only turns: ASR_URL → LLM (NPC + tutor) → TTS_URL."""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient

from machi.clients import SpeechError
from machi.config import settings
from machi.main import LLM, app
from machi.nlp import to_romaji

settings.scenarios_path = str(Path(__file__).resolve().parents[2] / "scenarios")
settings.db_path = str(Path(__file__).resolve().parents[2] / "data" / "test_machi.sqlite")

SEAT_JA = "こちらのお席へどうぞ。ご注文がお決まりでしたらお呼びください。"
PCM = b"\x01\x00\x02\x00pcm-bytes"
WAV = b"RIFFwav"


class _JsonResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _recording_client(posts: list[tuple[str, dict]], wav_b64: str):
    class RecordingClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        async def __aenter__(self) -> RecordingClient:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            del exc
            return False

        async def post(self, url: str, json: dict | None = None) -> _JsonResponse:
            body = json or {}
            posts.append((url, body))
            if url.endswith("/v1/transcribe"):
                return _JsonResponse({"text": "ふたりです", "confidence": 0.9})
            if url.endswith("/v1/synthesize"):
                return _JsonResponse({"audio_b64": wav_b64, "text": body.get("text", "")})
            raise AssertionError(url)

    return RecordingClient


def _patch_speech(monkeypatch, posts: list[tuple[str, dict]]) -> None:
    wav_b64 = base64.b64encode(WAV).decode("ascii")
    monkeypatch.setattr("machi.clients.httpx.AsyncClient", _recording_client(posts, wav_b64))


def _spy_llm(monkeypatch) -> tuple[list[dict], list[dict]]:
    npc_calls: list[dict] = []
    tutor_calls: list[dict] = []
    orig_npc = LLM.npc_reply
    orig_tutor = LLM.tutor_json

    async def spy_npc(**kwargs):
        npc_calls.append(kwargs)
        return await orig_npc(**kwargs)

    async def spy_tutor(**kwargs):
        tutor_calls.append(kwargs)
        return await orig_tutor(**kwargs)

    monkeypatch.setattr(LLM, "npc_reply", spy_npc)
    monkeypatch.setattr(LLM, "tutor_json", spy_tutor)
    return npc_calls, tutor_calls


def test_audio_b64_only_turn_runs_asr_llm_tts(monkeypatch):
    """Typed text is not required. audio_b64 alone is transcribed and spoken back."""
    posts: list[tuple[str, dict]] = []
    npc_calls, tutor_calls = _spy_llm(monkeypatch)
    _patch_speech(monkeypatch, posts)
    audio_b64 = base64.b64encode(PCM).decode("ascii")
    asr_url = settings.asr_url.rstrip("/")
    tts_url = settings.tts_url.rstrip("/")

    with TestClient(app) as client:
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        assert created.status_code == 200
        sid = created.json()["session_id"]
        turn = client.post(f"/sessions/{sid}/turn", json={"audio_b64": audio_b64})

    assert turn.status_code == 200
    body = turn.json()
    assert body["learner_text"] == "ふたりです"
    assert body["goal_hits"] == ["party_size"]
    assert body["node_id"] == "seat"
    assert body["npc"]["ja"] == SEAT_JA
    assert body["npc"]["romaji"] == to_romaji(SEAT_JA)
    assert body["npc"]["romaji"]
    assert body["tts_audio_b64"] == base64.b64encode(WAV).decode("ascii")
    assert body["coach"]["coach_note_en"] == "Nice!"

    assert float(turn.headers["x-latency-asr"]) >= 0
    assert float(turn.headers["x-latency-llm"]) >= 0
    assert float(turn.headers["x-latency-tts"]) >= 0

    assert posts[0][0] == f"{asr_url}/v1/transcribe"
    assert base64.b64decode(posts[0][1]["audio_b64"]) == PCM
    assert "text" not in posts[0][1]
    assert posts[1][0] == f"{tts_url}/v1/synthesize"
    assert posts[1][1]["text"] == SEAT_JA
    assert posts[1][1]["voice"] == "qwen3_tts"

    assert npc_calls and "ふたりです" in npc_calls[0]["user"]
    assert npc_calls[0]["fallback_line"] == SEAT_JA
    assert tutor_calls and "ふたりです" in tutor_calls[0]["user"]


def test_blank_text_still_transcribes_audio(monkeypatch):
    posts: list[tuple[str, dict]] = []
    _patch_speech(monkeypatch, posts)
    audio_b64 = base64.b64encode(PCM).decode("ascii")

    with TestClient(app) as client:
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        sid = created.json()["session_id"]
        turn = client.post(
            f"/sessions/{sid}/turn",
            json={"text": "   ", "audio_b64": audio_b64},
        )

    assert turn.status_code == 200
    assert turn.json()["learner_text"] == "ふたりです"
    assert base64.b64decode(posts[0][1]["audio_b64"]) == PCM
    assert "x-latency-asr" in turn.headers


def test_invalid_audio_b64_is_400():
    with TestClient(app) as client:
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        sid = created.json()["session_id"]
        turn = client.post(f"/sessions/{sid}/turn", json={"audio_b64": "!!!!"})

    assert turn.status_code == 400
    assert turn.json()["detail"] == "invalid audio_b64"


def test_asr_outage_is_502(monkeypatch):
    async def down(*args, **kwargs):
        del args, kwargs
        raise SpeechError("asr")

    monkeypatch.setattr("machi.main.transcribe", down)
    audio_b64 = base64.b64encode(PCM).decode("ascii")
    with TestClient(app) as client:
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        sid = created.json()["session_id"]
        turn = client.post(f"/sessions/{sid}/turn", json={"audio_b64": audio_b64})

    assert turn.status_code == 502
    assert turn.json()["detail"] == "asr_unavailable"


def test_ws_turn_without_text_runs_same_pipeline(monkeypatch):
    posts: list[tuple[str, dict]] = []
    npc_calls, tutor_calls = _spy_llm(monkeypatch)
    _patch_speech(monkeypatch, posts)
    audio_b64 = base64.b64encode(PCM).decode("ascii")

    with TestClient(app) as client:
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        sid = created.json()["session_id"]
        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "turn", "audio_b64": audio_b64})
            result = ws.receive_json()

    assert result["type"] == "turn_result"
    assert result["learner_text"] == "ふたりです"
    assert result["goal_hits"] == ["party_size"]
    assert result["npc"]["ja"] == SEAT_JA
    assert result["npc"]["romaji"] == to_romaji(SEAT_JA)
    assert result["tts_audio_b64"] == base64.b64encode(WAV).decode("ascii")
    assert base64.b64decode(posts[0][1]["audio_b64"]) == PCM
    assert posts[0][0].endswith("/v1/transcribe")
    assert posts[1][0].endswith("/v1/synthesize")
    assert npc_calls and tutor_calls


def test_ws_invalid_audio_b64_reports_detail():
    with TestClient(app) as client:
        created = client.post(
            "/sessions",
            json={"scenario_id": "restaurant_ramen_01", "level": 1},
        )
        sid = created.json()["session_id"]
        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "turn", "audio_b64": "not-base64"})
            result = ws.receive_json()

    assert result == {"type": "error", "detail": "invalid audio_b64"}
