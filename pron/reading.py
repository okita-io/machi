"""Expected kana, accent type, and per-mora pitch from pyopenjtalk.

pyopenjtalk (MIT) plus the OpenJTalk dictionary (Modified BSD) is enough.
``g2p(..., kana=True)`` is the reading. ``extract_fullcontext`` labels carry
the accent type in ``/F:`` (F2) and the mora index in ``/A:`` (A2). Tokyo
pitch (low/high per mora) follows from those two numbers.

pyopenjtalk-plus is a community fork with extra dictionary helpers. This
task does not need them, and it does not need the optional ``marine``
accent model (``pip install pyopenjtalk[marine]``). Stock full-context
labels already expose the expected pattern, so the plus fork is not a
dependency.

OpenJTalk stores heiban (平板) as accent position == mora count. That is
reported here as accent type 0. A fall after the last mora (尾高) is not
distinct from heiban until a following particle is in the same phrase.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import Any

_LABEL = re.compile(
    r"^(?P<p1>[^^]+)\^(?P<p2>[^-]+)-(?P<p3>[^+]+)\+(?P<p4>[^=]+)=(?P<p5>[^/]+)"
    r"/A:(?P<a1>[^+]+)\+(?P<a2>[^+]+)\+(?P<a3>[^/]+)"
    r"/B:(?P<b1>[^-]+)-(?P<b2>[^_]+)_(?P<b3>[^/]+)"
    r"/C:(?P<c1>[^_]+)_(?P<c2>[^+]+)\+(?P<c3>[^/]+)"
    r"/D:(?P<d1>[^+]+)\+(?P<d2>[^_]+)_(?P<d3>[^/]+)"
    r"/E:(?P<e1>[^_]+)_(?P<e2>[^!]+)!(?P<e3>[^_]+)_(?P<e4>[^-]+)-(?P<e5>[^/]+)"
    r"/F:(?P<f1>[^_]+)_(?P<f2>[^#]+)#(?P<f3>[^_]+)_(?P<f4>[^@]+)"
    r"@(?P<f5>[^_]+)_(?P<f6>[^|]+)\|(?P<f7>[^_]+)_(?P<f8>[^/]+)"
)

_VOWELS = {"a": "ア", "i": "イ", "u": "ウ", "e": "エ", "o": "オ"}
_VOWEL_INDEX = {"a": 0, "i": 1, "u": 2, "e": 3, "o": 4}
_ROW = {
    "k": "カキクケコ",
    "g": "ガギグゲゴ",
    "s": "サシスセソ",
    "z": "ザジズゼゾ",
    "t": "タチツテト",
    "d": "ダヂヅデド",
    "n": "ナニヌネノ",
    "h": "ハヒフヘホ",
    "b": "バビブベボ",
    "p": "パピプペポ",
    "m": "マミムメモ",
    "r": "ラリルレロ",
}
_SPECIAL = {
    ("ky", "a"): "キャ",
    ("ky", "u"): "キュ",
    ("ky", "o"): "キョ",
    ("gy", "a"): "ギャ",
    ("gy", "u"): "ギュ",
    ("gy", "o"): "ギョ",
    ("sh", "a"): "シャ",
    ("sh", "i"): "シ",
    ("sh", "u"): "シュ",
    ("sh", "e"): "シェ",
    ("sh", "o"): "ショ",
    ("ch", "a"): "チャ",
    ("ch", "i"): "チ",
    ("ch", "u"): "チュ",
    ("ch", "e"): "チェ",
    ("ch", "o"): "チョ",
    ("ts", "a"): "ツァ",
    ("ts", "i"): "ツィ",
    ("ts", "u"): "ツ",
    ("ts", "e"): "ツェ",
    ("ts", "o"): "ツォ",
    ("j", "a"): "ジャ",
    ("j", "i"): "ジ",
    ("j", "u"): "ジュ",
    ("j", "e"): "ジェ",
    ("j", "o"): "ジョ",
    ("ny", "a"): "ニャ",
    ("ny", "u"): "ニュ",
    ("ny", "o"): "ニョ",
    ("hy", "a"): "ヒャ",
    ("hy", "u"): "ヒュ",
    ("hy", "o"): "ヒョ",
    ("by", "a"): "ビャ",
    ("by", "u"): "ビュ",
    ("by", "o"): "ビョ",
    ("py", "a"): "ピャ",
    ("py", "u"): "ピュ",
    ("py", "o"): "ピョ",
    ("my", "a"): "ミャ",
    ("my", "u"): "ミュ",
    ("my", "o"): "ミョ",
    ("ry", "a"): "リャ",
    ("ry", "u"): "リュ",
    ("ry", "o"): "リョ",
    ("f", "a"): "ファ",
    ("f", "i"): "フィ",
    ("f", "u"): "フ",
    ("f", "e"): "フェ",
    ("f", "o"): "フォ",
    ("w", "a"): "ワ",
    ("w", "i"): "ウィ",
    ("w", "e"): "ウェ",
    ("w", "o"): "ウォ",
    ("y", "a"): "ヤ",
    ("y", "u"): "ユ",
    ("y", "e"): "イェ",
    ("y", "o"): "ヨ",
    ("v", "a"): "ヴァ",
    ("v", "i"): "ヴィ",
    ("v", "u"): "ヴ",
    ("v", "e"): "ヴェ",
    ("v", "o"): "ヴォ",
}
_SMALL = set("ァィゥェォャュョヮ")

Reader = Callable[[str], dict[str, Any]]


def dictionary_ready() -> bool:
    """True when pyopenjtalk is importable and its dictionary directory exists."""
    try:
        import pyopenjtalk
    except ImportError:
        return False
    raw = pyopenjtalk.OPEN_JTALK_DICT_DIR
    if isinstance(raw, bytes):
        raw = raw.decode()
    return os.path.isdir(raw)


def openjtalk_reader(text: str) -> dict[str, Any]:
    """Full-context labels and katakana from stock pyopenjtalk."""
    import pyopenjtalk

    kana = pyopenjtalk.g2p(text, kana=True)
    if not isinstance(kana, str):
        kana = "".join(kana)
    labels = pyopenjtalk.extract_fullcontext(text)
    return {"kana": kana, "labels": list(labels)}


def expected_reading(text: str, *, reader: Reader | None = None) -> dict[str, Any]:
    """Mora reading, accent type, and H/L pitch for ``text``."""
    raw = (reader or openjtalk_reader)(text)
    labels = raw.get("labels") if isinstance(raw, dict) else None
    kana = raw.get("kana") if isinstance(raw, dict) else ""
    return build_reading(
        text,
        list(labels) if isinstance(labels, list) else [],
        kana if isinstance(kana, str) else "",
    )


def build_reading(text: str, labels: list[str], kana: str) -> dict[str, Any]:
    phrases = _phrases_from_labels(labels)
    flat = [mora for phrase in phrases for mora in phrase["moras"]]
    kana_moras = split_moras(kana)
    if kana_moras and len(kana_moras) == len(flat):
        for mora, name in zip(flat, kana_moras, strict=True):
            mora["mora"] = name
    reading = "".join(mora["mora"] for mora in flat)
    accents = [phrase["accent_type"] for phrase in phrases]
    if len(accents) == 1:
        accent_type: int | list[int] | None = accents[0]
    elif accents:
        accent_type = accents
    else:
        accent_type = None
    return {
        "text": text,
        "kana": kana.strip() or reading,
        "accent_type": accent_type,
        "pitch_pattern": [mora["pitch"] for mora in flat],
        "moras": flat,
        "accent_phrases": phrases,
    }


def split_moras(kana: str) -> list[str]:
    """Split katakana into moras. A small kana stays with the previous mora."""
    moras: list[str] = []
    buf = ""
    for char in kana:
        if char in _SMALL and buf:
            buf += char
            continue
        if buf:
            moras.append(buf)
        buf = char
    if buf:
        moras.append(buf)
    return moras


def mora_kana(phonemes: list[str]) -> str:
    if phonemes == ["N"]:
        return "ン"
    if phonemes == ["cl"]:
        return "ッ"
    if len(phonemes) == 1 and phonemes[0] in _VOWELS:
        return _VOWELS[phonemes[0]]
    if len(phonemes) == 2:
        consonant, vowel = phonemes
        special = _SPECIAL.get((consonant, vowel))
        if special:
            return special
        row = _ROW.get(consonant)
        index = _VOWEL_INDEX.get(vowel)
        if row is not None and index is not None:
            return row[index]
    return "".join(phonemes)


def _pitch(position: int, accent_type: int, mora_count: int) -> str:
    """Tokyo H/L. Type 0 is heiban. Position is 1-indexed inside the phrase."""
    if accent_type == 0:
        return "H" if mora_count == 1 or position > 1 else "L"
    if position == 1:
        return "H" if accent_type == 1 else "L"
    if position <= accent_type:
        return "H"
    return "L"


def _parse_label(label: str) -> dict[str, str] | None:
    match = _LABEL.search(label.strip())
    if match is None:
        return None
    return match.groupdict()


def _phrases_from_labels(labels: list[str]) -> list[dict[str, Any]]:
    phrases: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    phonemes: list[str] = []
    meta: dict[str, Any] | None = None
    last_pos: int | None = None

    def flush_mora() -> None:
        nonlocal phonemes, meta
        if meta is None:
            phonemes = []
            return
        current.append(
            {
                "mora": mora_kana(phonemes),
                "pitch": meta["pitch"],
                "position": meta["pos"],
                "phonemes": list(phonemes),
                "accent_type": meta["accent_type"],
            }
        )
        phonemes = []
        meta = None

    def flush_phrase() -> None:
        nonlocal current, last_pos
        flush_mora()
        if current:
            phrases.append(
                {
                    "accent_type": current[0]["accent_type"],
                    "moras": [
                        {
                            "mora": item["mora"],
                            "pitch": item["pitch"],
                            "position": item["position"],
                            "phonemes": item["phonemes"],
                        }
                        for item in current
                    ],
                }
            )
        current = []
        last_pos = None

    for label in labels:
        parsed = _parse_label(label)
        if parsed is None:
            continue
        if parsed["p3"] in {"sil", "pau"} or parsed["a2"] == "xx" or parsed["f1"] == "xx":
            flush_phrase()
            continue
        pos = int(parsed["a2"])
        if last_pos is not None and pos < last_pos:
            flush_phrase()
        if meta is not None and pos != meta["pos"]:
            flush_mora()
        mora_count = int(parsed["f1"])
        accent_raw = int(parsed["f2"])
        accent_type = 0 if accent_raw == mora_count else accent_raw
        if meta is None:
            meta = {
                "pos": pos,
                "pitch": _pitch(pos, accent_type, mora_count),
                "accent_type": accent_type,
            }
        phonemes.append(parsed["p3"])
        last_pos = pos
    flush_phrase()
    return phrases
