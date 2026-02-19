"""Tests for import project routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.database import get_db
from src.services.import_project import DetectedPage, ImportPreview


def _insert_project(db_path: str, name: str = "Test", goal_key: str = "PROG-100") -> int:
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase) VALUES (?, ?, ?, ?)",
            (goal_key, name, "active", "planning"),
        )
        conn.commit()
        return cursor.lastrowid


class TestImportForm:
    def test_get_returns_200(self, client) -> None:
        resp = client.get("/import/")
        assert resp.status_code == 200
        assert "goal_key" in resp.text

    def test_form_has_htmx_attributes(self, client) -> None:
        resp = client.get("/import/")
        assert "hx-post" in resp.text
        assert "/import/fetch" in resp.text


class TestImportFetch:
    def test_returns_confirm_partial(self, client) -> None:
        preview = ImportPreview(
            goal_key="PROG-256",
            goal_summary="HOP Drop 2",
            detected_pages=[
                DetectedPage(page_id="100", url="https://x/pages/100/Charter", slug="Charter"),
                DetectedPage(page_id="200", url="https://x/pages/200/Scope", slug="Scope"),
            ],
            charter_id="100",
            xft_id="200",
        )

        with patch("src.web.routes.import_project.ImportService") as MockSvc:
            instance = MockSvc.return_value
            instance.fetch_preview = AsyncMock(return_value=preview)

            resp = client.post("/import/fetch", data={"goal_key": "PROG-256"})

        assert resp.status_code == 200
        assert "HOP Drop 2" in resp.text
        assert "100" in resp.text
        assert "200" in resp.text
        assert "Charter" in resp.text

    def test_handles_connector_error(self, client) -> None:
        from src.connectors.base import ConnectorError

        with patch("src.web.routes.import_project.ImportService") as MockSvc:
            instance = MockSvc.return_value
            instance.fetch_preview = AsyncMock(side_effect=ConnectorError(404, "Not found"))

            resp = client.post("/import/fetch", data={"goal_key": "PROG-999"})

        assert resp.status_code == 200
        assert "Failed to fetch" in resp.text

    def test_uppercases_key(self, client) -> None:
        preview = ImportPreview(
            goal_key="PROG-256",
            goal_summary="Test",
        )
        with patch("src.web.routes.import_project.ImportService") as MockSvc:
            instance = MockSvc.return_value
            instance.fetch_preview = AsyncMock(return_value=preview)

            client.post("/import/fetch", data={"goal_key": "prog-256"})

            instance.fetch_preview.assert_called_once_with("PROG-256")


class TestImportSave:
    def test_saves_and_redirects(self, client, tmp_db: str) -> None:
        with patch("src.web.routes.import_project.ImportService") as MockSvc:
            instance = MockSvc.return_value
            instance.save_project.return_value = 42

            resp = client.post(
                "/import/save",
                data={
                    "goal_key": "PROG-256",
                    "name": "HOP Drop 2",
                    "charter_id": "100",
                    "xft_id": "200",
                },
                follow_redirects=False,
            )

        assert resp.status_code == 303
        assert "/project/42/dashboard" in resp.headers["location"]

    def test_duplicate_shows_error(self, client, tmp_db: str) -> None:
        with patch("src.web.routes.import_project.ImportService") as MockSvc:
            instance = MockSvc.return_value
            instance.save_project.side_effect = ValueError("already exists (id=1)")

            resp = client.post(
                "/import/save",
                data={
                    "goal_key": "PROG-256",
                    "name": "HOP Drop 2",
                },
            )

        assert resp.status_code == 200
        assert "already exists" in resp.text

    def test_empty_page_ids_saved_as_none(self, client, tmp_db: str) -> None:
        with patch("src.web.routes.import_project.ImportService") as MockSvc:
            instance = MockSvc.return_value
            instance.save_project.return_value = 1

            client.post(
                "/import/save",
                data={
                    "goal_key": "PROG-300",
                    "name": "Minimal",
                    "charter_id": "",
                    "xft_id": "",
                },
                follow_redirects=False,
            )

            instance.save_project.assert_called_once_with(
                goal_key="PROG-300",
                name="Minimal",
                charter_id=None,
                xft_id=None,
            )


class TestDeleteProject:
    def test_delete_returns_redirect_header(self, client, tmp_db: str) -> None:
        pid = _insert_project(tmp_db, "Alpha", "PROG-1")

        with patch("src.web.routes.project.ImportService") as MockSvc:
            instance = MockSvc.return_value

            resp = client.delete(f"/project/{pid}")

        assert resp.status_code == 200
        assert resp.headers.get("HX-Redirect") == "/phases/"
        instance.delete_project.assert_called_once_with(pid)

    def test_delete_via_dashboard(self, client, tmp_db: str) -> None:
        """Verify the danger zone button target exists on dashboard."""
        from src.models.dashboard import ProjectSummary
        from src.models.dhf import DHFSummary
        from src.models.jira import JiraIssue
        from src.models.project import Project

        pid = _insert_project(tmp_db, "Alpha", "PROG-1")
        project = Project(
            id=pid, jira_goal_key="PROG-1", name="Alpha",
            confluence_charter_id=None, confluence_xft_id=None,
            status="active", phase="planning", created_at="2026-01-01",
        )
        goal = JiraIssue(
            id="1", key="PROG-1", summary="Alpha", status="In Progress",
            issue_type="Goal", project_key="PROG",
            labels=[], parent_key=None, fix_versions=[], due_date=None,
            description_adf=None,
        )
        summary = ProjectSummary(
            project=project, goal=goal,
            risk_count=0, open_risk_count=0, decision_count=0, initiative_count=0,
            error=None,
        )
        dhf = DHFSummary(total_count=0, released_count=0, draft_update_count=0, in_draft_count=0)

        with patch("src.web.routes.project.DashboardService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_project_by_id = lambda x: project
            instance.get_project_summary = AsyncMock(return_value=summary)
            instance.list_projects = lambda: [project]
            with patch("src.web.routes.project.DHFService") as MockDHF:
                MockDHF.return_value.get_dhf_summary = AsyncMock(return_value=dhf)
                with patch("src.web.routes.project.ApprovalEngine") as MockEng:
                    MockEng.return_value.list_all = lambda project_id=None: []
                    resp = client.get(f"/project/{pid}/dashboard")

        assert resp.status_code == 200
        assert "Danger Zone" in resp.text
        assert "Remove from Seat" in resp.text
        assert f'hx-delete="/project/{pid}"' in resp.text
