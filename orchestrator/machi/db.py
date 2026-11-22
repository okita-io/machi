"""SQLite progress store.

Schema v4 is applied by ``init_db``. Databases created before versioning (v1
sessions + attempts only) are altered in place, then v2 hint columns, the v3
``pitch_advisory`` JSON column, and the v4 ``corrections`` / ``cards`` tables
are added. Debrief writes session stars, completion, and the max hint rung,
plus one ``hint:{goal_id}`` attempt row per goal so per-goal peaks survive in
the attempt columns. Pitch advice is stored on the spoken attempt and never
changes stars.

A correction row is one phrase the tutor (or a missed warm-up line) asked the
learner to try. Weight is repeat misses plus hint climbs. Completing a visit
inserts one FSRS card per correction; ``srs_tags`` from the scenario are copied
onto that card. Cards start ``new`` and due immediately.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 4

# Historical v1 DDL. Kept so migrations and tests share one literal.
V1_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  scenario_id TEXT NOT NULL,
  level INTEGER NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  node_id TEXT,
  utterance TEXT,
  goal_hits TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

_SESSION_COLUMNS_V2 = (
    ("stars", "INTEGER"),
    ("max_hint_rung", "INTEGER"),
    ("completed", "INTEGER NOT NULL DEFAULT 0"),
)
_ATTEMPT_COLUMNS_V2 = (
    ("hint_rung", "INTEGER"),
    ("correction_ja", "TEXT"),
    ("correction_en", "TEXT"),
)


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        has_sessions = _table_exists(conn, "sessions")
        _ensure_version_table(conn)
        version = _stored_version(conn)
        if not has_sessions:
            _create_current_tables(conn)
            _write_version(conn, SCHEMA_VERSION)
        elif version is None or version < SCHEMA_VERSION:
            _migrate_to_current(conn, version)
            _write_version(conn, SCHEMA_VERSION)
        conn.commit()
    finally:
        conn.close()


def record_session(path: Path, session_id: str, scenario_id: str, level: int) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO sessions (id, scenario_id, level)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              scenario_id = excluded.scenario_id,
              level = excluded.level
            """,
            (session_id, scenario_id, level),
        )
        conn.commit()
    finally:
        conn.close()


def record_attempt(
    path: Path,
    session_id: str,
    node_id: str,
    utterance: str,
    goal_hits: list[str],
    *,
    hint_rung: int | None = None,
    correction_ja: str | None = None,
    correction_en: str | None = None,
    pitch_advisory: dict[str, Any] | None = None,
) -> None:
    advisory = None
    if pitch_advisory is not None:
        advisory = json.dumps(pitch_advisory, ensure_ascii=False)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO attempts (
              session_id, node_id, utterance, goal_hits,
              hint_rung, correction_ja, correction_en, pitch_advisory
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                node_id,
                utterance,
                ",".join(goal_hits),
                hint_rung,
                correction_ja,
                correction_en,
                advisory,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def record_debrief(
    path: Path,
    session_id: str,
    *,
    stars: int,
    completed: bool,
    hint_peaks: dict[str, int],
    max_hint_rung: int,
) -> None:
    """Persist the debrief summary. Replaces prior per-goal hint rows."""
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            UPDATE sessions
            SET stars = ?, max_hint_rung = ?, completed = ?
            WHERE id = ?
            """,
            (stars, max_hint_rung, 1 if completed else 0, session_id),
        )
        conn.execute(
            "DELETE FROM attempts WHERE session_id = ? AND node_id LIKE 'hint:%'",
            (session_id,),
        )
        for goal_id, rung in hint_peaks.items():
            if not goal_id:
                continue
            conn.execute(
                """
                INSERT INTO attempts (session_id, node_id, utterance, goal_hits, hint_rung)
                VALUES (?, ?, '', ?, ?)
                """,
                (session_id, f"hint:{goal_id}", goal_id, int(rung)),
            )
        conn.commit()
    finally:
        conn.close()


def session_progress(path: Path, session_id: str) -> dict | None:
    conn = _connect(path)
    try:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        attempts = conn.execute(
            "SELECT * FROM attempts WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()
    return _progress_payload(row, attempts)


def list_sessions(path: Path) -> list[dict]:
    conn = _connect(path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM sessions
            ORDER BY created_at, id
            """
        ).fetchall()
    finally:
        conn.close()
    return [_session_summary(row) for row in rows]


def _progress_payload(row: sqlite3.Row, attempts: list[sqlite3.Row]) -> dict:
    hint_rows = [item for item in attempts if _is_hint_row(item["node_id"])]
    spoken = [item for item in attempts if not _is_hint_row(item["node_id"])]
    if hint_rows:
        hint_max = {_hint_goal(item["node_id"]): item["hint_rung"] for item in hint_rows}
    else:
        hint_max = _hint_max_from_attempts(spoken)
    payload = _session_summary(row)
    payload["hint_max"] = hint_max
    payload["attempts"] = [_attempt_payload(item) for item in spoken]
    return payload


def _session_summary(row: sqlite3.Row) -> dict:
    return {
        "session_id": row["id"],
        "scenario_id": row["scenario_id"],
        "level": row["level"],
        "stars": row["stars"],
        "max_hint_rung": row["max_hint_rung"],
        "completed": bool(row["completed"]),
        "created_at": row["created_at"],
    }


def _attempt_payload(row: sqlite3.Row) -> dict:
    raw_hits = row["goal_hits"] or ""
    return {
        "id": row["id"],
        "node_id": row["node_id"],
        "utterance": row["utterance"],
        "goal_hits": [part for part in raw_hits.split(",") if part],
        "hint_rung": row["hint_rung"],
        "correction_ja": row["correction_ja"],
        "correction_en": row["correction_en"],
        "pitch_advisory": _load_advisory(row["pitch_advisory"]),
        "created_at": row["created_at"],
    }


def _load_advisory(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _hint_max_from_attempts(attempts: list[sqlite3.Row]) -> dict[str, int]:
    peaks: dict[str, int] = {}
    for row in attempts:
        if row["hint_rung"] is None:
            continue
        for goal_id in (row["goal_hits"] or "").split(","):
            if not goal_id:
                continue
            peaks[goal_id] = max(peaks.get(goal_id, 0), int(row["hint_rung"]))
    return peaks


def _is_hint_row(node_id: str | None) -> bool:
    return bool(node_id) and node_id.startswith("hint:")


def _hint_goal(node_id: str) -> str:
    return node_id.removeprefix("hint:")


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          version INTEGER NOT NULL
        )
        """
    )


def _stored_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    if row is None:
        return None
    return int(row[0])


def _write_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        """
        INSERT INTO schema_version (id, version) VALUES (1, ?)
        ON CONFLICT(id) DO UPDATE SET version = excluded.version
        """,
        (version,),
    )


def _create_current_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY,
          scenario_id TEXT NOT NULL,
          level INTEGER NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          stars INTEGER,
          max_hint_rung INTEGER,
          completed INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS attempts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT NOT NULL,
          node_id TEXT,
          utterance TEXT,
          goal_hits TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          hint_rung INTEGER,
          correction_ja TEXT,
          correction_en TEXT,
          pitch_advisory TEXT
        );
        """
    )
    _create_review_tables(conn)


def _migrate_to_current(conn: sqlite3.Connection, version: int | None) -> None:
    if version is None or version < 2:
        _migrate_v1_to_v2(conn)
    if version is None or version < 3:
        _add_column(conn, "attempts", "pitch_advisory", "TEXT")
    if version is None or version < 4:
        _create_review_tables(conn)


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    for name, decl in _SESSION_COLUMNS_V2:
        _add_column(conn, "sessions", name, decl)
    for name, decl in _ATTEMPT_COLUMNS_V2:
        _add_column(conn, "attempts", name, decl)


def _create_review_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS corrections (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT NOT NULL,
          scenario_id TEXT NOT NULL,
          goal_id TEXT,
          learner_text TEXT,
          correction_ja TEXT,
          correction_en TEXT,
          kana_ruby TEXT,
          romaji TEXT,
          srs_tags TEXT,
          weight INTEGER NOT NULL DEFAULT 0,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_corrections_session
          ON corrections (session_id);
        CREATE TABLE IF NOT EXISTS cards (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          correction_id INTEGER NOT NULL UNIQUE,
          state TEXT NOT NULL DEFAULT 'new'
            CHECK (state IN ('new', 'learning', 'review')),
          due_at TEXT,
          stability REAL,
          difficulty REAL,
          reps INTEGER NOT NULL DEFAULT 0,
          lapses INTEGER NOT NULL DEFAULT 0,
          last_rating TEXT,
          last_review_at TEXT,
          srs_tags TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_cards_due ON cards (due_at);
        """
    )


def record_correction(
    path: Path,
    *,
    session_id: str,
    scenario_id: str,
    goal_id: str,
    learner_text: str,
    correction_ja: str,
    correction_en: str,
    kana_ruby: str,
    romaji: str,
    srs_tags: list[str],
    weight: int,
) -> int:
    """Insert a phrase, or refresh it when the same Japanese line is missed again."""
    tags = ",".join(part for part in srs_tags if part)
    conn = sqlite3.connect(path)
    try:
        if correction_ja:
            row = conn.execute(
                """
                SELECT id FROM corrections
                WHERE session_id = ? AND correction_ja = ?
                """,
                (session_id, correction_ja),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT id FROM corrections
                WHERE session_id = ? AND correction_ja = '' AND correction_en = ?
                """,
                (session_id, correction_en),
            ).fetchone()
        if row is None:
            cur = conn.execute(
                """
                INSERT INTO corrections (
                  session_id, scenario_id, goal_id, learner_text,
                  correction_ja, correction_en, kana_ruby, romaji, srs_tags, weight
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    scenario_id,
                    goal_id,
                    learner_text,
                    correction_ja,
                    correction_en,
                    kana_ruby,
                    romaji,
                    tags,
                    int(weight),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        conn.execute(
            """
            UPDATE corrections
            SET scenario_id = ?, goal_id = ?, learner_text = ?,
                correction_en = ?, kana_ruby = ?, romaji = ?, srs_tags = ?, weight = ?
            WHERE id = ?
            """,
            (
                scenario_id,
                goal_id,
                learner_text,
                correction_en,
                kana_ruby,
                romaji,
                tags,
                int(weight),
                int(row[0]),
            ),
        )
        conn.commit()
        return int(row[0])
    finally:
        conn.close()


def enroll_corrections(path: Path, session_id: str, *, due_at: str) -> int:
    """Add one new card per correction that does not have one yet."""
    conn = _connect(path)
    try:
        rows = conn.execute(
            """
            SELECT id, srs_tags FROM corrections
            WHERE session_id = ?
            ORDER BY id
            """,
            (session_id,),
        ).fetchall()
        added = 0
        for row in rows:
            cur = conn.execute(
                """
                INSERT INTO cards (
                  correction_id, state, due_at, reps, lapses, srs_tags
                ) VALUES (?, 'new', ?, 0, 0, ?)
                ON CONFLICT(correction_id) DO NOTHING
                """,
                (row["id"], due_at, row["srs_tags"]),
            )
            added += cur.rowcount
        conn.commit()
        return added
    finally:
        conn.close()


def next_due_cards(path: Path, *, now: str, limit: int) -> list[dict]:
    """Due cards soonest first. A null due time is due now."""
    conn = _connect(path)
    try:
        rows = conn.execute(
            f"""
            {_CARD_SELECT}
            WHERE cards.due_at IS NULL OR cards.due_at <= ?
            ORDER BY cards.due_at ASC, cards.id ASC
            LIMIT ?
            """,
            (now, limit),
        ).fetchall()
    finally:
        conn.close()
    return [_review_card_payload(row) for row in rows]


def get_review_card(path: Path, card_id: int) -> dict | None:
    conn = _connect(path)
    try:
        row = conn.execute(
            f"{_CARD_SELECT} WHERE cards.id = ?",
            (card_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _review_card_payload(row)


def save_card_review(
    path: Path,
    card_id: int,
    *,
    state: str,
    due_at: str,
    stability: float,
    difficulty: float,
    reps: int,
    lapses: int,
    last_rating: str,
    last_review_at: str,
) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            UPDATE cards
            SET state = ?, due_at = ?, stability = ?, difficulty = ?,
                reps = ?, lapses = ?, last_rating = ?, last_review_at = ?
            WHERE id = ?
            """,
            (
                state,
                due_at,
                stability,
                difficulty,
                reps,
                lapses,
                last_rating,
                last_review_at,
                card_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


_CARD_SELECT = """
SELECT
  cards.id AS card_id,
  cards.correction_id AS correction_id,
  cards.state AS state,
  cards.due_at AS due_at,
  cards.stability AS stability,
  cards.difficulty AS difficulty,
  cards.reps AS reps,
  cards.lapses AS lapses,
  cards.last_rating AS last_rating,
  cards.last_review_at AS last_review_at,
  cards.srs_tags AS srs_tags,
  corrections.session_id AS session_id,
  corrections.scenario_id AS scenario_id,
  corrections.goal_id AS goal_id,
  corrections.learner_text AS learner_text,
  corrections.correction_ja AS correction_ja,
  corrections.correction_en AS correction_en,
  corrections.kana_ruby AS kana_ruby,
  corrections.romaji AS romaji,
  corrections.weight AS weight
FROM cards
JOIN corrections ON corrections.id = cards.correction_id
"""


def _review_card_payload(row: sqlite3.Row) -> dict:
    raw_tags = row["srs_tags"] or ""
    return {
        "card_id": row["card_id"],
        "correction_id": row["correction_id"],
        "state": row["state"],
        "due_at": row["due_at"],
        "stability": row["stability"],
        "difficulty": row["difficulty"],
        "reps": row["reps"],
        "lapses": row["lapses"],
        "last_rating": row["last_rating"],
        "last_review_at": row["last_review_at"],
        "srs_tags": [part for part in raw_tags.split(",") if part],
        "session_id": row["session_id"],
        "scenario_id": row["scenario_id"],
        "goal_id": row["goal_id"] or "",
        "learner_text": row["learner_text"] or "",
        "correction_ja": row["correction_ja"] or "",
        "correction_en": row["correction_en"] or "",
        "kana_ruby": row["kana_ruby"] or "",
        "romaji": row["romaji"] or "",
        "weight": row["weight"] or 0,
    }


def _add_column(conn: sqlite3.Connection, table: str, name: str, decl: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if name in existing:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
