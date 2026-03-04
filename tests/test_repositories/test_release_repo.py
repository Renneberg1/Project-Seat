"""Tests for ReleaseRepository — releases and release documents."""

from __future__ import annotations

import json

import pytest

from src.repositories.project_repo import ProjectRepository
from src.repositories.release_repo import ReleaseRepository


def _make_project(tmp_db: str) -> int:
    return ProjectRepository(tmp_db).create(jira_goal_key="PROG-1", name="Test")


class TestReleaseCreate:
    def test_create_release_returns_release(self, tmp_db: str):
        repo = ReleaseRepository(tmp_db)
        pid = _make_project(tmp_db)
        release = repo.create_release(pid, "v1.0")
        assert release.name == "v1.0"
        assert release.project_id == pid
        assert release.locked is False
        assert release.version_snapshot is None

    def test_create_release_unique_per_project(self, tmp_db: str):
        repo = ReleaseRepository(tmp_db)
        pid = _make_project(tmp_db)
        repo.create_release(pid, "v1.0")
        with pytest.raises(Exception):
            repo.create_release(pid, "v1.0")  # duplicate name in same project


class TestReleaseRead:
    def test_get_release_found(self, tmp_db: str):
        repo = ReleaseRepository(tmp_db)
        pid = _make_project(tmp_db)
        created = repo.create_release(pid, "v2.0")
        fetched = repo.get_release(created.id)
        assert fetched is not None
        assert fetched.name == "v2.0"

    def test_get_release_not_found(self, tmp_db: str):
        repo = ReleaseRepository(tmp_db)
        assert repo.get_release(9999) is None

    def test_list_releases(self, tmp_db: str):
        repo = ReleaseRepository(tmp_db)
        pid = _make_project(tmp_db)
        repo.create_release(pid, "v1.0")
        repo.create_release(pid, "v2.0")
        releases = repo.list_releases(pid)
        assert len(releases) == 2

    def test_list_releases_empty(self, tmp_db: str):
        repo = ReleaseRepository(tmp_db)
        assert repo.list_releases(9999) == []

    def test_get_project_id(self, tmp_db: str):
        repo = ReleaseRepository(tmp_db)
        pid = _make_project(tmp_db)
        r = repo.create_release(pid, "v1.0")
        assert repo.get_project_id(r.id) == pid

    def test_get_project_id_not_found(self, tmp_db: str):
        repo = ReleaseRepository(tmp_db)
        assert repo.get_project_id(9999) is None


class TestReleaseLockUnlock:
    def test_lock_release(self, tmp_db: str):
        repo = ReleaseRepository(tmp_db)
        pid = _make_project(tmp_db)
        r = repo.create_release(pid, "v1.0")
        snapshot = {"AIM": "v1.0", "CTCV": "v1.0"}
        repo.lock_release(r.id, json.dumps(snapshot))
        locked = repo.get_release(r.id)
        assert locked.locked is True
        assert locked.version_snapshot == snapshot

    def test_unlock_release(self, tmp_db: str):
        repo = ReleaseRepository(tmp_db)
        pid = _make_project(tmp_db)
        r = repo.create_release(pid, "v1.0")
        repo.lock_release(r.id, '{"x":"y"}')
        repo.unlock_release(r.id)
        assert repo.get_release(r.id).locked is False


class TestReleaseDelete:
    def test_delete_release(self, tmp_db: str):
        repo = ReleaseRepository(tmp_db)
        pid = _make_project(tmp_db)
        r = repo.create_release(pid, "v1.0")
        repo.delete_release(r.id)
        assert repo.get_release(r.id) is None

    def test_delete_release_cascades_documents(self, tmp_db: str):
        repo = ReleaseRepository(tmp_db)
        pid = _make_project(tmp_db)
        r = repo.create_release(pid, "v1.0")
        repo.save_documents(r.id, {"Doc A", "Doc B"})
        repo.delete_release(r.id)
        assert repo.get_selected_documents(r.id) == set()


class TestReleaseDocuments:
    def test_save_and_get_documents(self, tmp_db: str):
        repo = ReleaseRepository(tmp_db)
        pid = _make_project(tmp_db)
        r = repo.create_release(pid, "v1.0")
        repo.save_documents(r.id, {"Doc A", "Doc B", "Doc C"})
        docs = repo.get_selected_documents(r.id)
        assert docs == {"Doc A", "Doc B", "Doc C"}

    def test_save_documents_replaces_previous(self, tmp_db: str):
        repo = ReleaseRepository(tmp_db)
        pid = _make_project(tmp_db)
        r = repo.create_release(pid, "v1.0")
        repo.save_documents(r.id, {"Old Doc"})
        repo.save_documents(r.id, {"New Doc"})
        assert repo.get_selected_documents(r.id) == {"New Doc"}

    def test_get_selected_documents_empty(self, tmp_db: str):
        repo = ReleaseRepository(tmp_db)
        pid = _make_project(tmp_db)
        r = repo.create_release(pid, "v1.0")
        assert repo.get_selected_documents(r.id) == set()

    def test_save_documents_empty_set(self, tmp_db: str):
        repo = ReleaseRepository(tmp_db)
        pid = _make_project(tmp_db)
        r = repo.create_release(pid, "v1.0")
        repo.save_documents(r.id, {"Doc A"})
        repo.save_documents(r.id, set())
        assert repo.get_selected_documents(r.id) == set()
