from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from machi.schema import FlowNode, ScenarioSpec


def load_scenario(path: Path) -> ScenarioSpec:
    return scenario_from_text(path.read_text(encoding="utf-8"))


def scenario_from_text(text: str) -> ScenarioSpec:
    data = yaml.safe_load(text)
    return ScenarioSpec.model_validate(data)


def load_scenario_bundle(directory: Path) -> tuple[dict[str, ScenarioSpec], dict[str, str]]:
    """Parsed specs plus the original YAML, keyed by scenario id."""
    scenarios: dict[str, ScenarioSpec] = {}
    texts: dict[str, str] = {}
    if not directory.is_dir():
        return scenarios, texts
    for file in sorted(directory.glob("*.yaml")):
        text = file.read_text(encoding="utf-8")
        spec = scenario_from_text(text)
        scenarios[spec.id] = spec
        texts[spec.id] = text
    return scenarios, texts


def load_all_scenarios(directory: Path) -> dict[str, ScenarioSpec]:
    scenarios, _texts = load_scenario_bundle(directory)
    return scenarios


def _scalar_key(node: yaml.Node) -> Any:
    if not isinstance(node, yaml.ScalarNode):
        return None
    if node.tag == "tag:yaml.org,2002:int":
        return int(node.value)
    if node.tag == "tag:yaml.org,2002:float":
        return float(node.value)
    if node.tag == "tag:yaml.org,2002:bool":
        return node.value.lower() == "true"
    return node.value


def yaml_line_index(text: str) -> dict[tuple[Any, ...], int]:
    """Map a path of mapping keys and sequence indexes to a 1-based line."""
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    lines: dict[tuple[Any, ...], int] = {}

    def walk(node: yaml.Node | None, path: tuple[Any, ...]) -> None:
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                key = _scalar_key(key_node)
                child = path + (key,)
                if isinstance(value_node, yaml.ScalarNode):
                    mark = value_node.start_mark
                else:
                    mark = key_node.start_mark
                lines[child] = mark.line + 1
                walk(value_node, child)
        elif isinstance(node, yaml.SequenceNode):
            for index, item in enumerate(node.value):
                child = path + (index,)
                lines[child] = item.start_mark.line + 1
                walk(item, child)

    walk(root, ())
    return lines


def _line_for(lines: dict[tuple[Any, ...], int], loc: tuple[Any, ...]) -> int | None:
    for size in range(len(loc), 0, -1):
        found = lines.get(tuple(loc[:size]))
        if found is not None:
            return found
    return None


def _issue(path: str, message: str, line: int | None) -> dict[str, Any]:
    return {"path": path, "message": message, "line": line}


def _outgoing(node: FlowNode) -> list[tuple[str, str, tuple[Any, ...]]]:
    edges: list[tuple[str, str, tuple[Any, ...]]] = []
    if isinstance(node.on_success, str):
        edges.append(("on_success", node.on_success, ("on_success",)))
    elif isinstance(node.on_success, dict):
        for key, dest in node.on_success.items():
            edges.append((f"on_success.{key}", dest, ("on_success", key)))
    if node.next:
        edges.append(("next", node.next, ("next",)))
    if node.high:
        edges.append(("high", node.high, ("high",)))
    if node.low:
        edges.append(("low", node.low, ("low",)))
    return edges


def _graph_issues(spec: ScenarioSpec, lines: dict[tuple[Any, ...], int]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    nodes = spec.flow.nodes
    if spec.flow.start not in nodes:
        issues.append(
            _issue(
                "flow.start",
                f"start {spec.flow.start!r} is not a node",
                _line_for(lines, ("flow", "start")),
            )
        )
    for node_id, node in nodes.items():
        edges = _outgoing(node)
        if not node.end and not node.debrief and not edges:
            issues.append(
                _issue(
                    f"flow.nodes.{node_id}",
                    f"node {node_id!r} is missing an outgoing edge",
                    _line_for(lines, ("flow", "nodes", node_id)),
                )
            )
        for label, dest, suffix in edges:
            if dest not in nodes:
                path = ("flow", "nodes", node_id, *suffix)
                issues.append(
                    _issue(
                        f"flow.nodes.{node_id}.{label}",
                        f"edge to unknown node {dest!r}",
                        _line_for(lines, path),
                    )
                )
    return issues


def validate_scenario_text(text: str) -> tuple[ScenarioSpec | None, list[dict[str, Any]]]:
    """Parse and validate YAML in memory. Does not read or write the filesystem."""
    try:
        lines = yaml_line_index(text)
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 1 if mark is not None else None
        message = getattr(exc, "problem", None) or str(exc)
        return None, [_issue("yaml", str(message).strip(), line)]

    if not isinstance(data, dict):
        return None, [_issue("yaml", "scenario must be a YAML mapping", 1)]

    try:
        spec = ScenarioSpec.model_validate(data)
    except ValidationError as exc:
        issues = []
        for err in exc.errors():
            loc = tuple(err.get("loc") or ())
            path = ".".join(str(part) for part in loc) or "<root>"
            issues.append(_issue(path, err.get("msg", "invalid"), _line_for(lines, loc)))
        return None, issues

    graph = _graph_issues(spec, lines)
    if graph:
        return None, graph
    return spec, []
