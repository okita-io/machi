"""Text enrichment: romaji via cutlet; per-token furigana via fugashi + unidic-lite.

Both libraries are default dependencies (MIT / unidic-lite). If an import fails,
readings fall back to the original text so a CPU checkout without the wheels
still serves a turn.
"""

from __future__ import annotations

import html
import logging
import re

logger = logging.getLogger(__name__)

_katsu: object | None = None
_katsu_failed = False
_tagger: object | None = None
_tagger_failed = False

# Printable ASCII (and controls) stay as themselves so mixed English is readable.
_ASCII = re.compile(r"^[\x00-\x7f]+$")


def to_romaji(text: str) -> str:
    """Hepburn romaji for arbitrary Japanese, including kanji. Passthrough on failure."""
    global _katsu, _katsu_failed
    if not text:
        return ""
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
    try:
        return _katsu.romaji(text)  # type: ignore[union-attr]
    except Exception:
        logger.warning("cutlet failed; romaji passthrough")
        return text


def ruby_for_text(text: str) -> str:
    """Per-token ``<ruby>`` HTML. Readings are hiragana from unidic-lite ``kana``."""
    if not text:
        return ""
    tagger = _get_tagger()
    if tagger is None:
        return html.escape(text)
    parts: list[str] = []
    for word in tagger(text):  # type: ignore[operator]
        space = getattr(word, "white_space", "") or ""
        if space:
            parts.append(html.escape(space))
        parts.append(_token_ruby(word.surface, _hiragana_reading(word)))
    return "".join(parts) if parts else html.escape(text)


def build_ruby_html(text_ja: str, reading_kana: str | None) -> str:
    """Token ruby, or one whole-line ruby when ``reading_kana`` is set (YAML override)."""
    if reading_kana:
        return f"<ruby>{html.escape(text_ja)}<rt>{html.escape(reading_kana)}</rt></ruby>"
    return ruby_for_text(text_ja)


def match_goal(utterance: str, accept: list[str]) -> bool:
    normalized = _normalize(utterance)
    if not normalized:
        return False
    for phrase in accept:
        if _normalize(phrase) in normalized or normalized in _normalize(phrase):
            return True
    return False


def _get_tagger() -> object | None:
    global _tagger, _tagger_failed
    if _tagger_failed:
        return None
    if _tagger is None:
        try:
            import fugashi

            _tagger = fugashi.Tagger()
        except Exception:
            logger.warning("fugashi/unidic-lite unavailable; ruby passthrough")
            _tagger_failed = True
            return None
    return _tagger


def _hiragana_reading(word: object) -> str | None:
    feature = getattr(word, "feature", None)
    kana = getattr(feature, "kana", None)
    if not kana or kana == "*":
        return None
    return _katakana_to_hiragana(kana)


def _katakana_to_hiragana(text: str) -> str:
    chars: list[str] = []
    for ch in text:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            chars.append(chr(code - 0x60))
        else:
            chars.append(ch)
    return "".join(chars)


def _token_ruby(surface: str, reading: str | None) -> str:
    escaped = html.escape(surface)
    if not surface or reading is None or _ASCII.match(surface):
        return escaped
    return f"<ruby>{escaped}<rt>{html.escape(reading)}</rt></ruby>"


def _normalize(s: str) -> str:
    return "".join(s.split()).lower()
