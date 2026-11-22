"""Session state and flow engine."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from machi.nlp import match_goal
from machi.schema import FlowNode, ScenarioSpec


@dataclass
class SessionState:
    id: str
    scenario: ScenarioSpec
    level: int = 1
    node_id: str = ""
    completed_goals: set[str] = field(default_factory=set)
    hint_rung: int = 1
    retries: int = 0

    def __post_init__(self) -> None:
        if not self.node_id:
            self.node_id = self.scenario.flow.start


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


def npc_line_for_node(state: SessionState, *, success: bool) -> tuple[str, str | None]:
    node = state.scenario.flow.nodes[state.node_id]
    if success and node.npc_on_success:
        return node.npc_on_success, node.npc_on_success_kana
    if node.npc:
        return node.npc, node.npc_kana
    if node.on_other:
        return node.on_other.clarify, None
    return node.npc or "", node.npc_kana


def default_tutor_payload(
    goal_hits: list[str],
    *,
    coach_note: str,
    hint_rung: int,
) -> dict[str, Any]:
    return {
        "goal_hits": goal_hits,
        "slots": {},
        "understandable": bool(goal_hits),
        "correction": None,
        "pronunciation_tip_en": None,
        "hint_rung": hint_rung,
        "step_out": False,
        "coach_note_en": coach_note,
    }


def new_session(scenario: ScenarioSpec, level: int = 1) -> SessionState:
    return SessionState(id=str(uuid.uuid4()), scenario=scenario, level=level)