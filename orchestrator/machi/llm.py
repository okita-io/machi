"""OpenAI-compatible LLM client with mock fallback."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from machi.config import settings

logger = logging.getLogger(__name__)


class LlmClient:
    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None
        if settings.llm_base_url.strip():
            self._client = AsyncOpenAI(
                base_url=settings.llm_base_url.rstrip("/"),
                api_key=settings.llm_api_key or "none",
            )

    @property
    def using_mock(self) -> bool:
        return self._client is None

    async def npc_reply(
        self,
        *,
        system: str,
        user: str,
        fallback_line: str,
    ) -> str:
        if self._client is None:
            return fallback_line
        try:
            resp = await self._client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=120,
                temperature=0.4,
            )
            text = (resp.choices[0].message.content or "").strip()
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
        if self._client is None:
            return fallback
        try:
            resp = await self._client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=300,
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            raw = (resp.choices[0].message.content or "").strip()
            return json.loads(raw) if raw else fallback
        except Exception:
            logger.exception("LLM tutor call failed; using fallback")
            return fallback