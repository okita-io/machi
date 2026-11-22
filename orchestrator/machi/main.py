"""Machi orchestrator FastAPI app."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnected

from machi.clients import SpeechError, synthesize, transcribe
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
from machi.turn_taking import (
    TurnDecision,
    UtteranceGate,
    build_turn_gate,
    hands_free_turn_taking,
)
from machi.ws_audio import PCM_FRAME_BYTES, SessionAudioBuffer

logger = logging.getLogger(__name__)

SCENARIOS: dict = {}
SESSIONS: dict[str, SessionState] = {}
LLM = LlmClient()


class _InFlightTurn:
    """One running ``session_turn`` task for a WebSocket session."""

    def __init__(self) -> None:
        self.task: asyncio.Task[None] | None = None
        self.generation: int = 0


# Barge-in cancels the task in this map. A newer audio_start or turn bumps
# generation so a task that already finished its awaits still drops its result.
IN_FLIGHT: dict[str, _InFlightTurn] = {}


class _WsSink:
    """Serializes JSON sends so a turn task and the receive loop cannot overlap."""

    def __init__(self, websocket: WebSocket) -> None:
        self._ws = websocket
        self._lock = asyncio.Lock()

    async def send_json(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            await self._ws.send_json(payload)


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
    snapshot = _snapshot_flow(state)
    try:
        result = await _session_turn_pipeline(state, body, timer)
    except asyncio.CancelledError:
        # Barge-in: drop flow mutations so the learner can say the line again.
        _restore_flow(state, snapshot)
        timer.emit(session_id=session_id, cancelled=True)
        raise

    for key, value in timer.header_map().items():
        response.headers[key] = value
    timer.emit(session_id=session_id, cancelled=False)
    record_attempt(
        Path(settings.db_path),
        session_id,
        state.node_id,
        result["learner_text"],
        result["goal_hits"],
    )
    return result


async def _session_turn_pipeline(
    state: SessionState,
    body: TurnRequest,
    timer: TurnLatency,
) -> dict[str, Any]:
    # Blank text is not a typed turn, so audio_b64 alone still reaches ASR.
    utterance = (body.text or "").strip()
    try:
        if body.audio_b64 and not utterance:
            pcm = _decode_audio_b64(body.audio_b64)
            with timer.measure(STAGE_ASR):
                utterance = await transcribe(audio_pcm=pcm)
        elif not utterance:
            with timer.measure(STAGE_ASR):
                utterance = await transcribe(text_override="")
        else:
            # Typed text does not call ASR. Omit a zero duration.
            timer.skip(STAGE_ASR)
    except SpeechError as exc:
        raise _speech_unavailable(exc) from exc

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

    scripted_ja = npc_ja
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
        npc_ja = await LLM.npc_reply(system=npc_system, user=npc_user, fallback_line=scripted_ja)
        coach = await LLM.tutor_json(system=tutor_system, user=tutor_user, fallback=coach)

    try:
        with timer.measure(STAGE_TTS):
            audio = await synthesize(npc_ja, voice=state.scenario.npc.voice.engine)
    except SpeechError as exc:
        raise _speech_unavailable(exc) from exc

    return {
        "session_id": state.id,
        "node_id": state.node_id,
        "learner_text": utterance,
        "learner": enrich_line(utterance, None),
        "goal_hits": goal_hits,
        # npc_kana matches the scripted line only. A live rewrite gets token ruby.
        "npc": enrich_line(npc_ja, npc_kana if npc_ja == scripted_ja else None),
        "coach": coach,
        "tts_audio_b64": base64.b64encode(audio).decode("ascii"),
        "completed_goals": sorted(state.completed_goals),
    }


def _snapshot_flow(state: SessionState) -> tuple[str, set[str], int, int]:
    return (state.node_id, set(state.completed_goals), state.hint_rung, state.retries)


def _restore_flow(state: SessionState, snap: tuple[str, set[str], int, int]) -> None:
    node_id, goals, hint_rung, retries = snap
    state.node_id = node_id
    state.completed_goals = set(goals)
    state.hint_rung = hint_rung
    state.retries = retries


def _decode_audio_b64(audio_b64: str) -> bytes:
    try:
        return base64.b64decode(audio_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid audio_b64") from exc


def _speech_unavailable(exc: SpeechError) -> HTTPException:
    return HTTPException(status_code=502, detail=f"{exc.service}_unavailable")


def enrich_line(text_ja: str, kana: str | None) -> dict[str, str]:
    return {
        "ja": text_ja,
        "romaji": to_romaji(text_ja),
        "ruby_html": build_ruby_html(text_ja, kana),
    }


def _ws_bool(value: object) -> bool:
    return value is True


def _in_flight(session_id: str) -> _InFlightTurn:
    slot = IN_FLIGHT.get(session_id)
    if slot is None:
        slot = _InFlightTurn()
        IN_FLIGHT[session_id] = slot
    return slot


async def _cancel_inflight(session_id: str) -> None:
    """Cancel the session's running turn, if any, and wait until it stops."""
    slot = _in_flight(session_id)
    slot.generation += 1
    task = slot.task
    slot.task = None
    if task is None or task.done():
        return
    logger.info("barge-in cancel session=%s", session_id)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _schedule_ws_turn(
    sink: _WsSink,
    session_id: str,
    text: str | None,
    audio_b64: str | None,
) -> None:
    await _cancel_inflight(session_id)
    slot = _in_flight(session_id)
    generation = slot.generation
    task = asyncio.create_task(
        _deliver_ws_turn(sink, session_id, generation, text, audio_b64),
        name=f"machi-turn-{session_id}",
    )
    slot.task = task


async def _deliver_ws_turn(
    sink: _WsSink,
    session_id: str,
    generation: int,
    text: str | None,
    audio_b64: str | None,
) -> None:
    try:
        result = await session_turn(
            session_id,
            TurnRequest(text=text, audio_b64=audio_b64),
            Response(),
        )
    except asyncio.CancelledError:
        raise
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "turn_failed"
        await sink.send_json({"type": "error", "detail": detail})
        return
    except Exception:
        logger.exception("websocket turn failed session=%s", session_id)
        await sink.send_json({"type": "error", "detail": "turn_failed"})
        return
    slot = _in_flight(session_id)
    if slot.generation != generation or slot.task is not asyncio.current_task():
        return
    await sink.send_json({"type": "turn_result", **result})


async def _ws_pcm_frame(
    sink: _WsSink,
    session_id: str,
    buf: SessionAudioBuffer,
    gate: UtteranceGate | None,
    payload: bytes,
) -> None:
    if len(payload) != PCM_FRAME_BYTES:
        await sink.send_json(
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
    await sink.send_json(
        {
            "type": "audio_ack",
            "frames": buf.frames,
            "event": "frame",
            "accepted": accepted,
            "bytes": PCM_FRAME_BYTES,
        }
    )
    # Push-to-talk never reaches the VAD or the turn scorer.
    if not accepted or not hands_free_turn_taking(buf.hands_free, gate):
        return
    try:
        decision = gate.observe(payload, bytes(buf.pcm))
    except Exception:
        logger.exception("hands-free VAD failed session=%s", session_id)
        return
    if decision is not TurnDecision.CUT:
        return
    logger.info("hands-free endpoint session=%s", session_id)
    await _ws_turn(sink, session_id, buf, {})
    gate.reset()
    buf.start(hands_free=True)


async def _ws_turn(
    sink: _WsSink,
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
    await _schedule_ws_turn(sink, session_id, text, audio_b64)


async def _ws_control(
    sink: _WsSink,
    session_id: str,
    buf: SessionAudioBuffer,
    gate: UtteranceGate | None,
    raw: str,
) -> None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        await sink.send_json({"type": "error", "detail": "invalid_json"})
        return
    if not isinstance(data, dict):
        await sink.send_json({"type": "error", "detail": "expected_object"})
        return
    kind = data.get("type")
    if kind == "audio_start":
        # New speech supersedes an NPC line still being generated.
        await _cancel_inflight(session_id)
        buf.start(hands_free=_ws_bool(data.get("hands_free")))
        if hands_free_turn_taking(buf.hands_free, gate):
            gate.reset()
        await sink.send_json(
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
        await sink.send_json(
            {
                "type": "audio_ack",
                "frames": frames,
                "event": "audio_stop",
                "bytes": len(buf.pcm),
            }
        )
        return
    if kind == "turn":
        await _ws_turn(sink, session_id, buf, data)
        return
    await sink.send_json({"type": "error", "detail": "unknown_type"})


@app.websocket("/ws/{session_id}")
async def ws_session(websocket: WebSocket, session_id: str) -> None:
    """JSON control plus 640-byte PCM frames. Replies are JSON only.

    Push-to-talk (``hands_free`` false or omitted) only stores PCM until the
    client sends ``turn``. That path does not call Silero VAD or the turn
    scorer. Hands-free runs VAD on each accepted frame and, after the scorer
    cuts (or the 500 ms silence ceiling), emits ``turn_result`` the same way
    a client ``turn`` event does.

    Each session has at most one in-flight turn task. A new ``audio_start`` or
    ``turn`` cancels it. The cancelled task does not send ``turn_result``.
    """
    await websocket.accept()
    if session_id not in SESSIONS:
        await websocket.close(code=4404)
        return
    sink = _WsSink(websocket)
    buf = SessionAudioBuffer()
    gate = build_turn_gate()
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return
            payload = message.get("bytes")
            raw = message.get("text")
            if payload is not None:
                await _ws_pcm_frame(sink, session_id, buf, gate, payload)
            elif raw is not None:
                await _ws_control(sink, session_id, buf, gate, raw)
    except (WebSocketDisconnect, WebSocketDisconnected):
        return
    finally:
        await _cancel_inflight(session_id)
        IN_FLIGHT.pop(session_id, None)