"""Voice map: Sora's Irodori chain, NPC Qwen ids, stub fallback."""

import logging
from pathlib import Path

from machi.scenario_loader import load_all_scenarios
from machi.voices import (
    ALLOWED_LICENSES,
    ALLOWED_PROFILES,
    load_voice_catalog,
    resolve_voice,
)

ROOT = Path(__file__).resolve().parents[2]


def test_voice_map_lists_engines_and_sora_chain():
    catalog = load_voice_catalog(ROOT / "voices" / "voices.yaml")
    assert set(catalog.engines) == {"irodori", "kokoro", "qwen3_tts", "stub"}
    for engine in catalog.engines.values():
        assert engine.repo
        assert engine.license in ALLOWED_LICENSES
        assert engine.profiles
        assert set(engine.profiles) <= ALLOWED_PROFILES
    sora = catalog.voices["sora"]
    assert sora.voice_id == "irodori_small"
    assert sora.version == "v4.1"
    assert sora.fallback == ["irodori", "kokoro", "stub"]
    assert catalog.lookup("guide") is sora
    for name, voice in catalog.voices.items():
        if voice.role != "npc":
            continue
        assert voice.engine == "qwen3_tts"
        assert voice.voice_id == "Ono_Anna"
        assert name in {
            "staff_tanaka",
            "clerk_aoki",
            "local_mori",
            "attendant_kondo",
            "driver_sato",
            "clerk_hayashi",
        }


def test_scenarios_resolve_through_the_map():
    scenarios = load_all_scenarios(ROOT / "scenarios")
    assert len(scenarios) >= 6
    for spec in scenarios.values():
        assert resolve_voice(spec.npc.id) == "qwen3_tts"
        assert resolve_voice(spec.guide.id) == "irodori"
    assert resolve_voice("guide") == "irodori"
    assert resolve_voice("sora", profile="spark") == "irodori"
    assert resolve_voice("sora", profile="rtx3090") == "irodori"
    assert resolve_voice("sora", profile="cpu") == "kokoro"
    assert resolve_voice("guide", profile="stub") == "kokoro"
    assert resolve_voice("staff_tanaka", profile="cpu") == "stub"
    assert resolve_voice("clerk_hayashi", profile="rtx3090") == "qwen3_tts"


def test_unknown_voice_falls_back_to_stub(caplog):
    with caplog.at_level(logging.WARNING, logger="machi.voices"):
        assert resolve_voice("not-a-voice") == "stub"
    assert "unknown voice" in caplog.text
    assert "not-a-voice" in caplog.text


def test_disallowed_license_skips_to_stub(tmp_path, caplog):
    bad = tmp_path / "voices.yaml"
    bad.write_text(
        """
engines:
  evil:
    repo: example/evil
    license: GPL-3.0
    profiles: [spark, rtx3090]
  stub:
    repo: machi/speech-cpu
    license: MIT
    profiles: [cpu, stub, spark, rtx3090]
voices:
  sora:
    voice_id: irodori_small
    version: v4.1
    fallback: [evil, stub]
""",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="machi.voices"):
        assert resolve_voice("sora", path=bad) == "stub"
    assert "GPL-3.0" in caplog.text
