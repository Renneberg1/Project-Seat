"""Tests for project-scoped routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.database import get_db
from src.models.dashboard import InitiativeDetail, InitiativeSummary, EpicWithTasks, ProjectSummary
from src.models.dhf import DHFDocument, DHFSummary, DocumentStatus
from src.models.jira import JiraIssue
from src.models.project import Project


def _insert_project(db_path: str, name: str = "Test Project", goal_key: str = "PROG-100", phase: str = "planning") -> int:
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase) VALUES (?, ?, ?, ?)",
            (goal_key, name, "active", phase),
        )
        conn.commit()
        return cursor.lastrowid


def _make_project(pid: int = 1, name: str = "Test Project", goal_key: str = "PROG-100") -> Project:
    return Project(
        id=pid, jira_goal_key=goal_key, name=name,
        confluence_charter_id=None, confluence_xft_id=None,
        status="active", phase="planning", created_at="2026-01-01",
        dhf_draft_root_id=None, dhf_released_root_id=None,
    )


def _make_dhf_summary() -> DHFSummary:
    return DHFSummary(total_count=0, released_count=0, draft_update_count=0, in_draft_count=0)


def _make_issue(key: str = "AIM-100", summary: str = "Test Issue", status: str = "In Progress", issue_type: str = "Initiative") -> JiraIssue:
    return JiraIssue(
        id="10000", key=key, summary=summary, status=status,
        issue_type=issue_type, project_key="AIM",
        labels=[], parent_key=None, fix_versions=[], due_date=None,
        description_adf=None,
    )


def _make_summary(project: Project) -> ProjectSummary:
    goal = _make_issue(key=project.jira_goal_key, summary=project.name, issue_type="Goal")
    return ProjectSummary(
        project=project, goal=goal,
        risk_count=2, open_risk_count=1, decision_count=1, initiative_count=3,
        error=None,
    )


class TestProjectDashboard:
    def test_returns_200(self, client, tmp_db: str) -> None:
        pid = _insert_project(tmp_db, "Alpha", "PROG-1")
        project = _make_project(pid, "Alpha", "PROG-1")

        with patch("src.web.routes.project.DashboardService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_project_by_id = lambda x: project
            instance.get_project_summary = AsyncMock(return_value=_make_summary(project))
            instance.list_projects = lambda: [project]
            with patch("src.web.routes.project.DHFService") as MockDHF:
                MockDHF.return_value.get_dhf_summary = AsyncMock(return_value=_make_dhf_summary())
                with patch("src.web.routes.project.ApprovalEngine") as MockEng:
                    MockEng.return_value.list_all = lambda project_id=None: []
                    resp = client.get(f"/project/{pid}/dashboard")

        assert resp.status_code == 200
        assert "Alpha" in resp.text

    def test_not_found_returns_404(self, client) -> None:
        with patch("src.web.routes.project.DashboardService") as MockSvc:
            MockSvc.return_value.get_project_by_id = lambda x: None
            resp = client.get("/project/999/dashboard")
        assert resp.status_code == 404

    def test_sets_cookie(self, client, tmp_db: str) -> None:
        pid = _insert_project(tmp_db, "Alpha", "PROG-1")
        project = _make_project(pid, "Alpha", "PROG-1")

        with patch("src.web.routes.project.DashboardService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_project_by_id = lambda x: project
            instance.get_project_summary = AsyncMock(return_value=_make_summary(project))
            instance.list_projects = lambda: [project]
            with patch("src.web.routes.project.DHFService") as MockDHF:
                MockDHF.return_value.get_dhf_summary = AsyncMock(return_value=_make_dhf_summary())
                with patch("src.web.routes.project.ApprovalEngine") as MockEng:
                    MockEng.return_value.list_all = lambda project_id=None: []
                    resp = client.get(f"/project/{pid}/dashboard")

        assert "seat_selected_project" in resp.cookies
        assert resp.cookies["seat_selected_project"] == str(pid)

    def test_dashboard_shows_dhf_counts(self, client, tmp_db: str) -> None:
        pid = _insert_project(tmp_db, "Alpha", "PROG-1")
        project = _make_project(pid, "Alpha", "PROG-1")

        dhf = DHFSummary(total_count=5, released_count=2, draft_update_count=2, in_draft_count=1)
        with patch("src.web.routes.project.DashboardService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_project_by_id = lambda x: project
            instance.get_project_summary = AsyncMock(return_value=_make_summary(project))
            instance.list_projects = lambda: [project]
            with patch("src.web.routes.project.DHFService") as MockDHF:
                MockDHF.return_value.get_dhf_summary = AsyncMock(return_value=dhf)
                with patch("src.web.routes.project.ApprovalEngine") as MockEng:
                    MockEng.return_value.list_all = lambda project_id=None: []
                    resp = client.get(f"/project/{pid}/dashboard")

        assert resp.status_code == 200
        assert "2 Released" in resp.text
        assert "2 Draft Update" in resp.text
        assert "1 In Draft" in resp.text


class TestProjectFeatures:
    def test_returns_200_with_initiatives(self, client, tmp_db: str) -> None:
        pid = _insert_project(tmp_db, "Alpha", "PROG-1")
        project = _make_project(pid, "Alpha", "PROG-1")
        init_summary = InitiativeSummary(
            issue=_make_issue("AIM-100", "Feature A"),
            epic_count=3, task_count=10, done_epic_count=1, done_task_count=5,
        )

        with patch("src.web.routes.project.DashboardService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_project_by_id = lambda x: project
            instance.get_initiatives = AsyncMock(return_value=[init_summary])
            instance.list_projects = lambda: [project]
            resp = client.get(f"/project/{pid}/features")

        assert resp.status_code == 200
        assert "AIM-100" in resp.text
        assert "Feature A" in resp.text

    def test_empty_initiatives(self, client, tmp_db: str) -> None:
        pid = _insert_project(tmp_db, "Alpha", "PROG-1")
        project = _make_project(pid, "Alpha", "PROG-1")

        with patch("src.web.routes.project.DashboardService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_project_by_id = lambda x: project
            instance.get_initiatives = AsyncMock(return_value=[])
            instance.list_projects = lambda: [project]
            resp = client.get(f"/project/{pid}/features")

        assert resp.status_code == 200
        assert "No initiatives found" in resp.text


class TestInitiativeDetail:
    def test_returns_200_with_epics(self, client, tmp_db: str) -> None:
        pid = _insert_project(tmp_db, "Alpha", "PROG-1")
        project = _make_project(pid, "Alpha", "PROG-1")
        detail = InitiativeDetail(
            issue=_make_issue("AIM-100", "Feature A"),
            epics=[
                EpicWithTasks(
                    issue=_make_issue("AIM-200", "Epic 1", issue_type="Epic"),
                    tasks=[_make_issue("AIM-300", "Task 1", issue_type="Task")],
                ),
            ],
        )

        with patch("src.web.routes.project.DashboardService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_project_by_id = lambda x: project
            instance.get_initiative_detail = AsyncMock(return_value=detail)
            instance.list_projects = lambda: [project]
            resp = client.get(f"/project/{pid}/features/AIM-100")

        assert resp.status_code == 200
        assert "AIM-100" in resp.text
        assert "Epic 1" in resp.text
        assert "Task 1" in resp.text

    def test_initiative_not_found(self, client, tmp_db: str) -> None:
        pid = _insert_project(tmp_db, "Alpha", "PROG-1")
        project = _make_project(pid, "Alpha", "PROG-1")

        with patch("src.web.routes.project.DashboardService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_project_by_id = lambda x: project
            instance.get_initiative_detail = AsyncMock(return_value=None)
            instance.list_projects = lambda: [project]
            resp = client.get(f"/project/{pid}/features/FAKE-999")

        assert resp.status_code == 404


class TestProjectDocuments:
    def test_returns_200_no_config(self, client, tmp_db: str) -> None:
        """Without DHF config, shows the configuration form."""
        pid = _insert_project(tmp_db, "Alpha", "PROG-1")
        project = _make_project(pid, "Alpha", "PROG-1")

        with patch("src.web.routes.project.DashboardService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_project_by_id = lambda x: project
            instance.list_projects = lambda: [project]
            resp = client.get(f"/project/{pid}/documents")

        assert resp.status_code == 200
        assert "Configure DHF Tracking" in resp.text

    def test_returns_200_with_documents(self, client, tmp_db: str) -> None:
        pid = _insert_project(tmp_db, "Alpha", "PROG-1")
        project = _make_project(pid, "Alpha", "PROG-1")
        project.dhf_draft_root_id = "100"
        project.dhf_released_root_id = "200"

        docs = [
            DHFDocument("Plan A", "Risk", "1", "2", DocumentStatus.DRAFT_UPDATE, "2026-01-01", "Jane", "https://x"),
            DHFDocument("Plan B", "Design", None, "1", DocumentStatus.IN_DRAFT, "2026-01-02", "Bob", "https://y"),
        ]

        with patch("src.web.routes.project.DashboardService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_project_by_id = lambda x: project
            instance.list_projects = lambda: [project]
            with patch("src.web.routes.project.DHFService") as MockDHF:
                MockDHF.return_value.get_dhf_table = AsyncMock(return_value=(docs, ["Design", "Risk"]))
                resp = client.get(f"/project/{pid}/documents")

        assert resp.status_code == 200
        assert "Plan A" in resp.text
        assert "Plan B" in resp.text

    def test_area_filter(self, client, tmp_db: str) -> None:
        pid = _insert_project(tmp_db, "Alpha", "PROG-1")
        project = _make_project(pid, "Alpha", "PROG-1")
        project.dhf_draft_root_id = "100"
        project.dhf_released_root_id = "200"

        docs = [
            DHFDocument("Plan A", "Risk", "1", None, DocumentStatus.RELEASED, "", "", ""),
            DHFDocument("Plan B", "Design", None, "1", DocumentStatus.IN_DRAFT, "", "", ""),
        ]

        with patch("src.web.routes.project.DashboardService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_project_by_id = lambda x: project
            instance.list_projects = lambda: [project]
            with patch("src.web.routes.project.DHFService") as MockDHF:
                MockDHF.return_value.get_dhf_table = AsyncMock(return_value=(docs, ["Design", "Risk"]))
                resp = client.get(f"/project/{pid}/documents?area=Risk")

        assert resp.status_code == 200
        assert "Plan A" in resp.text
        assert "Plan B" not in resp.text

    def test_save_config_redirects(self, client, tmp_db: str) -> None:
        pid = _insert_project(tmp_db, "Alpha", "PROG-1")

        resp = client.post(
            f"/project/{pid}/documents/config",
            data={"dhf_draft_root_id": "111", "dhf_released_root_id": "222"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert f"/project/{pid}/documents" in resp.headers["location"]

        # Verify saved in DB
        with get_db(tmp_db) as conn:
            row = conn.execute("SELECT dhf_draft_root_id, dhf_released_root_id FROM projects WHERE id = ?", (pid,)).fetchone()
        assert row["dhf_draft_root_id"] == "111"
        assert row["dhf_released_root_id"] == "222"


class TestProjectApprovals:
    def test_returns_200(self, client, tmp_db: str) -> None:
        pid = _insert_project(tmp_db, "Alpha", "PROG-1")
        project = _make_project(pid, "Alpha", "PROG-1")

        with patch("src.web.routes.project.DashboardService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_project_by_id = lambda x: project
            instance.list_projects = lambda: [project]
            with patch("src.web.routes.project.ApprovalEngine") as MockEng:
                eng_instance = MockEng.return_value
                eng_instance.list_pending = lambda project_id=None: []
                eng_instance.list_all = lambda project_id=None: []
                resp = client.get(f"/project/{pid}/approvals")

        assert resp.status_code == 200
        assert "Approvals" in resp.text
