from pathlib import Path

from machi.nlp import match_goal
from machi.scenario_loader import load_scenario
from machi.session import advance_node, evaluate_turn, new_session

RESTAURANT = (
    Path(__file__).resolve().parents[2] / "scenarios" / "restaurant_ramen_01.yaml"
)


def test_party_size_match():
    assert match_goal("えっと、ふたりです", ["ふたりです", "二人です"])


def test_greet_to_seat_flow():
    spec = load_scenario(RESTAURANT)
    state = new_session(spec, level=1)
    hits, ok = evaluate_turn(state, "ふたりです")
    assert ok and "party_size" in hits
    advance_node(state, hits)
    assert state.node_id == "seat"