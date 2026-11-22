"""Baked NPC line audio (``assets/audio/{scenario_id}/manifest.json``)."""

from __future__ import annotations

import json
from pathlib import Path

from machi.schema import ScenarioSpec


def fixed_npc_lines(scenario: ScenarioSpec) -> list[tuple[str, str]]:
    """Node id and text for each fixed ``flow.nodes.*.npc`` line, in YAML order."""
    lines: list[tuple[str, str]] = []
    for node_id, node in scenario.flow.nodes.items():
        if node.npc:
            lines.append((node_id, node.npc))
    return lines


def write_manifest(directory: Path, scenario_id: str, voice: str, files: dict[str, str]) -> Path:
    """Write ``manifest.json`` whose ``lines`` map node id to a wav filename."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest.json"
    payload = {"scenario_id": scenario_id, "voice": voice, "lines": files}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def cached_npc_wav(assets_path: str | Path, scenario: ScenarioSpec, text: str) -> bytes | None:
    """Return baked WAV bytes when ``text`` is still that node's fixed NPC line.

    A missing manifest, missing node, or missing file returns None so the caller
    can fall back to live TTS.
    """
    if not assets_path or not text:
        return None
    root = Path(assets_path)
    manifest_path = root / "audio" / scenario.id / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    files = _manifest_files(data)
    audio_dir = manifest_path.parent.resolve()
    for node_id, node in scenario.flow.nodes.items():
        if not node.npc or node.npc != text:
            continue
        filename = files.get(node_id)
        if filename is None:
            return None
        wav_path = (manifest_path.parent / filename).resolve()
        if wav_path.parent != audio_dir or not wav_path.is_file():
            return None
        return wav_path.read_bytes()
    return None


def _manifest_files(data: object) -> dict[str, str]:
    if not isinstance(data, dict):
        return {}
    bucket = data.get("lines") if isinstance(data.get("lines"), dict) else data
    if not isinstance(bucket, dict):
        return {}
    files: dict[str, str] = {}
    for key, value in bucket.items():
        name = _wav_name(value)
        if name is not None:
            files[str(key)] = name
    return files


def _wav_name(value: object) -> str | None:
    if isinstance(value, dict):
        return _wav_name(value.get("file"))
    if not isinstance(value, str) or not value.endswith(".wav"):
        return None
    if "/" in value or "\\" in value or value in {".wav", "..wav"}:
        return None
    return value
