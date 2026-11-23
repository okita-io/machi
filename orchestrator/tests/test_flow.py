from pathlib import Path

from machi.nlp import match_goal
from machi.scenario_loader import load_scenario
from machi.session import advance_node, evaluate_turn, new_session

FIRMNESS = ("かため", "ふつう", "やわらかめ", "katame", "futsuu", "yawarakame")

RESTAURANT = (
    Path(__file__).resolve().parents[2] / "scenarios" / "restaurant_ramen_01.yaml"
)


def test_party_size_match():
    assert match_goal("えっと、ふたりです", ["ふたりです", "二人です"])


def test_party_size_accepts_whisper_digit():
    spec = load_scenario(RESTAURANT)
    state = new_session(spec, level=1)
    hits, ok = evaluate_turn(state, "2人です。")
    assert ok and "party_size" in hits


def test_greet_to_seat_flow():
    spec = load_scenario(RESTAURANT)
    state = new_session(spec, level=1)
    hits, ok = evaluate_turn(state, "ふたりです")
    assert ok and "party_size" in hits
    advance_node(state, hits)
    assert state.node_id == "seat"


def _order(spec, level: int):
    state = new_session(spec, level=level)
    hits, ok = evaluate_turn(state, "ふたりです")
    assert ok
    advance_node(state, hits)
    hits, ok = evaluate_turn(state, "醤油ラーメン")
    assert ok and "order" in hits
    advance_node(state, hits)
    return state


def test_level2_order_skips_firmness():
    spec = load_scenario(RESTAURANT)
    state = _order(spec, 2)
    assert state.node_id == "confirm_order"
    assert "noodle_firmness" not in state.completed_goals


def test_level4_firmness_accepts_kana_and_romaji_then_advances():
    spec = load_scenario(RESTAURANT)
    goal = spec.goal_by_id("noodle_firmness")
    assert goal is not None
    for phrase in FIRMNESS:
        assert match_goal(phrase, goal.accept), phrase
        state = _order(spec, 4)
        assert state.node_id == "noodle_firmness"
        hits, ok = evaluate_turn(state, phrase)
        assert ok and hits == ["noodle_firmness"]
        advance_node(state, hits)
        assert state.node_id == "confirm_order"


def test_level4_wrong_firmness_stays_for_retry():
    spec = load_scenario(RESTAURANT)
    state = _order(spec, 4)
    hits, ok = evaluate_turn(state, "わからない")
    assert hits == [] and ok is False
    assert state.node_id == "noodle_firmness"
    assert state.retries == 1