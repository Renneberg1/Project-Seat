"""SQLite database setup, schema, and connection helpers."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    jira_goal_key   TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    confluence_charter_id TEXT,
    confluence_xft_id     TEXT,
    status          TEXT    NOT NULL DEFAULT 'active',
    phase           TEXT    NOT NULL DEFAULT 'planning',
    dhf_draft_root_id     TEXT,
    dhf_released_root_id  TEXT,
    pi_version            TEXT,
    default_component     TEXT,
    default_label         TEXT,
    team_projects         TEXT,
    jira_plan_url         TEXT,
    confluence_ceo_review_id TEXT,
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
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS transcript_cache (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER,
    filename        TEXT    NOT NULL,
    raw_text        TEXT    NOT NULL,
    processed_json  TEXT,
    meeting_summary TEXT,
    source          TEXT    NOT NULL DEFAULT 'manual',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
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
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
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
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE (project_id, name)
);

CREATE TABLE IF NOT EXISTS release_documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id  INTEGER NOT NULL,
    doc_title   TEXT NOT NULL,
    FOREIGN KEY (release_id) REFERENCES releases(id) ON DELETE CASCADE,
    UNIQUE (release_id, doc_title)
);

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
    FOREIGN KEY (transcript_id) REFERENCES transcript_cache(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (approval_item_id) REFERENCES approval_queue(id)
);

CREATE TABLE IF NOT EXISTS team_progress_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    snapshot_date TEXT NOT NULL,
    data_json     TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE (project_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS health_reviews (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    health_rating TEXT NOT NULL,
    review_json   TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ceo_reviews (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id       INTEGER NOT NULL,
    review_json      TEXT NOT NULL DEFAULT '{}',
    confluence_body  TEXT NOT NULL DEFAULT '',
    approval_item_id INTEGER,
    status           TEXT NOT NULL DEFAULT 'draft',
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

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
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (approval_item_id) REFERENCES approval_queue(id)
);

CREATE TABLE IF NOT EXISTS closure_reports (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id       INTEGER NOT NULL,
    report_json      TEXT NOT NULL DEFAULT '{}',
    confluence_body  TEXT NOT NULL DEFAULT '',
    approval_item_id INTEGER,
    status           TEXT NOT NULL DEFAULT 'draft',
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS zoom_recordings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    zoom_meeting_uuid   TEXT    NOT NULL UNIQUE,
    zoom_meeting_id     TEXT    NOT NULL,
    topic               TEXT    NOT NULL DEFAULT '',
    host_email          TEXT    NOT NULL DEFAULT '',
    start_time          TEXT    NOT NULL,
    duration_minutes    INTEGER NOT NULL DEFAULT 0,
    transcript_url      TEXT    NOT NULL DEFAULT '',
    processing_status   TEXT    NOT NULL DEFAULT 'new',
    match_method        TEXT,
    error_message       TEXT,
    raw_metadata        TEXT    NOT NULL DEFAULT '{}',
    discovery_source    TEXT    NOT NULL DEFAULT 'recording',
    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS project_meeting_map (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    zoom_recording_id   INTEGER NOT NULL,
    project_id          INTEGER NOT NULL,
    transcript_id       INTEGER,
    analysis_status     TEXT    NOT NULL DEFAULT 'pending',
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (zoom_recording_id) REFERENCES zoom_recordings(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE (zoom_recording_id, project_id)
);

CREATE TABLE IF NOT EXISTS project_aliases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL,
    alias       TEXT    NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS action_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL,
    transcript_id   INTEGER,
    title           TEXT    NOT NULL,
    owner           TEXT    NOT NULL DEFAULT '',
    due_date        TEXT,
    status          TEXT    NOT NULL DEFAULT 'open',
    source          TEXT    NOT NULL DEFAULT 'transcript',
    evidence        TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (transcript_id) REFERENCES transcript_cache(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS knowledge_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL,
    transcript_id   INTEGER,
    entry_type      TEXT    NOT NULL DEFAULT 'note',
    title           TEXT    NOT NULL,
    content         TEXT    NOT NULL DEFAULT '',
    tags            TEXT    NOT NULL DEFAULT '[]',
    source          TEXT    NOT NULL DEFAULT 'transcript',
    published       INTEGER NOT NULL DEFAULT 0,
    approval_item_id INTEGER,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (transcript_id) REFERENCES transcript_cache(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS schema_versions (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


# ------------------------------------------------------------------
# Versioned migrations
# ------------------------------------------------------------------
# Each migration handles an incremental schema change.  They are run
# once and tracked in the ``schema_versions`` table.
# NOTE: For databases created after a migration was introduced, the
# _SCHEMA string already includes those columns/tables, so the
# migration is effectively a no-op guarded by ``IF NOT EXISTS`` /
# ``try/except OperationalError``.  This keeps both paths correct.

def _migrate_1_add_phase(conn: sqlite3.Connection) -> None:
    """Add phase column to projects (for databases created before it was in _SCHEMA)."""
    try:
        conn.execute("ALTER TABLE projects ADD COLUMN phase TEXT NOT NULL DEFAULT 'planning'")
    except sqlite3.OperationalError:
        pass


def _migrate_2_add_dhf_columns(conn: sqlite3.Connection) -> None:
    for col in ("dhf_draft_root_id", "dhf_released_root_id"):
        try:
            conn.execute(f"ALTER TABLE projects ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass


def _migrate_3_add_pi_version(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ALTER TABLE projects ADD COLUMN pi_version TEXT")
    except sqlite3.OperationalError:
        pass


def _migrate_4_add_component_label(conn: sqlite3.Connection) -> None:
    for col in ("default_component", "default_label"):
        try:
            conn.execute(f"ALTER TABLE projects ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass


def _migrate_5_add_team_projects(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ALTER TABLE projects ADD COLUMN team_projects TEXT")
    except sqlite3.OperationalError:
        pass


def _migrate_6_add_jira_plan_url(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ALTER TABLE projects ADD COLUMN jira_plan_url TEXT")
    except sqlite3.OperationalError:
        pass


def _migrate_7_add_meeting_summary(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ALTER TABLE transcript_cache ADD COLUMN meeting_summary TEXT")
    except sqlite3.OperationalError:
        pass


def _migrate_8_add_ceo_review_id(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ALTER TABLE projects ADD COLUMN confluence_ceo_review_id TEXT")
    except sqlite3.OperationalError:
        pass


def _migrate_9_add_indexes(conn: sqlite3.Connection) -> None:
    """Add secondary indexes for common query patterns."""
    for ddl in [
        "CREATE INDEX IF NOT EXISTS idx_transcript_suggestions_tid ON transcript_suggestions(transcript_id)",
        "CREATE INDEX IF NOT EXISTS idx_transcript_suggestions_proj ON transcript_suggestions(project_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_approval_queue_proj ON approval_queue(project_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_approval_queue_status ON approval_queue(status)",
        "CREATE INDEX IF NOT EXISTS idx_charter_suggestions_proj ON charter_suggestions(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_health_reviews_proj ON health_reviews(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_ceo_reviews_proj ON ceo_reviews(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_approval_log_proj ON approval_log(project_id)",
    ]:
        conn.execute(ddl)


def _migrate_10_add_cascade(conn: sqlite3.Connection) -> None:
    """Recreate tables with ON DELETE CASCADE on FK constraints.

    For tables that were created before CASCADE was added to _SCHEMA,
    we recreate them with the correct FK definitions.  Tables created
    after this migration already have CASCADE in _SCHEMA, so the
    recreation is harmless (copies data to itself).
    """
    _TABLE_DEFS: list[tuple[str, str, list[str]]] = [
        # (table_name, CREATE TABLE sql for _new table, index DDLs to recreate)
        (
            "approval_log",
            """CREATE TABLE approval_log_new (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  INTEGER,
                action_type TEXT    NOT NULL,
                payload     TEXT    NOT NULL,
                approved_by TEXT,
                approved_at TEXT,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )""",
            ["CREATE INDEX IF NOT EXISTS idx_approval_log_proj ON approval_log(project_id)"],
        ),
        (
            "transcript_cache",
            """CREATE TABLE transcript_cache_new (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id      INTEGER,
                filename        TEXT    NOT NULL,
                raw_text        TEXT    NOT NULL,
                processed_json  TEXT,
                meeting_summary TEXT,
                source          TEXT    NOT NULL DEFAULT 'manual',
                created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )""",
            [],
        ),
        (
            "approval_queue",
            """CREATE TABLE approval_queue_new (
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
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )""",
            [
                "CREATE INDEX IF NOT EXISTS idx_approval_queue_proj ON approval_queue(project_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_approval_queue_status ON approval_queue(status)",
            ],
        ),
        (
            "releases",
            """CREATE TABLE releases_new (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id       INTEGER NOT NULL,
                name             TEXT NOT NULL,
                locked           INTEGER NOT NULL DEFAULT 0,
                version_snapshot TEXT,
                created_at       TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE (project_id, name)
            )""",
            [],
        ),
        (
            "transcript_suggestions",
            """CREATE TABLE transcript_suggestions_new (
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
                FOREIGN KEY (transcript_id) REFERENCES transcript_cache(id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (approval_item_id) REFERENCES approval_queue(id)
            )""",
            [
                "CREATE INDEX IF NOT EXISTS idx_transcript_suggestions_tid ON transcript_suggestions(transcript_id)",
                "CREATE INDEX IF NOT EXISTS idx_transcript_suggestions_proj ON transcript_suggestions(project_id, status)",
            ],
        ),
        (
            "team_progress_snapshots",
            """CREATE TABLE team_progress_snapshots_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id    INTEGER NOT NULL,
                snapshot_date TEXT NOT NULL,
                data_json     TEXT NOT NULL,
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE (project_id, snapshot_date)
            )""",
            [],
        ),
        (
            "health_reviews",
            """CREATE TABLE health_reviews_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id    INTEGER NOT NULL,
                health_rating TEXT NOT NULL,
                review_json   TEXT NOT NULL DEFAULT '{}',
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )""",
            ["CREATE INDEX IF NOT EXISTS idx_health_reviews_proj ON health_reviews(project_id)"],
        ),
        (
            "ceo_reviews",
            """CREATE TABLE ceo_reviews_new (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id       INTEGER NOT NULL,
                review_json      TEXT NOT NULL DEFAULT '{}',
                confluence_body  TEXT NOT NULL DEFAULT '',
                approval_item_id INTEGER,
                status           TEXT NOT NULL DEFAULT 'draft',
                created_at       TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )""",
            ["CREATE INDEX IF NOT EXISTS idx_ceo_reviews_proj ON ceo_reviews(project_id)"],
        ),
        (
            "charter_suggestions",
            """CREATE TABLE charter_suggestions_new (
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
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (approval_item_id) REFERENCES approval_queue(id)
            )""",
            ["CREATE INDEX IF NOT EXISTS idx_charter_suggestions_proj ON charter_suggestions(project_id)"],
        ),
    ]

    # FK pragma must be toggled outside any transaction
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        for table_name, create_sql, index_ddls in _TABLE_DEFS:
            # Check if table exists
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()
            if not exists:
                continue

            conn.execute(create_sql)
            conn.execute(f"INSERT INTO {table_name}_new SELECT * FROM {table_name}")
            conn.execute(f"DROP TABLE {table_name}")
            conn.execute(f"ALTER TABLE {table_name}_new RENAME TO {table_name}")
            for ddl in index_ddls:
                conn.execute(ddl)
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _migrate_11_add_closure_reports(conn: sqlite3.Connection) -> None:
    """Create closure_reports table and index for databases created before it was in _SCHEMA."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS closure_reports (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id       INTEGER NOT NULL,
            report_json      TEXT NOT NULL DEFAULT '{}',
            confluence_body  TEXT NOT NULL DEFAULT '',
            approval_item_id INTEGER,
            status           TEXT NOT NULL DEFAULT 'draft',
            created_at       TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_closure_reports_proj ON closure_reports(project_id)"
    )


def _migrate_12_add_zoom_and_knowledge(conn: sqlite3.Connection) -> None:
    """Create zoom_recordings, project_meeting_map, project_aliases, action_items,
    and knowledge_entries tables for databases created before they were in _SCHEMA."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS zoom_recordings (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            zoom_meeting_uuid   TEXT    NOT NULL UNIQUE,
            zoom_meeting_id     TEXT    NOT NULL,
            topic               TEXT    NOT NULL DEFAULT '',
            host_email          TEXT    NOT NULL DEFAULT '',
            start_time          TEXT    NOT NULL,
            duration_minutes    INTEGER NOT NULL DEFAULT 0,
            transcript_url      TEXT    NOT NULL DEFAULT '',
            processing_status   TEXT    NOT NULL DEFAULT 'new',
            match_method        TEXT,
            error_message       TEXT,
            raw_metadata        TEXT    NOT NULL DEFAULT '{}',
            created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS project_meeting_map (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            zoom_recording_id   INTEGER NOT NULL,
            project_id          INTEGER NOT NULL,
            transcript_id       INTEGER,
            analysis_status     TEXT    NOT NULL DEFAULT 'pending',
            created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (zoom_recording_id) REFERENCES zoom_recordings(id) ON DELETE CASCADE,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            UNIQUE (zoom_recording_id, project_id)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS project_aliases (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER NOT NULL,
            alias       TEXT    NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS action_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id      INTEGER NOT NULL,
            transcript_id   INTEGER,
            title           TEXT    NOT NULL,
            owner           TEXT    NOT NULL DEFAULT '',
            due_date        TEXT,
            status          TEXT    NOT NULL DEFAULT 'open',
            source          TEXT    NOT NULL DEFAULT 'transcript',
            evidence        TEXT    NOT NULL DEFAULT '',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (transcript_id) REFERENCES transcript_cache(id) ON DELETE SET NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS knowledge_entries (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id      INTEGER NOT NULL,
            transcript_id   INTEGER,
            entry_type      TEXT    NOT NULL DEFAULT 'note',
            title           TEXT    NOT NULL,
            content         TEXT    NOT NULL DEFAULT '',
            tags            TEXT    NOT NULL DEFAULT '[]',
            source          TEXT    NOT NULL DEFAULT 'transcript',
            published       INTEGER NOT NULL DEFAULT 0,
            approval_item_id INTEGER,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (transcript_id) REFERENCES transcript_cache(id) ON DELETE SET NULL
        )"""
    )
    # Indexes
    for ddl in [
        "CREATE INDEX IF NOT EXISTS idx_zoom_recordings_status ON zoom_recordings(processing_status)",
        "CREATE INDEX IF NOT EXISTS idx_project_meeting_map_rec ON project_meeting_map(zoom_recording_id)",
        "CREATE INDEX IF NOT EXISTS idx_project_meeting_map_proj ON project_meeting_map(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_project_aliases_proj ON project_aliases(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_action_items_proj ON action_items(project_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_entries_proj ON knowledge_entries(project_id, entry_type)",
    ]:
        conn.execute(ddl)


def _migrate_13_add_transcript_source(conn: sqlite3.Connection) -> None:
    """Add source column to transcript_cache for databases created before it was in _SCHEMA."""
    try:
        conn.execute("ALTER TABLE transcript_cache ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
    except sqlite3.OperationalError:
        pass  # Column already exists (new databases)

    # Backfill existing Zoom-originated transcripts
    conn.execute(
        """UPDATE transcript_cache SET source = 'zoom'
           WHERE id IN (SELECT transcript_id FROM project_meeting_map WHERE transcript_id IS NOT NULL)"""
    )


def _migrate_14_add_discovery_source(conn: sqlite3.Connection) -> None:
    """Add discovery_source column to zoom_recordings for transcript-only meetings."""
    try:
        conn.execute(
            "ALTER TABLE zoom_recordings ADD COLUMN discovery_source TEXT NOT NULL DEFAULT 'recording'"
        )
    except sqlite3.OperationalError:
        pass  # Column already exists (new databases)


_MIGRATIONS: list[tuple[int, callable]] = [
    (1, _migrate_1_add_phase),
    (2, _migrate_2_add_dhf_columns),
    (3, _migrate_3_add_pi_version),
    (4, _migrate_4_add_component_label),
    (5, _migrate_5_add_team_projects),
    (6, _migrate_6_add_jira_plan_url),
    (7, _migrate_7_add_meeting_summary),
    (8, _migrate_8_add_ceo_review_id),
    (9, _migrate_9_add_indexes),
    (10, _migrate_10_add_cascade),
    (11, _migrate_11_add_closure_reports),
    (12, _migrate_12_add_zoom_and_knowledge),
    (13, _migrate_13_add_transcript_source),
    (14, _migrate_14_add_discovery_source),
]


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Execute any pending migrations and record them in schema_versions."""
    for version, fn in _MIGRATIONS:
        row = conn.execute(
            "SELECT 1 FROM schema_versions WHERE version = ?", (version,)
        ).fetchone()
        if row is None:
            logger.info("Running migration %d: %s", version, fn.__name__)
            fn(conn)
            conn.execute(
                "INSERT INTO schema_versions (version) VALUES (?)", (version,)
            )
    conn.commit()


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def init_db(db_path: str | Path = "seat.db") -> None:
    """Create all tables if they don't already exist."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        conn.executescript(_SCHEMA)
        _run_migrations(conn)
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
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
    finally:
        conn.close()
