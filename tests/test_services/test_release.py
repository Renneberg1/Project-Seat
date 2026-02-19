"""Tests for release service — CRUD, document selection, lock/unlock, status computation."""

from __future__ import annotations

import pytest

from src.database import get_db
from src.models.release import ReleaseStatus
from src.services.release import ReleaseService


def _insert_project(db_path: str, name: str = "Test Project") -> int:
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase) VALUES (?, ?, ?, ?)",
            ("PROG-100", name, "active", "planning"),
        )
        conn.commit()
        return cursor.lastrowid


# ---------------------------------------------------------------------------
# create_release: Incoming command — assert state change
# ---------------------------------------------------------------------------


def test_create_release_returns_release_with_correct_fields(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)

    release = service.create_release(pid, "v1.0")

    assert release.project_id == pid
    assert release.name == "v1.0"
    assert release.locked is False
    assert release.version_snapshot is None
    assert release.id is not None


def test_create_release_persists_to_database(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)

    release = service.create_release(pid, "v1.0")

    with get_db(tmp_db) as conn:
        row = conn.execute("SELECT * FROM releases WHERE id = ?", (release.id,)).fetchone()
    assert row is not None
    assert row["name"] == "v1.0"


def test_create_release_enforces_unique_name_per_project(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)
    service.create_release(pid, "v1.0")

    with pytest.raises(Exception):
        service.create_release(pid, "v1.0")


def test_create_release_allows_same_name_in_different_projects(tmp_db):
    pid1 = _insert_project(tmp_db, "Project A")
    pid2 = _insert_project(tmp_db, "Project B")
    service = ReleaseService(db_path=tmp_db)

    r1 = service.create_release(pid1, "v1.0")
    r2 = service.create_release(pid2, "v1.0")

    assert r1.id != r2.id


# ---------------------------------------------------------------------------
# list_releases: Incoming query — assert return value
# ---------------------------------------------------------------------------


def test_list_releases_returns_all_for_project(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)
    service.create_release(pid, "v1.0")
    service.create_release(pid, "v2.0")

    result = service.list_releases(pid)

    assert len(result) == 2
    names = {r.name for r in result}
    assert names == {"v1.0", "v2.0"}


def test_list_releases_returns_empty_for_project_with_none(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)

    result = service.list_releases(pid)

    assert result == []


def test_list_releases_does_not_include_other_projects(tmp_db):
    pid1 = _insert_project(tmp_db, "Project A")
    pid2 = _insert_project(tmp_db, "Project B")
    service = ReleaseService(db_path=tmp_db)
    service.create_release(pid1, "v1.0")
    service.create_release(pid2, "v2.0")

    result = service.list_releases(pid1)

    assert len(result) == 1
    assert result[0].name == "v1.0"


# ---------------------------------------------------------------------------
# get_release: Incoming query — assert return value
# ---------------------------------------------------------------------------


def test_get_release_returns_release(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)
    created = service.create_release(pid, "v1.0")

    result = service.get_release(created.id)

    assert result is not None
    assert result.name == "v1.0"


def test_get_release_returns_none_for_missing(tmp_db):
    service = ReleaseService(db_path=tmp_db)

    result = service.get_release(9999)

    assert result is None


# ---------------------------------------------------------------------------
# delete_release: Incoming command — assert state change
# ---------------------------------------------------------------------------


def test_delete_release_removes_from_database(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)
    release = service.create_release(pid, "v1.0")

    service.delete_release(release.id)

    assert service.get_release(release.id) is None


def test_delete_release_removes_associated_documents(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)
    release = service.create_release(pid, "v1.0")
    service.save_documents(release.id, {"Doc A", "Doc B"})

    service.delete_release(release.id)

    with get_db(tmp_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM release_documents WHERE release_id = ?",
            (release.id,),
        ).fetchone()[0]
    assert count == 0


# ---------------------------------------------------------------------------
# save_documents / get_selected_documents: Incoming command + query
# ---------------------------------------------------------------------------


def test_save_and_get_documents(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)
    release = service.create_release(pid, "v1.0")

    service.save_documents(release.id, {"Doc A", "Doc B", "Doc C"})

    result = service.get_selected_documents(release.id)
    assert result == {"Doc A", "Doc B", "Doc C"}


def test_save_documents_replaces_previous_selection(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)
    release = service.create_release(pid, "v1.0")
    service.save_documents(release.id, {"Doc A", "Doc B"})

    service.save_documents(release.id, {"Doc C"})

    result = service.get_selected_documents(release.id)
    assert result == {"Doc C"}


def test_get_selected_documents_returns_empty_when_none_selected(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)
    release = service.create_release(pid, "v1.0")

    result = service.get_selected_documents(release.id)

    assert result == set()


# ---------------------------------------------------------------------------
# reconcile_documents: Incoming command — assert state change + return
# ---------------------------------------------------------------------------


def test_reconcile_removes_stale_documents(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)
    release = service.create_release(pid, "v1.0")
    service.save_documents(release.id, {"Doc A", "Doc B", "Doc C"})

    valid, stale = service.reconcile_documents(release.id, {"Doc A", "Doc C"})

    assert valid == {"Doc A", "Doc C"}
    assert stale == ["Doc B"]
    assert service.get_selected_documents(release.id) == {"Doc A", "Doc C"}


def test_reconcile_returns_empty_stale_when_all_valid(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)
    release = service.create_release(pid, "v1.0")
    service.save_documents(release.id, {"Doc A", "Doc B"})

    valid, stale = service.reconcile_documents(release.id, {"Doc A", "Doc B", "Doc C"})

    assert valid == {"Doc A", "Doc B"}
    assert stale == []


def test_reconcile_with_no_selected_documents(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)
    release = service.create_release(pid, "v1.0")

    valid, stale = service.reconcile_documents(release.id, {"Doc A"})

    assert valid == set()
    assert stale == []


# ---------------------------------------------------------------------------
# lock_release / unlock_release: Incoming command — assert state change
# ---------------------------------------------------------------------------


def test_lock_release_sets_locked_and_stores_snapshot(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)
    release = service.create_release(pid, "v1.0")
    snapshot = {"Doc A": "3", "Doc B": None}

    service.lock_release(release.id, snapshot)

    updated = service.get_release(release.id)
    assert updated.locked is True
    assert updated.version_snapshot == {"Doc A": "3", "Doc B": None}


def test_unlock_release_clears_locked_but_preserves_snapshot(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)
    release = service.create_release(pid, "v1.0")
    service.lock_release(release.id, {"Doc A": "3"})

    service.unlock_release(release.id)

    updated = service.get_release(release.id)
    assert updated.locked is False
    assert updated.version_snapshot == {"Doc A": "3"}


def test_get_version_snapshot_returns_snapshot(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)
    release = service.create_release(pid, "v1.0")
    service.lock_release(release.id, {"Doc A": "3"})

    result = service.get_version_snapshot(release.id)

    assert result == {"Doc A": "3"}


def test_get_version_snapshot_returns_none_for_missing_release(tmp_db):
    service = ReleaseService(db_path=tmp_db)

    result = service.get_version_snapshot(9999)

    assert result is None


def test_get_version_snapshot_returns_none_before_lock(tmp_db):
    pid = _insert_project(tmp_db)
    service = ReleaseService(db_path=tmp_db)
    release = service.create_release(pid, "v1.0")

    result = service.get_version_snapshot(release.id)

    assert result is None


# ---------------------------------------------------------------------------
# compute_release_status: Pure computation — assert return value
# ---------------------------------------------------------------------------


def test_compute_release_status_published_when_version_changed():
    service = ReleaseService(db_path=":memory:")
    snapshot = {"Doc A": "3", "Doc B": "1"}
    current = {"Doc A": "4", "Doc B": "2"}

    result = service.compute_release_status(snapshot, current)

    assert result == [
        ("Doc A", ReleaseStatus.PUBLISHED),
        ("Doc B", ReleaseStatus.PUBLISHED),
    ]


def test_compute_release_status_pending_when_version_unchanged():
    service = ReleaseService(db_path=":memory:")
    snapshot = {"Doc A": "3", "Doc B": "1"}
    current = {"Doc A": "3", "Doc B": "1"}

    result = service.compute_release_status(snapshot, current)

    assert result == [
        ("Doc A", ReleaseStatus.PENDING),
        ("Doc B", ReleaseStatus.PENDING),
    ]


def test_compute_release_status_mixed():
    service = ReleaseService(db_path=":memory:")
    snapshot = {"Doc A": "3", "Doc B": "1"}
    current = {"Doc A": "4", "Doc B": "1"}

    result = service.compute_release_status(snapshot, current)

    assert result == [
        ("Doc A", ReleaseStatus.PUBLISHED),
        ("Doc B", ReleaseStatus.PENDING),
    ]


def test_compute_release_status_pending_when_snapshot_none_and_current_none():
    service = ReleaseService(db_path=":memory:")
    snapshot = {"Doc A": None}
    current = {"Doc A": None}

    result = service.compute_release_status(snapshot, current)

    assert result == [("Doc A", ReleaseStatus.PENDING)]


def test_compute_release_status_published_when_snapshot_none_and_current_has_version():
    service = ReleaseService(db_path=":memory:")
    snapshot = {"Doc A": None}
    current = {"Doc A": "1"}

    result = service.compute_release_status(snapshot, current)

    assert result == [("Doc A", ReleaseStatus.PUBLISHED)]


def test_compute_release_status_pending_when_doc_missing_from_current():
    service = ReleaseService(db_path=":memory:")
    snapshot = {"Doc A": "3"}
    current = {}

    result = service.compute_release_status(snapshot, current)

    assert result == [("Doc A", ReleaseStatus.PENDING)]
