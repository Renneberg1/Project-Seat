"""Tests for project-scoped routes — dashboard, features, documents, approvals."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.cache import cache
from src.database import get_db
from src.models.dashboard import EpicWithTasks, InitiativeDetail, InitiativeSummary, ProductIdeaSummary, ProjectSummary
from src.models.dhf import DHFDocument, DHFSummary, DocumentStatus
from src.models.jira import JiraIssue
from src.models.project import Project


def _insert_project(db_path, name="Test Project", goal_key="PROG-100", phase="planning"):
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase) VALUES (?, ?, ?, ?)",
            (goal_key, name, "active", phase),
        )
        conn.commit()
        return cursor.lastrowid


def _make_project(pid=1, name="Test Project", goal_key="PROG-100"):
    return Project(
        id=pid, jira_goal_key=goal_key, name=name,
        confluence_charter_id=None, confluence_xft_id=None,
        status="active", phase="planning", created_at="2026-01-01",
        dhf_draft_root_id=None, dhf_released_root_id=None,
    )


def _make_dhf_summary():
    return DHFSummary(total_count=0, released_count=0, draft_update_count=0, in_draft_count=0)


def _make_issue(key="AIM-100", summary="Test Issue", status="In Progress", issue_type="Initiative"):
    return JiraIssue(
        id="10000", key=key, summary=summary, status=status,
        issue_type=issue_type, project_key="AIM",
        labels=[], parent_key=None, fix_versions=[], due_date=None,
        description_adf=None,
    )


def _make_summary(project):
    goal = _make_issue(key=project.jira_goal_key, summary=project.name, issue_type="Goal")
    return ProjectSummary(
        project=project, goal=goal,
        risk_count=2, open_risk_count=1, decision_count=1, initiative_count=3,
        error=None,
    )


def _patch_dashboard(project):
    """Return a patch context for DashboardService returning the given project."""
    mock = patch("src.web.routes.project.DashboardService")
    return mock, project


# ---------------------------------------------------------------------------
# GET /project/{id}/dashboard — project dashboard: Contract tests
# ---------------------------------------------------------------------------


def test_project_dashboard_returns_200(client, tmp_db):
    pid = _insert_project(tmp_db, "Alpha", "PROG-1")
    project = _make_project(pid, "Alpha", "PROG-1")
    empty_pi = ProductIdeaSummary(0, 0, 0, 0, 0, 0, 0)
    cache.clear()

    with patch("src.web.routes.project.DashboardService") as MockSvc:
        instance = MockSvc.return_value
        instance.get_project_by_id = lambda x: project
        instance.get_project_summary = AsyncMock(return_value=_make_summary(project))
        instance.get_product_ideas = AsyncMock(return_value=[])
        instance.summarise_product_ideas = lambda ideas: empty_pi
        instance.list_projects = lambda: [project]
        with patch("src.web.routes.project.DHFService") as MockDHF:
            MockDHF.return_value.get_dhf_table = AsyncMock(return_value=([], []))
            with patch("src.web.routes.project.ApprovalEngine") as MockEng:
                MockEng.return_value.list_all = lambda project_id=None: []

                result = client.get(f"/project/{pid}/dashboard")

    assert result.status_code == 200
    assert "Alpha" in result.text


def test_project_dashboard_not_found_returns_404(client):
    with patch("src.web.routes.project.DashboardService") as MockSvc:
        MockSvc.return_value.get_project_by_id = lambda x: None

        result = client.get("/project/999/dashboard")

    assert result.status_code == 404


def test_project_dashboard_sets_cookie(client, tmp_db):
    pid = _insert_project(tmp_db, "Alpha", "PROG-1")
    project = _make_project(pid, "Alpha", "PROG-1")
    empty_pi = ProductIdeaSummary(0, 0, 0, 0, 0, 0, 0)
    cache.clear()

    with patch("src.web.routes.project.DashboardService") as MockSvc:
        instance = MockSvc.return_value
        instance.get_project_by_id = lambda x: project
        instance.get_project_summary = AsyncMock(return_value=_make_summary(project))
        instance.get_product_ideas = AsyncMock(return_value=[])
        instance.summarise_product_ideas = lambda ideas: empty_pi
        instance.list_projects = lambda: [project]
        with patch("src.web.routes.project.DHFService") as MockDHF:
            MockDHF.return_value.get_dhf_table = AsyncMock(return_value=([], []))
            with patch("src.web.routes.project.ApprovalEngine") as MockEng:
                MockEng.return_value.list_all = lambda project_id=None: []

                result = client.get(f"/project/{pid}/dashboard")

    assert "seat_selected_project" in result.cookies
    assert result.cookies["seat_selected_project"] == str(pid)


def test_project_dashboard_shows_dhf_counts(client, tmp_db):
    pid = _insert_project(tmp_db, "Alpha", "PROG-1")
    project = _make_project(pid, "Alpha", "PROG-1")
    project.dhf_draft_root_id = "100"
    project.dhf_released_root_id = "200"
    # Provide actual DHFDocument objects so the route can compute summary locally
    dhf_docs = [
        DHFDocument("Doc A", "Risk", "1", None, DocumentStatus.RELEASED, "", "", ""),
        DHFDocument("Doc B", "Risk", "1", None, DocumentStatus.RELEASED, "", "", ""),
        DHFDocument("Doc C", "Design", "1", "2", DocumentStatus.DRAFT_UPDATE, "", "", ""),
        DHFDocument("Doc D", "Design", "1", "2", DocumentStatus.DRAFT_UPDATE, "", "", ""),
        DHFDocument("Doc E", "Test", None, "1", DocumentStatus.IN_DRAFT, "", "", ""),
    ]
    empty_pi = ProductIdeaSummary(0, 0, 0, 0, 0, 0, 0)
    cache.clear()

    with patch("src.web.routes.project.DashboardService") as MockSvc:
        instance = MockSvc.return_value
        instance.get_project_by_id = lambda x: project
        instance.get_project_summary = AsyncMock(return_value=_make_summary(project))
        instance.get_product_ideas = AsyncMock(return_value=[])
        instance.summarise_product_ideas = lambda ideas: empty_pi
        instance.list_projects = lambda: [project]
        with patch("src.web.routes.project.DHFService") as MockDHF:
            MockDHF.return_value.get_dhf_table = AsyncMock(return_value=(dhf_docs, ["Design", "Risk", "Test"]))
            with patch("src.web.routes.project.ApprovalEngine") as MockEng:
                MockEng.return_value.list_all = lambda project_id=None: []

                result = client.get(f"/project/{pid}/dashboard")

    assert result.status_code == 200
    assert "2 Released" in result.text
    assert "2 Draft Update" in result.text
    assert "1 In Draft" in result.text


# ---------------------------------------------------------------------------
# DELETE /project/{id} — delete project: Contract tests
# ---------------------------------------------------------------------------


def test_delete_project_returns_redirect_header(client, tmp_db):
    pid = _insert_project(tmp_db, "Alpha", "PROG-1")

    with patch("src.web.routes.project.ImportService") as MockSvc:
        instance = MockSvc.return_value

        result = client.delete(f"/project/{pid}")

    assert result.status_code == 200
    assert result.headers.get("HX-Redirect") == "/phases/"
    instance.delete_project.assert_called_once_with(pid)


def test_delete_project_danger_zone_exists_on_dashboard(client, tmp_db):
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
    empty_pi = ProductIdeaSummary(0, 0, 0, 0, 0, 0, 0)
    cache.clear()

    with patch("src.web.routes.project.DashboardService") as MockSvc:
        instance = MockSvc.return_value
        instance.get_project_by_id = lambda x: project
        instance.get_project_summary = AsyncMock(return_value=summary)
        instance.get_product_ideas = AsyncMock(return_value=[])
        instance.summarise_product_ideas = lambda ideas: empty_pi
        instance.list_projects = lambda: [project]
        with patch("src.web.routes.project.DHFService") as MockDHF:
            MockDHF.return_value.get_dhf_table = AsyncMock(return_value=([], []))
            with patch("src.web.routes.project.ApprovalEngine") as MockEng:
                MockEng.return_value.list_all = lambda project_id=None: []

                result = client.get(f"/project/{pid}/dashboard")

    assert result.status_code == 200
    assert "Danger Zone" in result.text
    assert "Remove from Seat" in result.text
    assert f'hx-delete="/project/{pid}"' in result.text


# ---------------------------------------------------------------------------
# GET /project/{id}/features — initiative list: Contract tests
# ---------------------------------------------------------------------------


def test_project_features_returns_200_with_initiatives(client, tmp_db):
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
        instance.get_product_ideas = AsyncMock(return_value=[])
        instance.list_projects = lambda: [project]

        result = client.get(f"/project/{pid}/features")

    assert result.status_code == 200
    assert "AIM-100" in result.text
    assert "Feature A" in result.text


def test_project_features_empty_shows_message(client, tmp_db):
    pid = _insert_project(tmp_db, "Alpha", "PROG-1")
    project = _make_project(pid, "Alpha", "PROG-1")

    with patch("src.web.routes.project.DashboardService") as MockSvc:
        instance = MockSvc.return_value
        instance.get_project_by_id = lambda x: project
        instance.get_initiatives = AsyncMock(return_value=[])
        instance.get_product_ideas = AsyncMock(return_value=[])
        instance.list_projects = lambda: [project]

        result = client.get(f"/project/{pid}/features")

    assert result.status_code == 200
    assert "No initiatives found" in result.text


# ---------------------------------------------------------------------------
# GET /project/{id}/features/{key} — initiative detail: Contract tests
# ---------------------------------------------------------------------------


def test_initiative_detail_returns_200_with_epics(client, tmp_db):
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

        result = client.get(f"/project/{pid}/features/AIM-100")

    assert result.status_code == 200
    assert "AIM-100" in result.text
    assert "Epic 1" in result.text
    assert "Task 1" in result.text


def test_initiative_detail_not_found_returns_404(client, tmp_db):
    pid = _insert_project(tmp_db, "Alpha", "PROG-1")
    project = _make_project(pid, "Alpha", "PROG-1")

    with patch("src.web.routes.project.DashboardService") as MockSvc:
        instance = MockSvc.return_value
        instance.get_project_by_id = lambda x: project
        instance.get_initiative_detail = AsyncMock(return_value=None)
        instance.list_projects = lambda: [project]

        result = client.get(f"/project/{pid}/features/FAKE-999")

    assert result.status_code == 404


# ---------------------------------------------------------------------------
# GET /project/{id}/documents — DHF documents: Contract tests
# ---------------------------------------------------------------------------


def test_project_documents_no_config_shows_configuration_form(client, tmp_db):
    pid = _insert_project(tmp_db, "Alpha", "PROG-1")
    project = _make_project(pid, "Alpha", "PROG-1")

    with patch("src.web.routes.project.DashboardService") as MockSvc:
        instance = MockSvc.return_value
        instance.get_project_by_id = lambda x: project
        instance.list_projects = lambda: [project]

        result = client.get(f"/project/{pid}/documents")

    assert result.status_code == 200
    assert "Configure DHF Tracking" in result.text


def test_project_documents_with_documents(client, tmp_db):
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

            result = client.get(f"/project/{pid}/documents")

    assert result.status_code == 200
    assert "Plan A" in result.text
    assert "Plan B" in result.text


def test_project_documents_area_filter(client, tmp_db):
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

            result = client.get(f"/project/{pid}/documents?area=Risk")

    assert result.status_code == 200
    assert "Plan A" in result.text
    assert "Plan B" not in result.text


# ---------------------------------------------------------------------------
# POST /project/{id}/documents/config — save DHF config: Contract tests
# ---------------------------------------------------------------------------


def test_save_dhf_config_redirects_to_documents(client, tmp_db):
    pid = _insert_project(tmp_db, "Alpha", "PROG-1")

    result = client.post(
        f"/project/{pid}/documents/config",
        data={"dhf_draft_root_id": "111", "dhf_released_root_id": "222"},
        follow_redirects=False,
    )

    assert result.status_code == 303
    assert f"/project/{pid}/documents" in result.headers["location"]
    with get_db(tmp_db) as conn:
        row = conn.execute("SELECT dhf_draft_root_id, dhf_released_root_id FROM projects WHERE id = ?", (pid,)).fetchone()
    assert row["dhf_draft_root_id"] == "111"
    assert row["dhf_released_root_id"] == "222"


# ---------------------------------------------------------------------------
# POST /project/{id}/releases — create release: Contract tests
# ---------------------------------------------------------------------------


def test_create_release_redirects_with_release_id(client, tmp_db):
    pid = _insert_project(tmp_db, "Alpha", "PROG-1")

    result = client.post(
        f"/project/{pid}/releases",
        data={"release_name": "v1.0"},
        follow_redirects=False,
    )

    assert result.status_code == 303
    assert f"/project/{pid}/documents?release_id=" in result.headers["location"]
    with get_db(tmp_db) as conn:
        row = conn.execute("SELECT * FROM releases WHERE project_id = ?", (pid,)).fetchone()
    assert row is not None
    assert row["name"] == "v1.0"


def test_create_release_empty_name_redirects_to_documents(client, tmp_db):
    pid = _insert_project(tmp_db, "Alpha", "PROG-1")

    result = client.post(
        f"/project/{pid}/releases",
        data={"release_name": "  "},
        follow_redirects=False,
    )

    assert result.status_code == 303
    assert result.headers["location"] == f"/project/{pid}/documents"


def test_delete_release_returns_redirect_header(client, tmp_db):
    pid = _insert_project(tmp_db, "Alpha", "PROG-1")
    with get_db(tmp_db) as conn:
        cursor = conn.execute(
            "INSERT INTO releases (project_id, name) VALUES (?, ?)", (pid, "v1.0")
        )
        conn.commit()
        rid = cursor.lastrowid

    result = client.delete(f"/project/{pid}/releases/{rid}")

    assert result.status_code == 200
    assert result.headers.get("HX-Redirect") == f"/project/{pid}/documents"
    with get_db(tmp_db) as conn:
        row = conn.execute("SELECT * FROM releases WHERE id = ?", (rid,)).fetchone()
    assert row is None


# ---------------------------------------------------------------------------
# GET /project/{id}/approvals — project approvals: Contract tests
# ---------------------------------------------------------------------------


def test_project_approvals_returns_200(client, tmp_db):
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

            result = client.get(f"/project/{pid}/approvals")

    assert result.status_code == 200
    assert "Approvals" in result.text
