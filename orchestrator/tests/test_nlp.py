"""Furigana (fugashi + unidic-lite) and romaji (cutlet) for arbitrary Japanese."""

from __future__ import annotations

import re

import pytest

from machi import nlp
from machi.nlp import build_ruby_html, ruby_for_text, to_romaji

_KANJI = re.compile(r"[\u4e00-\u9fff]")
MISO_KANA = "みそラーメンをひとつください"
MISO_KANJI = "味噌ラーメンを一つください"


def test_ruby_for_futari_desu() -> None:
    html = ruby_for_text("ふたりです")
    assert "<ruby>ふたり<rt>ふたり</rt></ruby>" in html
    assert "<ruby>です<rt>です</rt></ruby>" in html


def test_ruby_for_kana_sentence_readings() -> None:
    html = ruby_for_text(MISO_KANA)
    assert "<rt>みそ</rt>" in html
    assert "<rt>らーめん</rt>" in html
    assert "<rt>を</rt>" in html
    assert "<rt>ひと</rt>" in html
    assert "<rt>つ</rt>" in html
    assert "<rt>ください</rt>" in html


def test_ruby_for_kanji_sentence_readings() -> None:
    html = ruby_for_text(MISO_KANJI)
    assert "<ruby>味噌<rt>みそ</rt></ruby>" in html
    assert "<ruby>一<rt>ひと</rt></ruby>" in html
    assert "<rt>ください</rt>" in html


def test_ruby_mixed_ascii_stays_readable() -> None:
    html = ruby_for_text("OK ふたりです 123")
    assert html.startswith("OK ")
    assert html.endswith(" 123")
    assert "<ruby>OK" not in html
    assert "<ruby>123" not in html
    assert "<rt>ふたり</rt>" in html
    assert "<rt>です</rt>" in html


def test_npc_kana_is_optional_whole_line_override() -> None:
    override = build_ruby_html("何名様ですか", "なんめいさまですか")
    assert override == "<ruby>何名様ですか<rt>なんめいさまですか</rt></ruby>"
    tokenized = build_ruby_html("お席", None)
    assert "<ruby>席<rt>せき</rt></ruby>" in tokenized
    assert "なんめい" not in tokenized


def test_romaji_of_kanji_is_romanized() -> None:
    romaji = to_romaji(MISO_KANJI)
    assert romaji != MISO_KANJI
    assert _KANJI.search(romaji) is None
    assert "miso" in romaji.lower()
    assert "kudasai" in romaji.lower()
    assert "ラーメン" not in romaji


def test_romaji_of_kana_and_learner_line() -> None:
    assert "futari" in to_romaji("ふたりです").lower()
    assert "desu" in to_romaji("ふたりです").lower()


def test_romaji_and_ruby_passthrough_when_libraries_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(nlp, "_katsu", None)
    monkeypatch.setattr(nlp, "_katsu_failed", False)
    monkeypatch.setattr(nlp, "_tagger", None)
    monkeypatch.setattr(nlp, "_tagger_failed", False)

    real_import = __import__

    def _block(name: str, *args: object, **kwargs: object):
        if name in {"cutlet", "fugashi"}:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _block)
    assert to_romaji(MISO_KANJI) == MISO_KANJI
    assert ruby_for_text("ふたりです") == "ふたりです"
    assert "<" not in ruby_for_text("a<b>")
