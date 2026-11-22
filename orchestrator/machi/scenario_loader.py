from pathlib import Path

import yaml

from machi.schema import ScenarioSpec


def load_scenario(path: Path) -> ScenarioSpec:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ScenarioSpec.model_validate(data)


def load_all_scenarios(directory: Path) -> dict[str, ScenarioSpec]:
    scenarios: dict[str, ScenarioSpec] = {}
    if not directory.is_dir():
        return scenarios
    for file in sorted(directory.glob("*.yaml")):
        spec = load_scenario(file)
        scenarios[spec.id] = spec
    return scenarios