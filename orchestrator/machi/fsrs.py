"""FSRS-4.5 scheduler (stdlib only).

The algorithm and the default 19 weights are FSRS-4.5 as published by
open-spaced-repetition. Weights are pinned from the MIT-licensed py-fsrs and
fsrs4py defaults (https://github.com/open-spaced-repetition/py-fsrs) so Machi
does not import those packages. Copyright for the published weights and
algorithm belongs to the open-spaced-repetition contributors, used here under
the MIT license. This file reimplements the scheduler with ``math`` only.

Steps, in the published order:

* initial stability ``S0 = w[G-1]`` for the first rating G (again=1 … easy=4)
* initial difficulty, then linear damping and mean reversion toward Easy
* retrievability ``R = (1 + FACTOR * t / S) ** DECAY`` with decay -0.5
* next stability from the recall formula, the forget formula, or the same-day
  short-term term ``w[17]``, ``w[18]`` when the last review was under a day ago
* interval from stability at desired retention 0.9, rounded, at least one day

No interval fuzzing, so a fixed rating sequence is deterministic. A new card
rated Good or Easy moves to ``review``. Again or Hard on a new card stays
``learning`` (1 minute / 10 minutes). Again on a review card lapses to
``learning``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# MIT py-fsrs / fsrs4py FSRS-4.5 defaults. Do not retune without a spec change.
DEFAULT_WEIGHTS: tuple[float, ...] = (
    0.40255,
    1.18385,
    3.173,
    15.69105,
    7.1949,
    0.5345,
    1.4604,
    0.0046,
    1.54575,
    0.1192,
    1.01925,
    1.9395,
    0.11,
    0.29605,
    2.2698,
    0.2315,
    2.9898,
    0.51655,
    0.6621,
)

DECAY = -0.5
FACTOR = 19.0 / 81.0
DESIRED_RETENTION = 0.9
MAXIMUM_INTERVAL_DAYS = 36500
S_MIN = 0.1
D_MIN = 1.0
D_MAX = 10.0
AGAIN_MINUTES = 1
HARD_MINUTES = 10

RATINGS: dict[str, int] = {"again": 1, "hard": 2, "good": 3, "easy": 4}


@dataclass
class FsrsState:
    """One card's scheduling memory. ``new`` cards leave stability empty."""

    state: str = "new"
    stability: float | None = None
    difficulty: float | None = None
    reps: int = 0
    lapses: int = 0
    last_review_at: datetime | None = None
    due_at: datetime | None = None
    last_rating: str | None = None
    interval_days: int = 0


def schedule(
    card: FsrsState,
    rating: str,
    now: datetime,
    *,
    weights: tuple[float, ...] = DEFAULT_WEIGHTS,
    desired_retention: float = DESIRED_RETENTION,
) -> FsrsState:
    """Return the next card state. ``card`` is not mutated."""
    grade = RATINGS.get(rating)
    if grade is None:
        raise ValueError(f"unknown rating: {rating}")
    if len(weights) != 19:
        raise ValueError("FSRS-4.5 needs 19 weights")
    reviewed_at = _as_utc(now)
    first = card.state == "new" or card.reps <= 0 or card.stability is None
    if first:
        stability = _init_stability(weights, grade)
        difficulty = _init_difficulty(weights, grade)
        lapses = card.lapses + (1 if grade == 1 else 0)
    else:
        previous = card.stability if card.stability is not None else S_MIN
        elapsed = _elapsed_days(reviewed_at, card.last_review_at)
        base_difficulty = card.difficulty
        if base_difficulty is None:
            base_difficulty = _init_difficulty(weights, grade)
        difficulty = _next_difficulty(weights, base_difficulty, grade)
        if elapsed < 1.0:
            stability = _short_term_stability(weights, previous, grade)
        elif grade == 1:
            recall = _retrievability(elapsed, previous)
            stability = _forget_stability(weights, difficulty, previous, recall)
        else:
            recall = _retrievability(elapsed, previous)
            stability = _recall_stability(weights, difficulty, previous, recall, grade)
        lapses = card.lapses + (1 if grade == 1 else 0)
    stability = max(stability, S_MIN)
    state, due_at, interval_days = _next_due(
        card.state if not first else "new",
        grade,
        stability,
        reviewed_at,
        desired_retention,
    )
    return FsrsState(
        state=state,
        stability=stability,
        difficulty=difficulty,
        reps=card.reps + 1,
        lapses=lapses,
        last_review_at=reviewed_at,
        due_at=due_at,
        last_rating=rating,
        interval_days=interval_days,
    )


def format_dt(value: datetime) -> str:
    """UTC timestamp. Lexicographic order matches time order."""
    return _as_utc(value).replace(microsecond=0).isoformat()


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return _as_utc(datetime.fromisoformat(value))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _elapsed_days(now: datetime, last: datetime | None) -> float:
    if last is None:
        return 0.0
    return max(0.0, (now - _as_utc(last)).total_seconds() / 86400.0)


def _clamp_difficulty(value: float) -> float:
    return min(D_MAX, max(D_MIN, value))


def _init_stability(weights: tuple[float, ...], grade: int) -> float:
    return max(weights[grade - 1], S_MIN)


def _init_difficulty(weights: tuple[float, ...], grade: int) -> float:
    raw = weights[4] - math.exp(weights[5] * (grade - 1)) + 1.0
    return _clamp_difficulty(raw)


def _next_difficulty(weights: tuple[float, ...], difficulty: float, grade: int) -> float:
    delta = -weights[6] * (grade - 3)
    damped = difficulty + delta * (10.0 - difficulty) / 9.0
    easy = _init_difficulty(weights, 4)
    mixed = weights[7] * easy + (1.0 - weights[7]) * damped
    return _clamp_difficulty(mixed)


def _retrievability(elapsed_days: float, stability: float) -> float:
    if stability <= 0:
        return 0.0
    return (1.0 + FACTOR * elapsed_days / stability) ** DECAY


def _recall_stability(
    weights: tuple[float, ...],
    difficulty: float,
    stability: float,
    retrievability: float,
    grade: int,
) -> float:
    hard_penalty = weights[15] if grade == 2 else 1.0
    easy_bonus = weights[16] if grade == 4 else 1.0
    growth = (
        math.exp(weights[8])
        * (11.0 - difficulty)
        * (stability ** -weights[9])
        * (math.exp((1.0 - retrievability) * weights[10]) - 1.0)
        * hard_penalty
        * easy_bonus
    )
    return stability * (1.0 + growth)


def _forget_stability(
    weights: tuple[float, ...],
    difficulty: float,
    stability: float,
    retrievability: float,
) -> float:
    return (
        weights[11]
        * (difficulty ** -weights[12])
        * ((stability + 1.0) ** weights[13] - 1.0)
        * math.exp((1.0 - retrievability) * weights[14])
    )


def _short_term_stability(weights: tuple[float, ...], stability: float, grade: int) -> float:
    return stability * math.exp(weights[17] * (grade - 3 + weights[18]))


def _interval_days(stability: float, desired_retention: float) -> int:
    raw = (stability / FACTOR) * (desired_retention ** (1.0 / DECAY) - 1.0)
    days = int(round(raw))
    return min(MAXIMUM_INTERVAL_DAYS, max(1, days))


def _next_due(
    state: str,
    grade: int,
    stability: float,
    now: datetime,
    desired_retention: float,
) -> tuple[str, datetime, int]:
    """Good or Easy graduates. Again and Hard on a new or learning card stay short."""
    learning_step = state in {"new", "learning"} and grade <= 2
    lapse = grade == 1 and state == "review"
    if learning_step or lapse:
        minutes = AGAIN_MINUTES if grade == 1 else HARD_MINUTES
        return "learning", now + timedelta(minutes=minutes), 0
    days = _interval_days(stability, desired_retention)
    return "review", now + timedelta(days=days), days
