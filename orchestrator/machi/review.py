"""Two-minute spoken review sessions over the FSRS deck.

A session takes up to eight due cards and a soft two-minute budget. Sora's
prompt comes from ``prompts/review_situation_<tag>.md``, chosen from the
cards' ``srs_tags``. Grading is fuzzy against the phrase unless the client
sends ``self_rating``. Ratings go through the same FSRS scheduler as
``POST /reviews``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from machi.db import get_review_card, save_card_review
from machi.fsrs import FsrsState, format_dt, parse_dt, schedule
from machi.llm import PROMPTS_DIR, render_prompt
from machi.nlp import match_strength

REVIEW_CARD_LIMIT = 8
REVIEW_BUDGET_S = 120

# First matching tag with a template wins. Shared tags are listed early so a
# restaurant miss opens an ordering scene that also fits konbini and taxi.
_TAG_PRIORITY = (
    "ordering",
    "counters",
    "payment",
    "station",
    "polite_requests",
    "shopping",
    "transport",
    "directions",
    "laundry",
    "tickets",
    "restaurant",
    "konbini",
    "taxi",
    "train",
    "town",
)


@dataclass
class ReviewItem:
    card_id: int
    ja: str
    en: str
    romaji: str
    ruby_html: str
    tags: list[str]
    utterance: str = ""
    match: str = ""
    rating: str = ""
    due_at: str = ""
    reps: int = 0


@dataclass
class ReviewSession:
    id: str
    items: list[ReviewItem]
    started_at: datetime
    situation_tag: str
    budget_s: int = REVIEW_BUDGET_S
    index: int = 0
    complete: bool = False
    reviewed: list[ReviewItem] = field(default_factory=list)


def over_budget(started: datetime, now: datetime, budget_s: int) -> bool:
    """True once the soft clock has run out. The current card is still graded."""
    return (now - started).total_seconds() >= budget_s


def situation_tag_for(cards: list[dict[str, Any]]) -> str:
    """Pick one tag that has a mini-situation template."""
    seen: list[str] = []
    for card in cards:
        for tag in card.get("srs_tags") or []:
            if tag and tag not in seen:
                seen.append(tag)
    for tag in _TAG_PRIORITY:
        if tag in seen and _template_name(tag) != "review_situation_default.md":
            return tag
    for tag in seen:
        if _template_name(tag) != "review_situation_default.md":
            return tag
    return "default"


def render_situation(tag: str, item: ReviewItem | None) -> str:
    phrase = item or ReviewItem(card_id=0, ja="", en="", romaji="", ruby_html="", tags=[])
    return render_prompt(
        _template_name(tag),
        {
            "phrase_ja": phrase.ja,
            "phrase_en": phrase.en,
            "phrase_romaji": phrase.romaji,
        },
    )


def new_review_session(cards: list[dict[str, Any]], *, now: datetime) -> ReviewSession:
    chosen = cards[:REVIEW_CARD_LIMIT]
    items = [_item_from_card(card) for card in chosen]
    tag = situation_tag_for(chosen) if items else "default"
    return ReviewSession(
        id=str(uuid.uuid4()),
        items=items,
        started_at=now,
        situation_tag=tag,
        complete=not items,
    )


def accept_phrases(item: ReviewItem) -> list[str]:
    return [part for part in (item.ja, item.romaji, item.en) if part]


def grade_match(utterance: str, item: ReviewItem, self_rating: str | None) -> tuple[str, str]:
    """Return ``(match, rating)``. ``self_rating`` replaces the fuzzy grade."""
    match = match_strength(utterance, accept_phrases(item))
    rating = self_rating or match
    return match, rating


def record_grade(
    session: ReviewSession,
    *,
    utterance: str,
    match: str,
    rating: str,
    card: dict[str, Any],
    now: datetime,
) -> None:
    """Store one answer and close the session on the last card or the soft clock."""
    if session.complete or session.index >= len(session.items):
        session.complete = True
        return
    item = session.items[session.index]
    item.utterance = utterance
    item.match = match
    item.rating = rating
    item.due_at = str(card.get("due_at") or "")
    item.reps = int(card.get("reps") or 0)
    session.reviewed.append(item)
    session.index += 1
    finished = session.index >= len(session.items)
    if finished or over_budget(session.started_at, now, session.budget_s):
        session.complete = True


def review_payload(session: ReviewSession) -> dict[str, Any]:
    current: ReviewItem | None = None
    if not session.complete and session.index < len(session.items):
        current = session.items[session.index]
    last = session.reviewed[-1] if session.reviewed else None
    if session.complete and not session.items:
        situation = "Nothing is due. Sora will catch you next time."
    elif session.complete:
        situation = "That's the set. Sora will bring these back when they're due."
    else:
        situation = render_situation(session.situation_tag, current)
    summary = None
    if session.complete:
        summary = {
            "cards_reviewed": len(session.reviewed),
            "next_due": [
                {
                    "card_id": item.card_id,
                    "due_at": item.due_at,
                    "rating": item.rating,
                    "phrase_ja": item.ja,
                    "reps": item.reps,
                }
                for item in session.reviewed
            ],
        }
    return {
        "review_id": session.id,
        "budget_s": session.budget_s,
        "index": session.index,
        "card_total": len(session.items),
        "complete": session.complete,
        "situation": situation,
        "situation_tag": session.situation_tag,
        "card": _card_json(current) if current is not None else None,
        "last": _last_json(last) if last is not None else None,
        "summary": summary,
    }


def rate_card(path: Path, card_id: int, rating: str, now: datetime) -> dict[str, Any]:
    """Apply one FSRS rating. Raises ``LookupError`` when the card is missing."""
    row = get_review_card(path, card_id)
    if row is None:
        raise LookupError(card_id)
    reviewed = schedule(
        FsrsState(
            state=str(row["state"]),
            stability=row["stability"],
            difficulty=row["difficulty"],
            reps=int(row["reps"] or 0),
            lapses=int(row["lapses"] or 0),
            last_review_at=parse_dt(row["last_review_at"]),
        ),
        rating,
        now,
    )
    due_at = reviewed.due_at
    stability = reviewed.stability
    difficulty = reviewed.difficulty
    reviewed_at = reviewed.last_review_at
    last_rating = reviewed.last_rating
    if (
        due_at is None
        or stability is None
        or difficulty is None
        or reviewed_at is None
        or last_rating is None
    ):
        raise RuntimeError("review_failed")
    save_card_review(
        path,
        card_id,
        state=reviewed.state,
        due_at=format_dt(due_at),
        stability=stability,
        difficulty=difficulty,
        reps=reviewed.reps,
        lapses=reviewed.lapses,
        last_rating=last_rating,
        last_review_at=format_dt(reviewed_at),
    )
    updated = get_review_card(path, card_id)
    if updated is None:
        raise LookupError(card_id)
    updated["interval_days"] = reviewed.interval_days
    return updated


def _template_name(tag: str) -> str:
    name = f"review_situation_{tag}.md"
    if tag and (PROMPTS_DIR / name).is_file():
        return name
    return "review_situation_default.md"


def _item_from_card(card: dict[str, Any]) -> ReviewItem:
    return ReviewItem(
        card_id=int(card["card_id"]),
        ja=str(card.get("correction_ja") or ""),
        en=str(card.get("correction_en") or ""),
        romaji=str(card.get("romaji") or ""),
        ruby_html=str(card.get("kana_ruby") or ""),
        tags=list(card.get("srs_tags") or []),
    )


def _card_json(item: ReviewItem) -> dict[str, Any]:
    return {
        "card_id": item.card_id,
        "ja": item.ja,
        "en": item.en,
        "romaji": item.romaji,
        "kana_ruby": item.ruby_html,
        "srs_tags": list(item.tags),
    }


def _last_json(item: ReviewItem) -> dict[str, Any]:
    return {
        "card_id": item.card_id,
        "utterance": item.utterance,
        "match": item.match,
        "rating": item.rating,
        "phrase_ja": item.ja,
        "reps": item.reps,
        "due_at": item.due_at,
    }
