"""Pydantic models for scenario YAML validation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_FORBID = ConfigDict(extra="forbid")


class LocalizedTitle(BaseModel):
    model_config = _FORBID
    en: str
    ja: str


class Hotspot(BaseModel):
    model_config = _FORBID
    rect: tuple[int, int, int, int]
    ja: str
    kana: str
    en: str
    opens: str | None = None
    # Mini-map pin. Directions uses these; other scenes leave them empty.
    x: int | None = None
    y: int | None = None


class SceneSpec(BaseModel):
    model_config = _FORBID
    background: str
    # Resting Sora plate. The web swaps sprites/sora/{expression}.webp from this path.
    sprite: str = "sprites/sora/neutral.webp"
    ambience: str | None = None
    hotspots: list[Hotspot] = Field(default_factory=list)
    # SVG polyline ("x,y x,y ...") the town UI draws as the ghost path.
    ghost_path: str | None = None


class VoiceSpec(BaseModel):
    model_config = _FORBID
    engine: str
    speaker: str | None = None
    style: str | None = None
    design: str | None = None


class NpcSpec(BaseModel):
    model_config = _FORBID
    id: str
    role: str
    voice: VoiceSpec
    register: str
    speed: dict[int, str] = Field(default_factory=dict)


class GuideSpec(BaseModel):
    model_config = _FORBID
    id: str
    voice: VoiceSpec
    brief_en: str | None = None
    sprite: str | None = None


class GoalSpec(BaseModel):
    model_config = _FORBID
    id: str
    prompt_en: str
    accept: list[str] = Field(default_factory=list)
    accept_intent: str | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    optional: bool = False
    coach_en: str | None = None


class KeyPhrase(BaseModel):
    model_config = _FORBID
    ja: str
    kana: str
    romaji: str
    en: str


class FlowOther(BaseModel):
    model_config = _FORBID
    clarify: str
    max_retries: int = 2


class FlowBranch(BaseModel):
    model_config = _FORBID
    when: dict[str, int] | None = None
    surprise: str | None = None


class FlowNode(BaseModel):
    model_config = _FORBID
    npc: str | None = None
    npc_kana: str | None = None
    expects: str | list[str] | None = None
    on_success: str | dict[str, str] | None = None
    on_other: FlowOther | None = None
    next: str | None = None
    branch: list[FlowBranch] = Field(default_factory=list)
    narration_en: str | None = None
    npc_on_success: str | None = None
    npc_on_success_kana: str | None = None
    end: bool = False
    debrief: bool = False


class FlowSpec(BaseModel):
    model_config = _FORBID
    start: str
    nodes: dict[str, FlowNode]


class SuccessSpec(BaseModel):
    model_config = _FORBID
    required: list[str]
    stars: dict[int, str] = Field(default_factory=dict)


# Spec hint ladder: level 1 English, 2 romaji, 3 kana, 4 no help.
HINT_DEFAULTS: dict[int, str] = {1: "english", 2: "romaji", 3: "kana", 4: "none"}


class ScenarioSpec(BaseModel):
    model_config = _FORBID
    id: str
    title: LocalizedTitle
    level: list[int]
    scene: SceneSpec
    npc: NpcSpec
    guide: GuideSpec
    goals: list[GoalSpec]
    key_phrases: list[KeyPhrase]
    flow: FlowSpec
    success: SuccessSpec
    srs_tags: list[str] = Field(default_factory=list)
    hint_defaults: dict[int, str] = Field(default_factory=dict)

    @field_validator("level")
    @classmethod
    def levels_positive(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("level must include at least one difficulty")
        return v

    @field_validator("hint_defaults")
    @classmethod
    def hint_defaults_match_spec(cls, v: dict[int, str]) -> dict[int, str]:
        if not v:
            return v
        if set(v) != set(HINT_DEFAULTS):
            raise ValueError("hint_defaults must define levels 1-4")
        for level, label in v.items():
            expected = HINT_DEFAULTS[level]
            if label != expected:
                raise ValueError(f"level {level} default hint is {expected}")
        return v

    def goal_by_id(self, goal_id: str) -> GoalSpec | None:
        for g in self.goals:
            if g.id == goal_id:
                return g
        return None