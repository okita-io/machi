"""Machi orchestrator FastAPI app."""

from __future__ import annotations

import base64
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnected

from machi.clients import synthesize, transcribe
from machi.config import settings
from machi.db import init_db, record_attempt, record_session
from machi.latency import STAGE_ASR, STAGE_LLM, STAGE_TTS, TurnLatency
from machi.llm import LlmClient
from machi.nlp import build_ruby_html, to_romaji
from machi.scenario_loader import load_all_scenarios
from machi.session import (
    SessionState,
    advance_node,
    default_tutor_payload,
    evaluate_turn,
    new_session,
)
from machi.ws_audio import PCM_FRAME_BYTES, SessionAudioBuffer

logger = logging.getLogger(__name__)

SCENARIOS: dict = {}
SESSIONS: dict[str, SessionState] = {}
LLM = LlmClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    scenarios_dir = Path(settings.scenarios_path)
    global SCENARIOS
    SCENARIOS = load_all_scenarios(scenarios_dir)
    init_db(Path(settings.db_path))
    logger.info("Loaded %s scenarios", len(SCENARIOS))
    yield


app = FastAPI(title="Machi Orchestrator", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateSessionRequest(BaseModel):
    scenario_id: str
    level: int = Field(default=1, ge=1, le=4)


class TurnRequest(BaseModel):
    text: str | None = None
    audio_b64: str | None = None


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "scenarios": len(SCENARIOS),
        "llm_mock": LLM.using_mock,
    }


@app.get("/scenarios")
async def list_scenarios() -> list[dict[str, str]]:
    return [
        {"id": s.id, "title_en": s.title.en, "title_ja": s.title.ja}
        for s in SCENARIOS.values()
    ]


@app.get("/scenarios/{scenario_id}")
async def get_scenario(scenario_id: str) -> dict[str, Any]:
    spec = SCENARIOS.get(scenario_id)
    if not spec:
        raise HTTPException(status_code=404, detail="scenario not found")
    return spec.model_dump(mode="json")


@app.post("/sessions")
async def create_session(body: CreateSessionRequest) -> dict[str, Any]:
    spec = SCENARIOS.get(body.scenario_id)
    if not spec:
        raise HTTPException(status_code=404, detail="scenario not found")
    state = new_session(spec, level=body.level)
    SESSIONS[state.id] = state
    record_session(Path(settings.db_path), state.id, spec.id, body.level)
    node = spec.flow.nodes[state.node_id]
    npc_ja, npc_kana = node.npc or "", node.npc_kana
    return {
        "session_id": state.id,
        "scenario_id": spec.id,
        "level": state.level,
        "node_id": state.node_id,
        "scene": {
            "background": f"{settings.assets_base_url}/{spec.scene.background}",
            "guide_sprite": f"{settings.assets_base_url}/sprites/sora_neutral.svg",
        },
        "opening_npc": enrich_line(npc_ja, npc_kana),
        "briefing_en": spec.goals[0].prompt_en if spec.goals else "",
        "key_phrases": [kp.model_dump() for kp in spec.key_phrases],
        "hint_rung": state.hint_rung,
    }


@app.post("/sessions/{session_id}/turn")
async def session_turn(
    session_id: str,
    body: TurnRequest,
    response: Response,
) -> dict[str, Any]:
    state = SESSIONS.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="session not found")

    timer = TurnLatency()
    utterance = body.text or ""
    if body.audio_b64 and not utterance:
        audio = base64.b64decode(body.audio_b64)
        with timer.measure(STAGE_ASR):
            utterance = await transcribe(audio_pcm=audio)
    elif not utterance:
        with timer.measure(STAGE_ASR):
            utterance = await transcribe(text_override="")
    else:
        # Typed text does not call ASR. Omit a zero duration.
        timer.skip(STAGE_ASR)

    prev_node_id = state.node_id
    goal_hits, success = evaluate_turn(state, utterance)

    if success:
        advance_node(state, goal_hits, progressed=True)
        node = state.scenario.flow.nodes[state.node_id]
        npc_ja, npc_kana = node.npc or "", node.npc_kana
        if prev_node_id != state.node_id and state.node_id == "pay" and "pay" in goal_hits:
            pay = state.scenario.flow.nodes["pay"]
            npc_ja = pay.npc_on_success or npc_ja
            npc_kana = pay.npc_on_success_kana
    else:
        node = state.scenario.flow.nodes[state.node_id]
        if node.on_other:
            npc_ja, npc_kana = node.on_other.clarify, None
        else:
            npc_ja, npc_kana = node.npc or "", node.npc_kana

    npc_system = f"You are {state.scenario.npc.role}. Speak only Japanese, one short line."
    npc_user = f"Learner said: {utterance}. Respond in character."
    coach = default_tutor_payload(
        goal_hits,
        coach_note="Good try! Match a key phrase from the briefing." if not success else "Nice!",
        hint_rung=state.hint_rung,
    )
    tutor_system = "You are Sora the tutor. Return JSON with goal_hits, coach_note_en, hint_rung."
    tutor_user = f"Utterance: {utterance}; hits: {goal_hits}"
    with timer.measure(STAGE_LLM):
        npc_ja = await LLM.npc_reply(system=npc_system, user=npc_user, fallback_line=npc_ja)
        coach = await LLM.tutor_json(system=tutor_system, user=tutor_user, fallback=coach)

    with timer.measure(STAGE_TTS):
        audio = await synthesize(npc_ja, voice=state.scenario.npc.voice.engine)
    for key, value in timer.header_map().items():
        response.headers[key] = value
    timer.emit(session_id=session_id)
    record_attempt(
        Path(settings.db_path),
        session_id,
        state.node_id,
        utterance,
        goal_hits,
    )

    return {
        "session_id": session_id,
        "node_id": state.node_id,
        "learner_text": utterance,
        "goal_hits": goal_hits,
        "npc": enrich_line(npc_ja, npc_kana),
        "coach": coach,
        "tts_audio_b64": base64.b64encode(audio).decode("ascii"),
        "completed_goals": sorted(state.completed_goals),
    }


def enrich_line(text_ja: str, kana: str | None) -> dict[str, str]:
    return {
        "ja": text_ja,
        "romaji": to_romaji(text_ja),
        "ruby_html": build_ruby_html(text_ja, kana),
    }


def _ws_bool(value: object) -> bool:
    return value is True


async def _ws_pcm_frame(websocket: WebSocket, buf: SessionAudioBuffer, payload: bytes) -> None:
    if len(payload) != PCM_FRAME_BYTES:
        await websocket.send_json(
            {
                "type": "audio_ack",
                "frames": buf.frames,
                "event": "frame",
                "accepted": False,
                "bytes": len(payload),
            }
        )
        return
    accepted = buf.append(payload)
    await websocket.send_json(
        {
            "type": "audio_ack",
            "frames": buf.frames,
            "event": "frame",
            "accepted": accepted,
            "bytes": PCM_FRAME_BYTES,
        }
    )


async def _ws_turn(
    websocket: WebSocket,
    session_id: str,
    buf: SessionAudioBuffer,
    data: dict[str, Any],
) -> None:
    text = data.get("text") if isinstance(data.get("text"), str) else None
    if text == "":
        text = None
    audio_b64 = data.get("audio_b64") if isinstance(data.get("audio_b64"), str) else None
    # Typed text keeps the existing turn path. Otherwise use this socket's PCM.
    if text:
        buf.clear()
        audio_b64 = None
    elif audio_b64:
        buf.clear()
    else:
        audio_b64 = buf.take_b64()
    try:
        result = await session_turn(
            session_id,
            TurnRequest(text=text, audio_b64=audio_b64),
            Response(),
        )
    except Exception:
        logger.exception("websocket turn failed session=%s", session_id)
        await websocket.send_json({"type": "error", "detail": "turn_failed"})
        return
    await websocket.send_json({"type": "turn_result", **result})


async def _ws_control(
    websocket: WebSocket,
    session_id: str,
    buf: SessionAudioBuffer,
    raw: str,
) -> None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        await websocket.send_json({"type": "error", "detail": "invalid_json"})
        return
    if not isinstance(data, dict):
        await websocket.send_json({"type": "error", "detail": "expected_object"})
        return
    kind = data.get("type")
    if kind == "audio_start":
        buf.start(hands_free=_ws_bool(data.get("hands_free")))
        await websocket.send_json(
            {
                "type": "audio_ack",
                "frames": buf.frames,
                "event": "audio_start",
                "hands_free": buf.hands_free,
            }
        )
        return
    if kind == "audio_stop":
        frames = buf.stop()
        await websocket.send_json(
            {
                "type": "audio_ack",
                "frames": frames,
                "event": "audio_stop",
                "bytes": len(buf.pcm),
            }
        )
        return
    if kind == "turn":
        await _ws_turn(websocket, session_id, buf, data)
        return
    await websocket.send_json({"type": "error", "detail": "unknown_type"})


@app.websocket("/ws/{session_id}")
async def ws_session(websocket: WebSocket, session_id: str) -> None:
    """JSON control events plus 640-byte PCM frames. Replies are JSON only."""
    await websocket.accept()
    if session_id not in SESSIONS:
        await websocket.close(code=4404)
        return
    buf = SessionAudioBuffer()
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return
            payload = message.get("bytes")
            raw = message.get("text")
            if payload is not None:
                await _ws_pcm_frame(websocket, buf, payload)
            elif raw is not None:
                await _ws_control(websocket, session_id, buf, raw)
    except (WebSocketDisconnect, WebSocketDisconnected):
        return