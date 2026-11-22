"""Session state and flow engine."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from machi.nlp import match_goal
from machi.schema import FlowNode, KeyPhrase, ScenarioSpec

PHASE_BRIEFING = "briefing"
PHASE_WARMUP = "warmup"
PHASE_ROLEPLAY = "roleplay"
PHASE_DEBRIEF = "debrief"


@dataclass
class SessionState:
    id: str
    scenario: ScenarioSpec
    level: int = 1
    node_id: str = ""
    completed_goals: set[str] = field(default_factory=set)
    hint_rung: int = 1
    retries: int = 0
    phase: str = PHASE_BRIEFING
    warmup_index: int = 0
    corrections: list[dict[str, str]] = field(default_factory=list)
    hint_peaks: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.node_id:
            self.node_id = self.scenario.flow.start
        if self.hint_rung == 1:
            self.hint_rung = default_rung_for_level(self.level)


def coaching_phrase(state: SessionState, node_id: str, utterance: str) -> str:
    """First accept phrase on the node, otherwise the learner line."""
    node = state.scenario.flow.nodes[node_id]
    for goal_id in expected_goals(node):
        goal = state.scenario.goal_by_id(goal_id)
        if goal is not None and goal.accept:
            return goal.accept[0]
    return utterance.strip()


def expected_goals(node: FlowNode) -> list[str]:
    if node.expects is None:
        return []
    if isinstance(node.expects, str):
        return [node.expects]
    return list(node.expects)


def evaluate_turn(
    state: SessionState,
    utterance: str,
) -> tuple[list[str], bool]:
    node = state.scenario.flow.nodes[state.node_id]
    if not expected_goals(node):
        return [], True

    hits: list[str] = []
    for goal_id in expected_goals(node):
        goal = state.scenario.goal_by_id(goal_id)
        if goal and goal.accept and match_goal(utterance, goal.accept):
            hits.append(goal_id)
            state.completed_goals.add(goal_id)
    success = bool(hits)
    if not success and node.on_other and state.retries < node.on_other.max_retries:
        state.retries += 1
    return hits, success


def advance_node(
    state: SessionState,
    goal_hits: list[str],
    *,
    progressed: bool = False,
) -> str | None:
    node = state.scenario.flow.nodes[state.node_id]
    if node.end:
        return None

    if progressed and not expected_goals(node) and node.next:
        state.node_id = node.next
        state.retries = 0
        return state.node_id

    if goal_hits and node.on_success is not None:
        if isinstance(node.on_success, str):
            state.node_id = node.on_success
        elif isinstance(node.on_success, dict):
            for g in goal_hits:
                if g in node.on_success:
                    state.node_id = node.on_success[g]
                    break
        state.retries = 0
        return state.node_id

    if node.next:
        state.node_id = node.next
        state.retries = 0
        return state.node_id

    return state.node_id


def maybe_chain_narration(state: SessionState) -> None:
    """Skip narration-only nodes (no NPC line) toward the next interactive step."""
    for _ in range(4):
        node = state.scenario.flow.nodes[state.node_id]
        if node.npc or node.expects or node.end:
            break
        if node.next:
            state.node_id = node.next
        else:
            break


def default_rung_for_level(level: int) -> int:
    if level <= 1:
        return 1
    if level >= 4:
        return 4
    return level


def stars_earned(level: int, hint_max: dict[str, int]) -> int:
    """3 at the level default, 2 after one climb, 1 after further climbs."""
    base = default_rung_for_level(level)
    extra = 0
    for rung in hint_max.values():
        extra = max(extra, max(0, int(rung) - base))
    if extra <= 0:
        return 3
    if extra == 1:
        return 2
    return 1


def goals_completed(state: SessionState) -> list[str]:
    """Required goals from ``success.required``, in scenario order."""
    return [
        goal_id
        for goal_id in state.scenario.success.required
        if goal_id in state.completed_goals
    ]


def scenario_complete(state: SessionState) -> bool:
    required = state.scenario.success.required
    return bool(required) and all(goal_id in state.completed_goals for goal_id in required)


def reset_flow(state: SessionState, *, phase: str) -> None:
    state.phase = phase
    state.node_id = state.scenario.flow.start
    state.completed_goals = set()
    state.retries = 0
    state.warmup_index = 0
    state.corrections = []
    state.hint_peaks = {}
    state.hint_rung = default_rung_for_level(state.level)


def note_hint_peaks(state: SessionState, hint_max: dict[str, int]) -> None:
    for key, rung in hint_max.items():
        state.hint_peaks[key] = max(state.hint_peaks.get(key, 0), int(rung))
    if hint_max:
        state.hint_rung = max(state.hint_rung, max(hint_max.values()))


def _phrase_accept(phrase: KeyPhrase) -> list[str]:
    return [part for part in (phrase.ja, phrase.kana, phrase.romaji, phrase.en) if part]


def begin_warmup(state: SessionState) -> KeyPhrase | None:
    """Enter warm-up on the first key phrase. No phrases skips straight to role-play."""
    state.warmup_index = 0
    phrases = state.scenario.key_phrases
    if not phrases:
        state.phase = PHASE_ROLEPLAY
        return None
    state.phase = PHASE_WARMUP
    return phrases[0]


def apply_warmup_attempt(state: SessionState, utterance: str) -> dict[str, Any]:
    """Score one phrase leniently and advance. A miss is not a failure."""
    phrases = state.scenario.key_phrases
    if not phrases or state.warmup_index >= len(phrases):
        state.phase = PHASE_ROLEPLAY
        return {"passed": True, "complete": True, "phrase": None, "next_phrase": None}
    phrase = phrases[state.warmup_index]
    passed = match_goal(utterance, _phrase_accept(phrase))
    state.warmup_index += 1
    complete = state.warmup_index >= len(phrases)
    if complete:
        state.phase = PHASE_ROLEPLAY
    next_phrase = None if complete else phrases[state.warmup_index]
    return {
        "passed": passed,
        "complete": complete,
        "phrase": phrase,
        "next_phrase": next_phrase,
    }


def remember_correction(state: SessionState, coach: dict[str, Any]) -> None:
    """Keep tutor corrections. Debrief shows the latest two."""
    en = coach.get("correction_en")
    ja = coach.get("correction_ja")
    en_text = en.strip() if isinstance(en, str) else ""
    ja_text = ja.strip() if isinstance(ja, str) else ""
    if not en_text and not ja_text:
        legacy = coach.get("correction")
        if isinstance(legacy, str) and legacy.strip():
            legacy = legacy.strip()
            if any(ord(ch) > 127 for ch in legacy):
                ja_text = legacy
            else:
                en_text = legacy
    if not en_text and not ja_text:
        return
    item = {"en": en_text, "ja": ja_text}
    if item not in state.corrections:
        state.corrections.append(item)


def scripted_npc_line(
    state: SessionState,
    prev_node_id: str,
    *,
    success: bool,
) -> tuple[str, str | None]:
    departed = state.scenario.flow.nodes[prev_node_id]
    current = state.scenario.flow.nodes[state.node_id]
    if success and prev_node_id != state.node_id and departed.npc_on_success:
        return departed.npc_on_success, departed.npc_on_success_kana
    if not success and current.on_other:
        return current.on_other.clarify, None
    if current.npc:
        return current.npc, current.npc_kana
    return "", None


def npc_line_for_node(state: SessionState, *, success: bool) -> tuple[str, str | None]:
    node = state.scenario.flow.nodes[state.node_id]
    if success and node.npc_on_success:
        return node.npc_on_success, node.npc_on_success_kana
    if node.npc:
        return node.npc, node.npc_kana
    if node.on_other:
        return node.on_other.clarify, None
    return node.npc or "", node.npc_kana


SORA_EXPRESSIONS = frozenset({"happy", "think", "cheer", "surprised", "sorry", "point"})

# Coach-note sentiment (and a few aliases) → Sora's expression id.
_SENTIMENT_EXPRESSION = {
    "happy": "happy",
    "positive": "happy",
    "glad": "happy",
    "cheer": "cheer",
    "celebrate": "cheer",
    "success": "cheer",
    "think": "think",
    "thinking": "think",
    "encourage": "think",
    "neutral": "think",
    "surprised": "surprised",
    "surprise": "surprised",
    "sorry": "sorry",
    "negative": "sorry",
    "apologetic": "sorry",
    "point": "point",
    "correction": "point",
    "correct": "point",
}


def expression_from_tutor(payload: dict[str, Any]) -> str:
    """Pick a Sora expression from explicit id, then coach-note sentiment."""
    explicit = payload.get("sora_expression")
    if isinstance(explicit, str) and explicit in SORA_EXPRESSIONS:
        return explicit
    for key in ("sentiment", "coach_note_sentiment"):
        sentiment = payload.get(key)
        if isinstance(sentiment, str) and sentiment in _SENTIMENT_EXPRESSION:
            return _SENTIMENT_EXPRESSION[sentiment]
    if payload.get("correction") or payload.get("correction_ja") or payload.get("correction_en"):
        return "point"
    hits = payload.get("goal_hits")
    if isinstance(hits, list) and hits:
        return "cheer"
    if payload.get("understandable") is False:
        return "sorry"
    return "think"


def default_tutor_payload(
    goal_hits: list[str],
    *,
    coach_note: str,
    hint_rung: int,
) -> dict[str, Any]:
    sentiment = "success" if goal_hits else "encourage"
    payload: dict[str, Any] = {
        "goal_hits": goal_hits,
        "slots": {},
        "understandable": bool(goal_hits),
        "correction": None,
        "correction_en": None,
        "correction_ja": None,
        "pronunciation_tip_en": None,
        "hint_rung": hint_rung,
        "step_out": False,
        "coach_note_en": coach_note,
        "sentiment": sentiment,
        "coach_note_sentiment": sentiment,
    }
    payload["sora_expression"] = expression_from_tutor(payload)
    return payload


def _nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _alias_correction(merged: dict[str, Any]) -> None:
    """Coach UI reads ``correction``. Prefer the Japanese phrase, then English."""
    ja = merged.get("correction_ja")
    en = merged.get("correction_en")
    ja_text = ja.strip() if isinstance(ja, str) else ""
    en_text = en.strip() if isinstance(en, str) else ""
    if ja_text:
        merged["correction"] = ja_text
    elif en_text and not _nonempty_str(merged.get("correction")):
        merged["correction"] = en_text


def normalize_tutor_payload(
    raw: dict[str, Any] | None,
    *,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    """Merge model JSON onto the mock payload and fill sora_expression."""
    source = raw if isinstance(raw, dict) else {}
    merged = dict(fallback)
    for key, value in source.items():
        if value is None and key not in (
            "correction",
            "correction_en",
            "correction_ja",
            "pronunciation_tip_en",
        ):
            continue
        merged[key] = value
    _alias_correction(merged)
    sentiment = merged.get("sentiment") or merged.get("coach_note_sentiment")
    if not isinstance(sentiment, str) or not sentiment:
        sentiment = "success" if merged.get("goal_hits") else "encourage"
    merged["sentiment"] = sentiment
    merged["coach_note_sentiment"] = sentiment
    if "sora_expression" not in source:
        merged.pop("sora_expression", None)
    merged["sora_expression"] = expression_from_tutor(merged)
    return merged


def new_session(scenario: ScenarioSpec, level: int = 1) -> SessionState:
    return SessionState(id=str(uuid.uuid4()), scenario=scenario, level=level)