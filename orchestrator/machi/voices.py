"""Resolve guide and NPC speakers through ``voices/voices.yaml``."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from machi.config import settings

logger = logging.getLogger(__name__)

ALLOWED_LICENSES = frozenset({"Apache-2.0", "MIT", "BSD", "BSD-2-Clause", "BSD-3-Clause"})
ALLOWED_PROFILES = frozenset({"cpu", "stub", "spark", "rtx3090"})
# cpu and stub are one demo bucket: an engine listed for either may run on both.
_DEMO_PROFILES = frozenset({"cpu", "stub"})
STUB_ENGINE = "stub"


class EngineEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    repo: str
    license: str
    profiles: list[str] = Field(default_factory=list)
    speaker: str | None = None


class VoiceEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str = ""
    aliases: list[str] = Field(default_factory=list)
    voice_id: str = ""
    version: str = ""
    engine: str | None = None
    speaker: str | None = None
    style: str | None = None
    design: str | None = None
    fallback: list[str] = Field(default_factory=list)


class VoiceCatalog(BaseModel):
    model_config = ConfigDict(extra="ignore")

    engines: dict[str, EngineEntry] = Field(default_factory=dict)
    voices: dict[str, VoiceEntry] = Field(default_factory=dict)
    aliases: dict[str, str] = Field(default_factory=dict)

    def lookup(self, name: str) -> VoiceEntry | None:
        if name in self.voices:
            return self.voices[name]
        alias = self.aliases.get(name)
        if alias is None:
            return None
        return self.voices.get(alias)


_catalog_cache: dict[tuple[str, int], VoiceCatalog] = {}
_missing_warned: set[str] = set()


def voices_file(path: Path | None = None) -> Path:
    """Configured path when that file exists, otherwise the repo copy."""
    if path is not None:
        return path
    configured = Path(settings.voices_path)
    if configured.is_file():
        return configured
    bundled = Path(__file__).resolve().parents[2] / "voices" / "voices.yaml"
    if bundled.is_file():
        return bundled
    return configured


def engine_available(profiles: list[str], speech_profile: str) -> bool:
    """Empty profile keeps the voice's preferred engine. cpu and stub match each other."""
    active = speech_profile.strip().lower()
    if not active:
        return True
    listed = {item.strip().lower() for item in profiles}
    if active in listed:
        return True
    return active in _DEMO_PROFILES and bool(listed & _DEMO_PROFILES)


def _fallback_chain(entry: VoiceEntry) -> list[str]:
    chain = [item.strip() for item in entry.fallback if item.strip()]
    if chain:
        return chain
    if entry.engine:
        engine = entry.engine.strip()
        if engine and engine != STUB_ENGINE:
            return [engine, STUB_ENGINE]
        if engine:
            return [engine]
    return [STUB_ENGINE]


def load_voice_catalog(path: Path | None = None) -> VoiceCatalog:
    """Parse the voice map. A missing or invalid file yields an empty catalog."""
    file = voices_file(path)
    if not file.is_file():
        key = str(file)
        if key not in _missing_warned:
            _missing_warned.add(key)
            logger.warning("voice map missing at %s; unknown voices use stub", file)
        return VoiceCatalog()
    stamp = file.stat().st_mtime_ns
    cache_key = (str(file.resolve()), stamp)
    cached = _catalog_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        engines = {
            name: EngineEntry.model_validate(body)
            for name, body in dict(raw.get("engines") or {}).items()
        }
        voices = {
            name: VoiceEntry.model_validate(body)
            for name, body in dict(raw.get("voices") or {}).items()
        }
    except (OSError, yaml.YAMLError, ValueError) as exc:
        logger.warning("voice map %s failed to load; using stub (%s)", file, exc)
        return VoiceCatalog()
    aliases: dict[str, str] = {}
    for name, entry in voices.items():
        entry.fallback = _fallback_chain(entry)
        for alias in entry.aliases:
            aliases[alias] = name
    catalog = VoiceCatalog(engines=engines, voices=voices, aliases=aliases)
    _catalog_cache[cache_key] = catalog
    return catalog


def resolve_voice(name: str, *, profile: str | None = None, path: Path | None = None) -> str:
    """Engine name for TTS. Unknown speakers log a warning and return ``stub``."""
    catalog = load_voice_catalog(path)
    active = settings.speech_profile if profile is None else profile
    voice = catalog.lookup(name.strip())
    if voice is None:
        logger.warning("unknown voice %r; using stub", name)
        return STUB_ENGINE
    for engine_name in voice.fallback:
        engine = catalog.engines.get(engine_name)
        if engine is None:
            logger.warning("voice %r lists unknown engine %s; skipping", name, engine_name)
            continue
        if engine.license not in ALLOWED_LICENSES:
            logger.warning(
                "engine %s license %s is not allowed; skipping",
                engine_name,
                engine.license,
            )
            continue
        if engine_available(engine.profiles, active):
            return engine_name
    logger.warning(
        "no usable engine for voice %r (profile %r); using stub",
        name,
        active.strip().lower() or "any",
    )
    return STUB_ENGINE
