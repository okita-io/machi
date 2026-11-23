"""Compare a transcript with the phrase the learner was trying to say.

The coach names the words speech recognition produced instead of the target
words, then tells the learner how to pronounce the intended phrase.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from machi.nlp import to_romaji, tokenize_words

_KANJI = re.compile(r"[一-龯]")
_JAPANESE = re.compile(r"[ぁ-んァ-ン一-龯]")


def choose_intended(
    accept: list[str],
    *,
    tip: str = "",
) -> dict[str, str] | None:
    """Pick the written line and the kana reading from a goal's accept list.

    The first Japanese accept is the line. A kanji accept with the same reading
    becomes the written form, and the kana accept with that reading is how to
    say it.
    """
    japanese = [item.strip() for item in accept if item and item.strip() and _JAPANESE.search(item)]
    if not japanese:
        return None
    primary = japanese[0]
    primary_key = _reading_key(primary)
    written = primary
    for candidate in japanese:
        if _KANJI.search(candidate) and _reading_key(candidate) == primary_key:
            written = candidate
            break
    written_key = _reading_key(written)
    spoken = ""
    for candidate in japanese:
        if not _KANJI.search(candidate) and _reading_key(candidate) == written_key:
            spoken = candidate
            break
    if not spoken:
        spoken = "".join(reading for _, reading in tokenize_words(written))
    return {
        "ja": written,
        "kana": spoken,
        "romaji": to_romaji(written),
        "en": "",
        "tip": tip.strip(),
    }


def build_interpretation(
    heard: str,
    intended: dict[str, str] | None,
    *,
    asr_ms: float | None = None,
    audio_ms: int | None = None,
) -> dict[str, Any]:
    """Word diff plus a pronunciation line for one spoken attempt."""
    heard_text = (heard or "").strip()
    target = intended or {}
    ja = str(target.get("ja") or "")
    kana = str(target.get("kana") or "")
    romaji = str(target.get("romaji") or "")
    meaning = str(target.get("en") or "")
    tip = str(target.get("tip") or "")
    if ja and not romaji:
        romaji = to_romaji(ja)

    heard_words = tokenize_words(heard_text)
    target_text = ja or kana
    target_words = tokenize_words(target_text) if target_text else []
    matched = bool(target_text) and _same_phrase(heard_text, ja, kana)
    swaps: list[tuple[str, str]] = []
    extras: list[str] = []
    missing: list[str] = []
    if heard_words and target_words and not matched:
        swaps, extras, missing = _diff_words(heard_words, target_words)

    interpreted = _interpreted_sentence(
        heard_words,
        target_words,
        swaps,
        extras,
        missing,
        matched=matched,
        asr_ms=asr_ms,
        audio_ms=audio_ms,
    )
    pronounce = _pronounce_sentence(ja, kana, romaji, meaning, tip) if target_text else ""
    detail = " ".join(part for part in (interpreted, pronounce) if part)
    spoken_heard, spoken_pronounce = spoken_lines(interpreted, pronounce, matched=matched)
    return {
        "heard": heard_text,
        "intended_ja": ja,
        "intended_kana": kana or "".join(reading for _, reading in target_words),
        "intended_romaji": romaji,
        "intended_en": meaning,
        "instead": [{"heard": left, "intended": right} for left, right in swaps],
        "missing": missing,
        "extra": extras,
        "interpreted": interpreted,
        "pronounce": pronounce,
        "spoken_interpreted": spoken_heard,
        "spoken_pronounce": spoken_pronounce,
        "detail": detail,
        "matched": matched,
    }


def spoken_parts(info: dict[str, Any] | None) -> tuple[str, str]:
    """The two clips Sora says: what was heard, then how to say the phrase."""
    if not info:
        return "", ""
    heard = str(info.get("spoken_interpreted") or info.get("interpreted") or "").strip()
    pronounce = str(info.get("spoken_pronounce") or "").strip()
    if pronounce or "spoken_pronounce" in info:
        return heard, pronounce
    return spoken_lines(
        str(info.get("interpreted") or ""),
        str(info.get("pronounce") or ""),
        matched=bool(info.get("matched")),
    )


def spoken_lines(interpreted: str, pronounce: str, *, matched: bool) -> tuple[str, str]:
    """Keep the correction in its own sentence, announced when the phrase was missed."""
    heard = interpreted.strip()
    line = pronounce.strip()
    if not line:
        return heard, ""
    if matched:
        return heard, line
    return heard, f"Correction. {line}"


def stamp_coach(coach: dict[str, Any], info: dict[str, Any]) -> None:
    """Make Sora's note the word diff and the pronunciation of the target line."""
    coach["coach_note_en"] = str(info.get("detail") or "")
    coach["pronunciation_tip_en"] = str(info.get("pronounce") or "")
    if info.get("matched"):
        coach["correction"] = None
        coach["correction_en"] = None
        coach["correction_ja"] = None
        coach["sora_expression"] = "cheer"
        coach["sentiment"] = "success"
        coach["coach_note_sentiment"] = "success"
        return
    intended_ja = str(info.get("intended_ja") or "")
    if intended_ja:
        coach["correction_ja"] = intended_ja
        coach["correction"] = intended_ja
    coach["sora_expression"] = "point"


def _reading_key(text: str) -> str:
    return "".join(reading for _, reading in tokenize_words(text))


def _same_phrase(heard: str, ja: str, kana: str) -> bool:
    heard_key = _reading_key(heard)
    if not heard_key:
        return False
    targets = {_reading_key(ja), _reading_key(kana)}
    targets.discard("")
    return heard_key in targets


def _label(surface: str, reading: str) -> str:
    if reading and reading != surface:
        return f"{surface}（{reading}）"
    return surface or reading


def _diff_words(
    heard: list[tuple[str, str]],
    target: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    heard_keys = [reading for _, reading in heard]
    target_keys = [reading for _, reading in target]
    swaps: list[tuple[str, str]] = []
    extras: list[str] = []
    missing: list[str] = []
    matcher = SequenceMatcher(a=heard_keys, b=target_keys, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        heard_slice = heard[i1:i2]
        target_slice = target[j1:j2]
        if tag == "replace":
            paired = min(len(heard_slice), len(target_slice))
            for index in range(paired):
                swaps.append((_label(*heard_slice[index]), _label(*target_slice[index])))
            extras.extend(_label(*word) for word in heard_slice[paired:])
            missing.extend(_label(*word) for word in target_slice[paired:])
        elif tag == "delete":
            extras.extend(_label(*word) for word in heard_slice)
        elif tag == "insert":
            missing.extend(_label(*word) for word in target_slice)
    return swaps, extras, missing


def _interpreted_sentence(
    heard_words: list[tuple[str, str]],
    target_words: list[tuple[str, str]],
    swaps: list[tuple[str, str]],
    extras: list[str],
    missing: list[str],
    *,
    matched: bool,
    asr_ms: float | None = None,
    audio_ms: int | None = None,
) -> str:
    if not heard_words:
        return _empty_recognition(audio_ms, asr_ms)
    if matched:
        shown = target_words or heard_words
        labels = "」「".join(_label(surface, reading) for surface, reading in shown)
        return f"Heard 「{labels}」, the words in the phrase."
    parts: list[str] = []
    if swaps:
        bits = [f"「{left}」 instead of 「{right}」" for left, right in swaps]
        if len(bits) == 1:
            parts.append(f"Heard {bits[0]}.")
        else:
            parts.append("Heard " + ", and ".join(bits) + ".")
    if extras:
        parts.append(
            "Also heard 「" + "」「".join(extras) + "」, which is not in the phrase."
        )
    if missing:
        parts.append("Missing 「" + "」「".join(missing) + "」.")
    if parts:
        return " ".join(parts)
    labels = "」「".join(_label(surface, reading) for surface, reading in heard_words)
    return f"Heard 「{labels}」."


def _empty_recognition(audio_ms: int | None, asr_ms: float | None) -> str:
    """Say how long recognition ran before reporting that it found no words."""
    if audio_ms and asr_ms is not None and asr_ms >= 0:
        return (
            f"Speech recognition spent {asr_ms / 1000:.2f} s on "
            f"{audio_ms / 1000:.1f} s of audio. No words were recognized."
        )
    return "No words were recognized."


def _pronounce_sentence(ja: str, kana: str, romaji: str, meaning: str, tip: str) -> str:
    spoken = kana or ja
    if ja and spoken and spoken != ja:
        line = f"Say {ja}. Pronounce it {spoken}"
    else:
        line = f"Say {ja or spoken}"
    if romaji:
        line += f" ({romaji})"
    line += "."
    gloss = meaning.strip().rstrip(".")
    if gloss:
        line += f" It means {gloss}."
    if tip.strip():
        line += f" {tip.strip()}"
    return line
