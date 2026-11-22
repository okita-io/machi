"""Beginner-phrase WAVs in tests/fixtures/asr/.

The files are checked in. Posting them to a live ASR is marked ``accent`` and
runs only when ``ASR_URL`` answers ``/health``. Word error rate is the token
edit distance on cutlet romaji, so kanji and kana of the same phrase agree.
Mean WER must be <= 0.35. The CPU mock returns 「ふたりです」 for every clip and
fails that bar; point ASR_URL at a real engine.
"""

from __future__ import annotations

import base64
import json
import os
import unicodedata
import wave
from pathlib import Path

import httpx
import pytest

from machi.nlp import to_romaji
from machi.scenario_loader import load_scenario

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "asr"
EXPECTED_PATH = FIXTURE_DIR / "expected.json"
SCENARIO = ROOT / "scenarios" / "restaurant_ramen_01.yaml"
# Mean romaji-token WER. Above this, the accent run fails.
WER_THRESHOLD = 0.35
_PUNCT = "、。！？!?.,「」『』（）()・"


def _expected() -> dict[str, str]:
    data = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return {str(name): str(text) for name, text in data.items()}


def _tokens(text: str) -> list[str]:
    cleaned = unicodedata.normalize("NFKC", text)
    for char in _PUNCT:
        cleaned = cleaned.replace(char, " ")
    romaji = to_romaji(cleaned).lower()
    return [tok for tok in romaji.split() if tok]


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate on romaji tokens. 0 is an exact reading."""
    ref = _tokens(reference)
    hyp = _tokens(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return _edit_distance(ref, hyp) / len(ref)


def _edit_distance(left: list[str], right: list[str]) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, token in enumerate(left, start=1):
        current = [i]
        for j, other in enumerate(right, start=1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            substitute = previous[j - 1] + (token != other)
            current.append(min(insert, delete, substitute))
        previous = current
    return previous[-1]


def _scenario_phrases() -> set[str]:
    spec = load_scenario(SCENARIO)
    phrases: set[str] = set()
    for goal in spec.goals:
        phrases.update(goal.accept)
    for phrase in spec.key_phrases:
        phrases.add(phrase.ja)
        phrases.add(phrase.kana)
    return phrases


def test_accent_fixtures_are_scenario_phrases_and_pcm16():
    expected = _expected()
    assert 5 <= len(expected) <= 8
    allowed = _scenario_phrases()
    for name, text in expected.items():
        assert text in allowed, f"{name} text {text!r} is not a ramen accept/key phrase"
        path = FIXTURE_DIR / name
        assert path.is_file(), name
        assert path.stat().st_size < 100 * 1024
        with wave.open(str(path), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            assert wf.getnframes() > 0


def test_romaji_wer_matches_kana_and_kanji_party_size():
    assert wer("ふたりです", "二人です") == 0.0
    assert wer("ふたりです", "お水をください") > 0.5


def _asr_url() -> str | None:
    url = os.environ.get("ASR_URL", "").strip().rstrip("/")
    if not url:
        return None
    try:
        response = httpx.get(f"{url}/health", timeout=2.0)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    return url


@pytest.mark.accent
def test_beginner_phrases_meet_wer_threshold():
    """POST each WAV to ``{ASR_URL}/v1/transcribe`` and score romaji WER."""
    url = _asr_url()
    if url is None:
        pytest.skip("ASR_URL is not set or the ASR /health endpoint is unreachable")
    lines: list[str] = []
    scores: list[float] = []
    with httpx.Client(timeout=60.0) as client:
        for name, reference in _expected().items():
            wav = (FIXTURE_DIR / name).read_bytes()
            response = client.post(
                f"{url}/v1/transcribe",
                json={"audio_b64": base64.b64encode(wav).decode("ascii")},
            )
            assert response.status_code == 200, f"{name}: {response.status_code} {response.text}"
            hypothesis = response.json().get("text") or ""
            score = wer(reference, str(hypothesis))
            scores.append(score)
            lines.append(f"{name}: wer={score:.3f} hyp={hypothesis!r} ref={reference!r}")
    mean = sum(scores) / len(scores)
    report = "\n".join(lines)
    assert mean <= WER_THRESHOLD, (
        f"mean romaji WER {mean:.3f} exceeds {WER_THRESHOLD:.2f}\n{report}"
    )
