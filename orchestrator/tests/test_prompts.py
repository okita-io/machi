"""Prompt templates and strict tutor JSON."""

import asyncio
import json

import pytest
from pydantic import ValidationError

from machi.llm import LlmClient, TutorResponse, parse_tutor_payload, render_prompt

VALID = {
    "goal_hits": ["party_size"],
    "correction_en": None,
    "correction_ja": None,
    "coach_note_en": "Nice!",
    "hint_rung": 1,
    "sora_expression": "cheer",
}


def test_templates_fill_placeholders():
    system = render_prompt(
        "npc_system.md",
        {"npc_role": "ramen staff", "register": "polite_service"},
    )
    user = render_prompt(
        "npc_user.md",
        {"node_id": "greet", "utterance": "ふたりです", "scripted_line": "こちらへ"},
    )
    tutor = render_prompt(
        "tutor_user.md",
        {
            "utterance": "ふたりです",
            "goal_hits": "party_size",
            "expected_goals": "party_size",
            "hint_rung": 1,
            "accepted": "true",
            "expected_reading": "フタリデス accent 0 pitch L-H-H-H-H",
        },
    )
    assert "ramen staff" in system and "polite_service" in system
    assert "{{" not in system and "{{" not in user and "{{" not in tutor
    assert "ふたりです" in user and "ふたりです" in tutor
    assert "フタリデス" in tutor and "accent 0" in tutor
    assert render_prompt("coach_note_success.md", {}) == "Nice!"
    assert "key phrase" in render_prompt("coach_note_retry.md", {})
    heard = render_prompt("coach_note_warmup_miss.md", {"phrase_en": "Two people."})
    assert "Two people." in heard
    with pytest.raises(KeyError):
        render_prompt("npc_system.md", {})


def test_unknown_expression_is_rejected():
    bad = dict(VALID)
    bad["sora_expression"] = "wave"
    with pytest.raises(ValidationError):
        TutorResponse.model_validate(bad)
    bad_rung = dict(VALID)
    bad_rung["hint_rung"] = 5
    with pytest.raises(ValidationError):
        TutorResponse.model_validate(bad_rung)
    parsed, err = parse_tutor_payload(json.dumps(bad))
    assert parsed is None
    assert err and "sora_expression" in err


def test_malformed_json_repairs_once_then_falls_back():
    calls: list[list[dict[str, str]]] = []

    async def complete(messages, *, max_tokens, temperature, json_mode):
        del max_tokens, temperature, json_mode
        calls.append(messages)
        if len(calls) == 1:
            return "{not json"
        if len(calls) == 2:
            return json.dumps(VALID)
        return "still bad"

    async def scenario():
        client = LlmClient(complete=complete)
        repaired = await client.tutor_json(
            system="sora",
            user="Learner said: hi",
            fallback={"x": 1},
        )
        assert repaired["goal_hits"] == ["party_size"]
        assert repaired["sora_expression"] == "cheer"
        assert "Validation error:" in calls[1][1]["content"]
        assert "invalid JSON" in calls[1][1]["content"]

        calls.clear()

        async def always_bad(messages, *, max_tokens, temperature, json_mode):
            del max_tokens, temperature, json_mode
            calls.append(messages)
            return "nope"

        fallback = {"coach_note_en": "fallback"}
        client_bad = LlmClient(complete=always_bad)
        given = await client_bad.tutor_json(system="sora", user="again", fallback=fallback)
        assert given is fallback
        assert len(calls) == 2
        assert "Validation error:" in calls[1][1]["content"]

    asyncio.run(scenario())
