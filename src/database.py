"""SQLite database setup, schema, and connection helpers."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    jira_goal_key   TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    confluence_charter_id TEXT,
    confluence_xft_id     TEXT,
    status          TEXT    NOT NULL DEFAULT 'active',
    phase           TEXT    NOT NULL DEFAULT 'planning',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS approval_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER,
    action_type TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS transcript_cache (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER,
    filename        TEXT    NOT NULL,
    raw_text        TEXT    NOT NULL,
    processed_json  TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS approval_queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER,
    action_type TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    preview     TEXT    NOT NULL DEFAULT '',
    context     TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'pending',
    result      TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def init_db(db_path: str | Path = "seat.db") -> None:
    """Create all tables if they don't already exist."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA)
        # Migration: add phase column if not present (existing databases)
        try:
            conn.execute("ALTER TABLE projects ADD COLUMN phase TEXT NOT NULL DEFAULT 'planning'")
        except sqlite3.OperationalError:
            pass  # column already exists
        # Migration: add DHF root page ID columns
        for col in ("dhf_draft_root_id", "dhf_released_root_id"):
            try:
                conn.execute(f"ALTER TABLE projects ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists
        # Migration: add PI version column
        try:
            conn.execute("ALTER TABLE projects ADD COLUMN pi_version TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_db(db_path: str | Path = "seat.db") -> Generator[sqlite3.Connection, None, None]:
    """Yield a SQLite connection, closing it when done.

    Usage::

        with get_db() as conn:
            conn.execute("SELECT ...")
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
