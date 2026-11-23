"""Word-level coaching: what was heard instead, then the intended pronunciation."""

from machi.interpret import build_interpretation, choose_intended

PHRASE = {
    "ja": "二人です",
    "kana": "ふたりです",
    "romaji": "futari desu",
    "en": "Two people.",
    "tip": "",
}


def test_matching_reading_lists_the_phrase_words():
    info = build_interpretation("ふたりです", PHRASE)
    assert info["matched"] is True
    assert info["instead"] == []
    assert "ふたり" in info["interpreted"]
    assert "instead of" not in info["interpreted"]
    assert "二人です" in info["pronounce"]
    assert "ふたりです" in info["pronounce"]
    assert "futari desu" in info["pronounce"]
    assert "Two people" in info["pronounce"]
    assert not info["spoken_pronounce"].startswith("Correction.")
    assert info["spoken_interpreted"].startswith("Heard")


def test_digit_counter_matches_the_same_phrase():
    info = build_interpretation("2人です", PHRASE)
    assert info["matched"] is True
    assert info["instead"] == []


def test_wrong_word_is_named_instead_of_the_target():
    info = build_interpretation("ひとりです", PHRASE)
    assert info["matched"] is False
    assert info["instead"]
    heard = info["instead"][0]["heard"]
    intended = info["instead"][0]["intended"]
    assert "ひとり" in heard
    assert "ふたり" in intended
    assert "instead of" in info["interpreted"]
    assert "Pronounce it ふたりです" in info["pronounce"]
    assert info["spoken_pronounce"].startswith("Correction.")
    assert "Correction." not in info["interpreted"]
    assert "Correction." not in info["pronounce"]


def test_silence_asks_for_the_intended_phrase():
    info = build_interpretation("", PHRASE)
    assert info["matched"] is False
    assert info["interpreted"] == "No words were recognized."
    assert "Say 二人です" in info["pronounce"]


def test_empty_result_names_how_long_recognition_ran():
    info = build_interpretation("", PHRASE, asr_ms=420.0, audio_ms=1560)
    assert "0.42 s" in info["interpreted"]
    assert "1.6 s of audio" in info["interpreted"]
    assert info["interpreted"].endswith("No words were recognized.")


def test_goal_accept_list_picks_kanji_and_kana():
    chosen = choose_intended(
        ["ふたりです", "二人です", "ふたり", "2人お願いします"],
    )
    assert chosen is not None
    assert chosen["ja"] == "二人です"
    assert chosen["kana"] == "ふたりです"
