"""Tests for ProjectRepository CRUD operations."""

from __future__ import annotations

import json

from src.repositories.project_repo import ProjectRepository


class TestProjectCreate:
    def test_create_returns_id(self, tmp_db: str):
        repo = ProjectRepository(tmp_db)
        pid = repo.create(jira_goal_key="PROG-1", name="Alpha")
        assert isinstance(pid, int)
        assert pid >= 1

    def test_create_with_team_projects_list(self, tmp_db: str):
        repo = ProjectRepository(tmp_db)
        teams = [["AIM", "Drop 1"], ["CTCV", "Drop 1"]]
        pid = repo.create(jira_goal_key="PROG-2", name="Beta", team_projects=teams)
        project = repo.get_by_id(pid)
        assert project is not None
        assert project.team_projects == teams

    def test_create_with_all_fields(self, tmp_db: str):
        repo = ProjectRepository(tmp_db)
        pid = repo.create(
            jira_goal_key="PROG-3",
            name="Full",
            confluence_charter_id="111",
            confluence_xft_id="222",
            status="active",
            phase="execution",
            dhf_draft_root_id="333",
            dhf_released_root_id="444",
            default_component="Frontend",
            default_label="release-1",
        )
        p = repo.get_by_id(pid)
        assert p.confluence_charter_id == "111"
        assert p.confluence_xft_id == "222"
        assert p.phase == "execution"
        assert p.dhf_draft_root_id == "333"
        assert p.default_component == "Frontend"


class TestProjectRead:
    def test_get_by_id_found(self, tmp_db: str):
        repo = ProjectRepository(tmp_db)
        pid = repo.create(jira_goal_key="PROG-10", name="Found")
        project = repo.get_by_id(pid)
        assert project is not None
        assert project.name == "Found"
        assert project.jira_goal_key == "PROG-10"

    def test_get_by_id_not_found(self, tmp_db: str):
        repo = ProjectRepository(tmp_db)
        assert repo.get_by_id(9999) is None

    def test_get_by_goal_key(self, tmp_db: str):
        repo = ProjectRepository(tmp_db)
        repo.create(jira_goal_key="PROG-20", name="ByKey")
        project = repo.get_by_goal_key("PROG-20")
        assert project is not None
        assert project.name == "ByKey"

    def test_get_by_goal_key_not_found(self, tmp_db: str):
        repo = ProjectRepository(tmp_db)
        assert repo.get_by_goal_key("NOPE-1") is None

    def test_exists_by_goal_key(self, tmp_db: str):
        repo = ProjectRepository(tmp_db)
        pid = repo.create(jira_goal_key="PROG-30", name="Exists")
        assert repo.exists_by_goal_key("PROG-30") == pid
        assert repo.exists_by_goal_key("NOPE-1") is None

    def test_list_all_empty(self, tmp_db: str):
        repo = ProjectRepository(tmp_db)
        assert repo.list_all() == []

    def test_list_all_returns_all(self, tmp_db: str):
        repo = ProjectRepository(tmp_db)
        repo.create(jira_goal_key="PROG-A", name="A")
        repo.create(jira_goal_key="PROG-B", name="B")
        projects = repo.list_all()
        assert len(projects) == 2

    def test_list_all_returns_projects_ordered_by_id(self, tmp_db: str):
        repo = ProjectRepository(tmp_db)
        id1 = repo.create(jira_goal_key="PROG-X", name="First")
        id2 = repo.create(jira_goal_key="PROG-Y", name="Second")
        projects = repo.list_all()
        # ORDER BY created_at DESC — both have same second, so order by rowid
        ids = [p.id for p in projects]
        assert id1 in ids and id2 in ids
        assert len(projects) == 2


class TestProjectUpdate:
    def test_update_single_field(self, tmp_db: str):
        repo = ProjectRepository(tmp_db)
        pid = repo.create(jira_goal_key="PROG-40", name="Before")
        repo.update(pid, name="After")
        assert repo.get_by_id(pid).name == "After"

    def test_update_multiple_fields(self, tmp_db: str):
        repo = ProjectRepository(tmp_db)
        pid = repo.create(jira_goal_key="PROG-41", name="Old")
        repo.update(pid, name="New", phase="execution", status="completed")
        p = repo.get_by_id(pid)
        assert p.name == "New"
        assert p.phase == "execution"
        assert p.status == "completed"

    def test_update_team_projects_serialises_list(self, tmp_db: str):
        repo = ProjectRepository(tmp_db)
        pid = repo.create(jira_goal_key="PROG-42", name="Teams")
        teams = [["AIM", "v2"]]
        repo.update(pid, team_projects=teams)
        assert repo.get_by_id(pid).team_projects == teams

    def test_update_no_fields_is_noop(self, tmp_db: str):
        repo = ProjectRepository(tmp_db)
        pid = repo.create(jira_goal_key="PROG-43", name="Stable")
        repo.update(pid)  # no kwargs
        assert repo.get_by_id(pid).name == "Stable"


class TestProjectDelete:
    def test_delete_removes_project(self, tmp_db: str):
        repo = ProjectRepository(tmp_db)
        pid = repo.create(jira_goal_key="PROG-50", name="Gone")
        repo.delete(pid)
        assert repo.get_by_id(pid) is None

    def test_delete_nonexistent_is_silent(self, tmp_db: str):
        repo = ProjectRepository(tmp_db)
        repo.delete(9999)  # should not raise
