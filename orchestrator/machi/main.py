"""Machi orchestrator FastAPI app."""

from __future__ import annotations

import base64
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from machi.clients import synthesize, transcribe
from machi.config import settings
from machi.db import init_db, record_attempt, record_session
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
async def session_turn(session_id: str, body: TurnRequest) -> dict[str, Any]:
    state = SESSIONS.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="session not found")

    utterance = body.text or ""
    if body.audio_b64 and not utterance:
        audio = base64.b64decode(body.audio_b64)
        utterance = await transcribe(audio_pcm=audio)
    elif not utterance:
        utterance = await transcribe(text_override="")

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
    npc_ja = await LLM.npc_reply(system=npc_system, user=npc_user, fallback_line=npc_ja)

    coach = default_tutor_payload(
        goal_hits,
        coach_note="Good try! Match a key phrase from the briefing." if not success else "Nice!",
        hint_rung=state.hint_rung,
    )
    tutor_system = "You are Sora the tutor. Return JSON with goal_hits, coach_note_en, hint_rung."
    tutor_user = f"Utterance: {utterance}; hits: {goal_hits}"
    coach = await LLM.tutor_json(system=tutor_system, user=tutor_user, fallback=coach)

    audio = await synthesize(npc_ja, voice=state.scenario.npc.voice.engine)
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


@app.websocket("/ws/{session_id}")
async def ws_session(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    if session_id not in SESSIONS:
        await websocket.close(code=4404)
        return
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "turn":
                req = TurnRequest(
                    text=data.get("text"),
                    audio_b64=data.get("audio_b64"),
                )
                result = await session_turn(session_id, req)
                await websocket.send_json({"type": "turn_result", **result})
    except WebSocketDisconnect:
        return