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

CREATE TABLE IF NOT EXISTS releases (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id       INTEGER NOT NULL,
    name             TEXT NOT NULL,
    locked           INTEGER NOT NULL DEFAULT 0,
    version_snapshot TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id),
    UNIQUE (project_id, name)
);

CREATE TABLE IF NOT EXISTS release_documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id  INTEGER NOT NULL,
    doc_title   TEXT NOT NULL,
    FOREIGN KEY (release_id) REFERENCES releases(id) ON DELETE CASCADE,
    UNIQUE (release_id, doc_title)
);
"""


def init_db(db_path: str | Path = "seat.db") -> None:
    """Create all tables if they don't already exist."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
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
        # Migration: add default_component and default_label to projects
        for col in ("default_component", "default_label"):
            try:
                conn.execute(f"ALTER TABLE projects ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists
        # Migration: add team_projects column (JSON-encoded list of Jira project keys)
        try:
            conn.execute("ALTER TABLE projects ADD COLUMN team_projects TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
        # Migration: add jira_plan_url column
        try:
            conn.execute("ALTER TABLE projects ADD COLUMN jira_plan_url TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
        # Migration: add meeting_summary to transcript_cache
        try:
            conn.execute("ALTER TABLE transcript_cache ADD COLUMN meeting_summary TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
        # Migration: transcript_suggestions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transcript_suggestions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_id   INTEGER NOT NULL,
                project_id      INTEGER NOT NULL,
                suggestion_type TEXT    NOT NULL,
                title           TEXT    NOT NULL,
                detail          TEXT    NOT NULL DEFAULT '',
                evidence        TEXT    NOT NULL DEFAULT '',
                proposed_payload TEXT   NOT NULL DEFAULT '{}',
                proposed_action TEXT    NOT NULL DEFAULT '',
                proposed_preview TEXT   NOT NULL DEFAULT '',
                confidence      REAL   NOT NULL DEFAULT 0.0,
                status          TEXT    NOT NULL DEFAULT 'pending',
                approval_item_id INTEGER,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (transcript_id) REFERENCES transcript_cache(id),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (approval_item_id) REFERENCES approval_queue(id)
            )
        """)
        # Migration: team_progress_snapshots table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS team_progress_snapshots (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id    INTEGER NOT NULL,
                snapshot_date TEXT NOT NULL,
                data_json     TEXT NOT NULL,
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                UNIQUE (project_id, snapshot_date)
            )
        """)
        # Migration: charter_suggestions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS charter_suggestions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id       INTEGER NOT NULL,
                section_name     TEXT    NOT NULL,
                current_text     TEXT    NOT NULL DEFAULT '',
                proposed_text    TEXT    NOT NULL DEFAULT '',
                rationale        TEXT    NOT NULL DEFAULT '',
                confidence       REAL   NOT NULL DEFAULT 0.0,
                proposed_payload TEXT    NOT NULL DEFAULT '{}',
                proposed_preview TEXT    NOT NULL DEFAULT '',
                analysis_summary TEXT   NOT NULL DEFAULT '',
                status           TEXT    NOT NULL DEFAULT 'pending',
                approval_item_id INTEGER,
                created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (approval_item_id) REFERENCES approval_queue(id)
            )
        """)
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
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()
