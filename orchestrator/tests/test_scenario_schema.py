from pathlib import Path

import pytest
import yaml

from machi.scenario_loader import load_scenario
from machi.schema import HINT_DEFAULTS, FlowNode, ScenarioSpec
from machi.session import advance_node, evaluate_turn, expected_goals, new_session

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = REPO_ROOT / "scenarios"
RESTAURANT = SCENARIOS / "restaurant_ramen_01.yaml"
SCENARIO_PATHS = sorted(SCENARIOS.glob("*.yaml"))
NEIGHBORHOOD = {
    "konbini_checkout_01",
    "directions_01",
    "coin_laundry_01",
    "taxi_01",
    "train_ticket_01",
}


def test_restaurant_scenario_validates():
    spec = load_scenario(RESTAURANT)
    assert spec.id == "restaurant_ramen_01"
    assert spec.flow.start == "greet"
    assert len(spec.goals) >= 3


def test_all_yaml_in_scenarios_dir():
    loaded = {load_scenario(path).id for path in SCENARIO_PATHS}
    assert NEIGHBORHOOD <= loaded


def _edge_targets(node: FlowNode) -> list[str]:
    targets: list[str] = []
    if isinstance(node.on_success, str):
        targets.append(node.on_success)
    elif isinstance(node.on_success, dict):
        targets.extend(node.on_success.values())
    if node.next:
        targets.append(node.next)
    return targets


def _reachable(spec: ScenarioSpec) -> set[str]:
    seen: set[str] = set()
    stack = [spec.flow.start]
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        stack.extend(_edge_targets(spec.flow.nodes[node_id]))
    return seen


def _play_to_debrief(spec: ScenarioSpec) -> set[str]:
    """Walk greet → goals → debrief using the first accept phrase on each node."""
    state = new_session(spec, level=1)
    for _ in range(12):
        node = spec.flow.nodes[state.node_id]
        if node.debrief or node.end:
            break
        goals = expected_goals(node)
        if goals:
            goal = spec.goal_by_id(goals[0])
            assert goal is not None and goal.accept
            utterance = goal.accept[0]
        else:
            utterance = "はい"
        hits, ok = evaluate_turn(state, utterance)
        assert ok, f"{spec.id}:{state.node_id} rejected {utterance!r}"
        advance_node(state, hits, progressed=True)
    assert spec.flow.nodes[state.node_id].debrief, spec.id
    return set(state.completed_goals)


@pytest.mark.parametrize("path", SCENARIO_PATHS, ids=lambda path: path.name)
def test_scenario_yaml_invariants(path: Path):
    spec = load_scenario(path)
    nodes = spec.flow.nodes
    assert spec.flow.start in nodes
    assert len(nodes) == len(set(nodes))
    goal_ids = [goal.id for goal in spec.goals]
    assert len(goal_ids) == len(set(goal_ids))
    assert set(spec.success.required) <= set(goal_ids)
    assert spec.success.required
    assert 3 <= len(spec.key_phrases) <= 5

    for goal in spec.goals:
        assert goal.accept, goal.id
        assert goal.prompt_en.strip()

    for node_id, node in nodes.items():
        for target in _edge_targets(node):
            assert target in nodes, f"{spec.id}:{node_id} -> {target}"
        for goal_id in expected_goals(node):
            assert goal_id in goal_ids, f"{spec.id}:{node_id} expects {goal_id}"
        if node.npc:
            assert node.npc_kana, node_id
        if node.npc_on_success:
            assert node.npc_on_success_kana, node_id

    ends = [node_id for node_id, node in nodes.items() if node.end]
    assert len(ends) == 1
    end_id = ends[0]
    assert nodes[end_id].debrief
    assert end_id in _reachable(spec)

    completed = _play_to_debrief(spec)
    assert set(spec.success.required) <= completed

    if spec.id in NEIGHBORHOOD:
        assert spec.level == [1, 2, 3, 4]
        assert spec.hint_defaults == HINT_DEFAULTS
        assert spec.guide.brief_en
        assert 4 <= len(nodes) <= 7
        for goal in spec.goals:
            assert goal.coach_en

    if spec.id == "directions_01":
        assert spec.scene.background == "bg/street.webp"
        assert spec.scene.ghost_path
        assert len(spec.scene.hotspots) >= 3
        for hotspot in spec.scene.hotspots:
            assert hotspot.x is not None and hotspot.y is not None

    if spec.id == "coin_laundry_01":
        assert len(spec.scene.hotspots) >= 3


def test_rejects_empty_levels():
    data = yaml.safe_load(RESTAURANT.read_text(encoding="utf-8"))
    data["level"] = []
    with pytest.raises(Exception):
        ScenarioSpec.model_validate(data)