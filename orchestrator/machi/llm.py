"""OpenAI-compatible LLM client with mock fallback and prompt templates."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from enum import StrEnum
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from machi.config import settings

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_PLACEHOLDER = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")

CompleteFn = Callable[..., Awaitable[str]]


class SoraExpression(StrEnum):
    happy = "happy"
    think = "think"
    cheer = "cheer"
    surprised = "surprised"
    sorry = "sorry"
    point = "point"


class TutorResponse(BaseModel):
    """Strict tutor JSON. Unknown keys and unknown expressions are rejected."""

    model_config = ConfigDict(extra="forbid")

    goal_hits: list[str]
    correction_en: str | None = None
    correction_ja: str | None = None
    coach_note_en: str
    hint_rung: int = Field(ge=1, le=4)
    sora_expression: SoraExpression


def render_prompt(name: str, values: dict[str, object]) -> str:
    """Load ``orchestrator/prompts/<name>`` and fill ``{{placeholders}}``."""
    path = PROMPTS_DIR / name
    text = path.read_text(encoding="utf-8")

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(key)
        return str(values[key])

    return _PLACEHOLDER.sub(repl, text).strip()


def parse_tutor_payload(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    """Validate one tutor payload. The error string is safe to append on retry."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON ({exc.msg})"
    if not isinstance(data, dict):
        return None, "expected a JSON object"
    try:
        model = TutorResponse.model_validate(data)
    except ValidationError as exc:
        return None, str(exc)
    return model.model_dump(mode="json"), None


class LlmClient:
    def __init__(self, *, complete: CompleteFn | None = None) -> None:
        self._complete_override = complete
        self._client: AsyncOpenAI | None = None
        if settings.llm_base_url.strip():
            self._client = AsyncOpenAI(
                base_url=settings.llm_base_url.rstrip("/"),
                api_key=settings.llm_api_key or "none",
            )

    @property
    def using_mock(self) -> bool:
        return self._client is None and self._complete_override is None

    async def _complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
    ) -> str:
        if self._complete_override is not None:
            return await self._complete_override(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
            )
        if self._client is None:
            raise RuntimeError("LLM client is mocked")
        kwargs: dict[str, Any] = {
            "model": settings.llm_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = await self._client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip()

    async def npc_reply(
        self,
        *,
        system: str,
        user: str,
        fallback_line: str,
    ) -> str:
        if self.using_mock:
            return fallback_line
        try:
            text = await self._complete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=120,
                temperature=0.4,
                json_mode=False,
            )
            return text or fallback_line
        except Exception:
            logger.exception("LLM NPC call failed; using fallback")
            return fallback_line

    async def tutor_json(
        self,
        *,
        system: str,
        user: str,
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        if self.using_mock:
            return fallback
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            raw = await self._complete(
                messages,
                max_tokens=300,
                temperature=0.2,
                json_mode=True,
            )
        except Exception:
            logger.exception("LLM tutor call failed; using fallback")
            return fallback
        parsed, err = parse_tutor_payload(raw)
        if parsed is not None:
            return parsed
        # One repair retry: same prompt with the validation error appended.
        retry_user = f"{user}\n\nValidation error: {err}"
        try:
            raw_retry = await self._complete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": retry_user},
                ],
                max_tokens=300,
                temperature=0.2,
                json_mode=True,
            )
        except Exception:
            logger.exception("LLM tutor retry failed; using fallback")
            return fallback
        parsed, retry_err = parse_tutor_payload(raw_retry)
        if parsed is not None:
            return parsed
        logger.warning("tutor JSON invalid after retry: %s", retry_err)
        return fallback
