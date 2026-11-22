"""Text enrichment: romaji via cutlet (when MeCab available); ruby from scenario kana."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_katsu: object | None = None
_katsu_failed = False


def to_romaji(text: str) -> str:
    global _katsu, _katsu_failed
    if _katsu_failed:
        return text
    if _katsu is None:
        try:
            import cutlet

            _katsu = cutlet.Cutlet()
        except Exception:
            logger.warning("cutlet/MeCab unavailable; romaji passthrough")
            _katsu_failed = True
            return text
    return _katsu.romaji(text)  # type: ignore[union-attr]


def build_ruby_html(text_ja: str, reading_kana: str | None) -> str:
    if not reading_kana:
        return text_ja
    return f'<ruby>{text_ja}<rt>{reading_kana}</rt></ruby>'


def match_goal(utterance: str, accept: list[str]) -> bool:
    normalized = _normalize(utterance)
    if not normalized:
        return False
    for phrase in accept:
        if _normalize(phrase) in normalized or normalized in _normalize(phrase):
            return True
    return False


def _normalize(s: str) -> str:
    return "".join(s.split()).lower()