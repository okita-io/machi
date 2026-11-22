"""Schema v2 migration and debrief progress rows."""

from __future__ import annotations

import sqlite3

from machi.db import (
    SCHEMA_VERSION,
    init_db,
    record_attempt,
    record_debrief,
    record_session,
    session_progress,
)

# v1 shape from before schema_version. init_db must alter this in place.
V1_SCHEMA_SQL = """
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  scenario_id TEXT NOT NULL,
  level INTEGER NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  node_id TEXT,
  utterance TEXT,
  goal_hits TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def _columns(path, table: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_v1_database_migrates_in_place(tmp_path):
    path = tmp_path / "v1.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(V1_SCHEMA_SQL)
    conn.execute(
        "INSERT INTO sessions (id, scenario_id, level, created_at) VALUES (?, ?, ?, ?)",
        ("sess-1", "restaurant_ramen_01", 2, "2024-01-01 00:00:00"),
    )
    conn.execute(
        """
        INSERT INTO attempts (session_id, node_id, utterance, goal_hits, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("sess-1", "greet", "ふたりです", "party_size", "2024-01-01 00:01:00"),
    )
    conn.commit()
    conn.close()

    init_db(path)
    init_db(path)

    assert {"stars", "max_hint_rung", "completed"} <= _columns(path, "sessions")
    assert {"hint_rung", "correction_ja", "correction_en"} <= _columns(path, "attempts")

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        version = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
        assert version["version"] == SCHEMA_VERSION
        session = conn.execute("SELECT * FROM sessions WHERE id = 'sess-1'").fetchone()
        assert session["scenario_id"] == "restaurant_ramen_01"
        assert session["level"] == 2
        assert session["created_at"] == "2024-01-01 00:00:00"
        assert session["stars"] is None
        assert session["max_hint_rung"] is None
        assert session["completed"] == 0
        attempt = conn.execute("SELECT * FROM attempts").fetchone()
        assert attempt["node_id"] == "greet"
        assert attempt["utterance"] == "ふたりです"
        assert attempt["goal_hits"] == "party_size"
        assert attempt["created_at"] == "2024-01-01 00:01:00"
        assert attempt["hint_rung"] is None
        assert attempt["correction_ja"] is None
        assert attempt["correction_en"] is None
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
    finally:
        conn.close()

    record_debrief(
        path,
        "sess-1",
        stars=2,
        completed=True,
        hint_peaks={"party_size": 2, "order": 1},
        max_hint_rung=2,
    )
    progress = session_progress(path, "sess-1")
    assert progress is not None
    assert progress["stars"] == 2
    assert progress["completed"] is True
    assert progress["max_hint_rung"] == 2
    assert progress["hint_max"] == {"party_size": 2, "order": 1}
    assert progress["level"] == 2
    assert [row["utterance"] for row in progress["attempts"]] == ["ふたりです"]


def test_fresh_database_is_v2_and_stores_attempt_corrections(tmp_path):
    path = tmp_path / "fresh.sqlite"
    init_db(path)
    record_session(path, "sess-2", "restaurant_ramen_01", 1)
    record_attempt(
        path,
        "sess-2",
        "seat",
        "ふたりです",
        ["party_size"],
        hint_rung=1,
        correction_ja="二人です",
        correction_en="Two people.",
    )
    progress = session_progress(path, "sess-2")
    assert progress is not None
    assert progress["stars"] is None
    assert progress["completed"] is False
    assert progress["attempts"][0]["hint_rung"] == 1
    assert progress["attempts"][0]["correction_ja"] == "二人です"
    assert progress["attempts"][0]["correction_en"] == "Two people."
    assert progress["attempts"][0]["goal_hits"] == ["party_size"]
    assert session_progress(path, "missing") is None
