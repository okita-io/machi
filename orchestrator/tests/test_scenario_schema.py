from pathlib import Path

import pytest
import yaml

from machi.scenario_loader import load_scenario
from machi.schema import ScenarioSpec

REPO_ROOT = Path(__file__).resolve().parents[2]
RESTAURANT = REPO_ROOT / "scenarios" / "restaurant_ramen_01.yaml"


def test_restaurant_scenario_validates():
    spec = load_scenario(RESTAURANT)
    assert spec.id == "restaurant_ramen_01"
    assert spec.flow.start == "greet"
    assert len(spec.goals) >= 3


def test_all_yaml_in_scenarios_dir():
    for path in (REPO_ROOT / "scenarios").glob("*.yaml"):
        load_scenario(path)


def test_rejects_empty_levels():
    data = yaml.safe_load(RESTAURANT.read_text(encoding="utf-8"))
    data["level"] = []
    with pytest.raises(Exception):
        ScenarioSpec.model_validate(data)