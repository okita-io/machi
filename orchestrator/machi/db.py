"""SQLite progress store (minimal v0)."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
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
        )
        conn.commit()
    finally:
        conn.close()


def record_session(path: Path, session_id: str, scenario_id: str, level: int) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO sessions (id, scenario_id, level) VALUES (?, ?, ?)",
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
) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO attempts (session_id, node_id, utterance, goal_hits) VALUES (?, ?, ?, ?)",
            (session_id, node_id, utterance, ",".join(goal_hits)),
        )
        conn.commit()
    finally:
        conn.close()