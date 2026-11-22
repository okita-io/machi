"""Pydantic models for scenario YAML validation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class LocalizedTitle(BaseModel):
    en: str
    ja: str


class Hotspot(BaseModel):
    rect: tuple[int, int, int, int]
    ja: str
    kana: str
    en: str
    opens: str | None = None


class SceneSpec(BaseModel):
    background: str
    ambience: str | None = None
    hotspots: list[Hotspot] = Field(default_factory=list)


class VoiceSpec(BaseModel):
    engine: str
    speaker: str | None = None
    style: str | None = None
    design: str | None = None


class NpcSpec(BaseModel):
    id: str
    role: str
    voice: VoiceSpec
    register: str
    speed: dict[int, str] = Field(default_factory=dict)


class GuideSpec(BaseModel):
    id: str
    voice: VoiceSpec


class GoalSpec(BaseModel):
    id: str
    prompt_en: str
    accept: list[str] = Field(default_factory=list)
    accept_intent: str | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    optional: bool = False


class KeyPhrase(BaseModel):
    ja: str
    kana: str
    romaji: str
    en: str


class FlowOther(BaseModel):
    clarify: str
    max_retries: int = 2


class FlowBranch(BaseModel):
    when: dict[str, int] | None = None
    surprise: str | None = None


class FlowNode(BaseModel):
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
    start: str
    nodes: dict[str, FlowNode]


class SuccessSpec(BaseModel):
    required: list[str]
    stars: dict[int, str] = Field(default_factory=dict)


class ScenarioSpec(BaseModel):
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

    @field_validator("level")
    @classmethod
    def levels_positive(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("level must include at least one difficulty")
        return v

    def goal_by_id(self, goal_id: str) -> GoalSpec | None:
        for g in self.goals:
            if g.id == goal_id:
                return g
        return None