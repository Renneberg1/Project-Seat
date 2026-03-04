"""Tests for ZoomRepository — recordings, project mappings, aliases, config."""

from __future__ import annotations

import pytest

from src.repositories.project_repo import ProjectRepository
from src.repositories.zoom_repo import ZoomRepository


def _make_project(tmp_db: str, key: str = "PROG-1", name: str = "Test") -> int:
    return ProjectRepository(tmp_db).create(jira_goal_key=key, name=name)


def _insert_recording(repo: ZoomRepository, uuid: str = "uuid-1", **kw) -> int:
    defaults = dict(
        zoom_meeting_uuid=uuid,
        zoom_meeting_id="123456",
        topic="Sprint Planning",
        host_email="host@example.com",
        start_time="2026-01-15T10:00:00Z",
        duration_minutes=45,
        transcript_url="https://zoom.us/transcript/1",
        raw_metadata={"recording_id": "abc"},
    )
    defaults.update(kw)
    return repo.insert_recording(**defaults)


# ------------------------------------------------------------------
# zoom_recordings
# ------------------------------------------------------------------


class TestRecordingInsertAndGet:
    def test_insert_returns_id(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        rid = _insert_recording(repo)
        assert isinstance(rid, int) and rid >= 1

    def test_get_by_id(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        rid = _insert_recording(repo)
        rec = repo.get_by_id(rid)
        assert rec is not None
        assert rec.topic == "Sprint Planning"
        assert rec.host_email == "host@example.com"
        assert rec.duration_minutes == 45
        assert rec.processing_status == "new"
        assert rec.raw_metadata == {"recording_id": "abc"}

    def test_get_by_id_not_found(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        assert repo.get_by_id(9999) is None

    def test_get_by_uuid(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        _insert_recording(repo, uuid="unique-uuid")
        rec = repo.get_by_uuid("unique-uuid")
        assert rec is not None
        assert rec.zoom_meeting_uuid == "unique-uuid"

    def test_get_by_uuid_not_found(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        assert repo.get_by_uuid("nonexistent") is None

    def test_duplicate_uuid_raises(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        _insert_recording(repo, uuid="dup-uuid")
        with pytest.raises(Exception):
            _insert_recording(repo, uuid="dup-uuid")


class TestRecordingList:
    def test_list_all(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        _insert_recording(repo, uuid="u1")
        _insert_recording(repo, uuid="u2")
        assert len(repo.list_all()) == 2

    def test_list_all_empty(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        assert repo.list_all() == []

    def test_list_by_status(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        rid1 = _insert_recording(repo, uuid="u1")
        rid2 = _insert_recording(repo, uuid="u2")
        repo.update_status(rid1, "matched")
        assert len(repo.list_by_status("new")) == 1
        assert len(repo.list_by_status("matched")) == 1


class TestRecordingUpdateStatus:
    def test_update_status_basic(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        rid = _insert_recording(repo)
        repo.update_status(rid, "matched")
        assert repo.get_by_id(rid).processing_status == "matched"

    def test_update_status_with_match_method(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        rid = _insert_recording(repo)
        repo.update_status(rid, "matched", match_method="title")
        rec = repo.get_by_id(rid)
        assert rec.processing_status == "matched"
        assert rec.match_method == "title"

    def test_update_status_with_error(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        rid = _insert_recording(repo)
        repo.update_status(rid, "error", error_message="Download failed")
        rec = repo.get_by_id(rid)
        assert rec.processing_status == "error"
        assert rec.error_message == "Download failed"

    def test_dismiss_recording(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        rid = _insert_recording(repo)
        repo.dismiss_recording(rid)
        assert repo.get_by_id(rid).processing_status == "dismissed"


# ------------------------------------------------------------------
# project_meeting_map
# ------------------------------------------------------------------


class TestProjectMappings:
    def test_add_and_get_mapping(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        pid = _make_project(tmp_db)
        rid = _insert_recording(repo)
        repo.add_project_mapping(rid, pid)
        mappings = repo.get_mappings_for_recording(rid)
        assert len(mappings) == 1
        assert mappings[0].project_id == pid
        assert mappings[0].analysis_status == "pending"

    def test_add_mapping_with_transcript(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        pid = _make_project(tmp_db)
        rid = _insert_recording(repo)
        repo.add_project_mapping(rid, pid, transcript_id=99)
        assert repo.get_mappings_for_recording(rid)[0].transcript_id == 99

    def test_add_duplicate_mapping_ignored(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        pid = _make_project(tmp_db)
        rid = _insert_recording(repo)
        repo.add_project_mapping(rid, pid)
        repo.add_project_mapping(rid, pid)  # INSERT OR IGNORE
        assert len(repo.get_mappings_for_recording(rid)) == 1

    def test_get_project_ids_for_recording(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        pid1 = _make_project(tmp_db, key="PROG-1", name="P1")
        pid2 = _make_project(tmp_db, key="PROG-2", name="P2")
        rid = _insert_recording(repo)
        repo.add_project_mapping(rid, pid1)
        repo.add_project_mapping(rid, pid2)
        project_ids = repo.get_project_ids_for_recording(rid)
        assert set(project_ids) == {pid1, pid2}

    def test_update_mapping_transcript(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        pid = _make_project(tmp_db)
        rid = _insert_recording(repo)
        repo.add_project_mapping(rid, pid)
        repo.update_mapping_transcript(rid, pid, transcript_id=42)
        m = repo.get_mappings_for_recording(rid)[0]
        assert m.transcript_id == 42
        assert m.analysis_status == "complete"

    def test_update_mapping_status(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        pid = _make_project(tmp_db)
        rid = _insert_recording(repo)
        repo.add_project_mapping(rid, pid)
        repo.update_mapping_status(rid, pid, "error")
        assert repo.get_mappings_for_recording(rid)[0].analysis_status == "error"

    def test_get_mappings_empty(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        assert repo.get_mappings_for_recording(9999) == []


# ------------------------------------------------------------------
# project_aliases
# ------------------------------------------------------------------


class TestAliases:
    def test_set_and_get_aliases(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        pid = _make_project(tmp_db)
        repo.set_aliases(pid, ["Alpha", "Beta"])
        aliases = repo.get_aliases(pid)
        assert set(aliases) == {"Alpha", "Beta"}

    def test_set_aliases_replaces(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        pid = _make_project(tmp_db)
        repo.set_aliases(pid, ["Old"])
        repo.set_aliases(pid, ["New"])
        assert repo.get_aliases(pid) == ["New"]

    def test_set_aliases_strips_whitespace(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        pid = _make_project(tmp_db)
        repo.set_aliases(pid, ["  Alpha  ", ""])
        assert repo.get_aliases(pid) == ["Alpha"]

    def test_get_aliases_empty(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        pid = _make_project(tmp_db)
        assert repo.get_aliases(pid) == []

    def test_get_all_aliases(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        pid1 = _make_project(tmp_db, key="PROG-1", name="P1")
        pid2 = _make_project(tmp_db, key="PROG-2", name="P2")
        repo.set_aliases(pid1, ["A1"])
        repo.set_aliases(pid2, ["A2", "A3"])
        all_aliases = repo.get_all_aliases()
        assert set(all_aliases[pid1]) == {"A1"}
        assert set(all_aliases[pid2]) == {"A2", "A3"}


# ------------------------------------------------------------------
# config helpers
# ------------------------------------------------------------------


class TestConfig:
    def test_set_and_get_config(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        repo.set_config("zoom_token", "abc123")
        assert repo.get_config("zoom_token") == "abc123"

    def test_get_config_not_found(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        assert repo.get_config("nonexistent") is None

    def test_set_config_upserts(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        repo.set_config("key", "v1")
        repo.set_config("key", "v2")
        assert repo.get_config("key") == "v2"

    def test_delete_config(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        repo.set_config("key", "val")
        repo.delete_config("key")
        assert repo.get_config("key") is None

    def test_last_sync_time(self, tmp_db: str):
        repo = ZoomRepository(tmp_db)
        assert repo.get_last_sync_time() is None
        repo.set_last_sync_time("2026-01-15T10:00:00Z")
        assert repo.get_last_sync_time() == "2026-01-15T10:00:00Z"
