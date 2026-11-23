"""Text enrichment: romaji via cutlet; per-token furigana via fugashi + unidic-lite.

Both libraries are default dependencies (MIT / unidic-lite). If an import fails,
readings fall back to the original text so a CPU checkout without the wheels
still serves a turn.
"""

from __future__ import annotations

import html
import logging
import re
import unicodedata

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


def match_strength(utterance: str, accept: list[str]) -> str:
    """FSRS grade from a spoken line: ``good``, ``hard`` (a fragment), or ``again``.

    Saying the whole accept phrase, plus extra words, is ``good``. A shorter
    piece of that phrase is ``hard``. Unrelated text is ``again``.
    """
    normalized = _normalize(utterance)
    if not normalized:
        return "again"
    partial = False
    for phrase in accept:
        target = _normalize(phrase)
        if len(target) < 2:
            continue
        if normalized == target or target in normalized:
            return "good"
        if len(normalized) >= 2 and normalized in target:
            partial = True
            continue
        span = _longest_common_substring(normalized, target)
        if span >= 2 and span / len(target) >= 0.4:
            partial = True
    return "hard" if partial else "again"


def _longest_common_substring(left: str, right: str) -> int:
    if not left or not right:
        return 0
    best = 0
    prev = [0] * (len(right) + 1)
    for char in left:
        current = [0] * (len(right) + 1)
        for index, other in enumerate(right, start=1):
            if char == other:
                current[index] = prev[index - 1] + 1
                if current[index] > best:
                    best = current[index]
        prev = current
    return best


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


_PUNCT = re.compile(r"[、。！？!?.,「」『』（）()・\s]+")


def fold_spoken(text: str) -> str:
    """NFKC plus the counter forms ASR writes as digits (``2人`` → ``二人``)."""
    folded = unicodedata.normalize("NFKC", text or "")
    folded = re.sub(r"(?<![0-9])2人", "二人", folded)
    folded = re.sub(r"(?<![0-9])1人", "一人", folded)
    folded = re.sub(r"(?<![0-9])1つ", "一つ", folded)
    return folded.strip()


def tokenize_words(text: str) -> list[tuple[str, str]]:
    """Content words as ``(surface, hiragana)``. Punctuation is dropped.

    Without fugashi the whole line is one word, so coaching still has a phrase
    to compare.
    """
    folded = fold_spoken(text)
    if not folded:
        return []
    tagger = _get_tagger()
    if tagger is None:
        cleaned = _PUNCT.sub("", folded)
        return [(cleaned, cleaned)] if cleaned else []
    words: list[tuple[str, str]] = []
    for word in tagger(folded):  # type: ignore[operator]
        surface = str(getattr(word, "surface", "") or "")
        if not surface or _PUNCT.fullmatch(surface):
            continue
        reading = _hiragana_reading(word) or surface
        words.append((surface, reading))
    return words


def _normalize(s: str) -> str:
    """Compare form: folded counters, no punctuation."""
    return _PUNCT.sub("", fold_spoken(s)).lower()
