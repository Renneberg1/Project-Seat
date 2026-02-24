"""Tests for the CEO Review service, agent, and routes."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.database import init_db, get_db
from src.models.ceo_review import CeoReview, CeoReviewStatus
from src.models.dhf import DHFDocument, DocumentStatus
from src.models.project import Project
from src.services.ceo_review import CeoReviewService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    # Insert a test project
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase, team_projects, confluence_ceo_review_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("PROG-1", "Test Project", "active", "development", json.dumps({"AIM": "Drop 1"}), "99999"),
        )
        conn.commit()
    return db_path


@pytest.fixture
def project(tmp_db):
    with get_db(tmp_db) as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = 1").fetchone()
    return Project.from_row(row)


@pytest.fixture
def service(tmp_db):
    settings = MagicMock()
    settings.db_path = tmp_db
    settings.llm = MagicMock()
    settings.atlassian = MagicMock()
    return CeoReviewService(db_path=tmp_db, settings=settings)


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------


class TestComputeMetrics:
    """Test the deterministic metrics computation."""

    def test_empty_context(self, service, project):
        ctx = {
            "project": project,
            "summary": None,
            "initiatives": [],
            "team_reports": [],
            "snapshots": [],
            "dhf_docs": [],
            "releases": [],
            "new_risks_raw": [],
            "new_decisions_raw": [],
            "meeting_summaries": [],
        }
        metrics = service.compute_metrics(ctx)
        assert metrics["project_name"] == "Test Project"
        assert metrics["phase"] == "development"
        assert metrics["new_risks"] == []
        assert metrics["new_decisions"] == []
        assert metrics["team_progress"] == []
        assert metrics["sp_burned_2w"] == 0
        assert metrics["dhf_total"] == 0

    def test_new_risks_parsed(self, service, project):
        ctx = {
            "project": project,
            "summary": None,
            "initiatives": [],
            "team_reports": [],
            "snapshots": [],
            "dhf_docs": [],
            "releases": [],
            "new_risks_raw": [
                {
                    "key": "RISK-10",
                    "fields": {
                        "summary": "New risk item",
                        "status": {"name": "Open"},
                        "components": [{"name": "Backend"}],
                    },
                }
            ],
            "new_decisions_raw": [
                {
                    "key": "RISK-20",
                    "fields": {
                        "summary": "Architecture decision",
                        "status": {"name": "Decided"},
                    },
                }
            ],
            "meeting_summaries": [],
        }
        metrics = service.compute_metrics(ctx)
        assert len(metrics["new_risks"]) == 1
        assert metrics["new_risks"][0]["key"] == "RISK-10"
        assert metrics["new_risks"][0]["components"] == "Backend"
        assert len(metrics["new_decisions"]) == 1
        assert metrics["new_decisions"][0]["key"] == "RISK-20"

    def test_burnup_delta(self, service, project):
        ctx = {
            "project": project,
            "summary": None,
            "initiatives": [],
            "team_reports": [],
            "snapshots": [
                {"date": "2026-02-10", "sp_total": 100, "sp_done": 50},
                {"date": "2026-02-24", "sp_total": 110, "sp_done": 70},
            ],
            "dhf_docs": [],
            "releases": [],
            "new_risks_raw": [],
            "new_decisions_raw": [],
            "meeting_summaries": [],
        }
        metrics = service.compute_metrics(ctx)
        assert metrics["sp_burned_2w"] == 20
        assert metrics["scope_change_2w"] == 10

    def test_dhf_filtering(self, service, project):
        doc_recent = DHFDocument(
            title="Doc A", area="Design", released_version="1",
            draft_version=None, status=DocumentStatus.RELEASED,
            last_modified="2026-02-20", author="Alice", page_url="",
        )
        doc_old = DHFDocument(
            title="Doc B", area="Design", released_version="1",
            draft_version=None, status=DocumentStatus.RELEASED,
            last_modified="2025-01-01", author="Bob", page_url="",
        )
        doc_draft = DHFDocument(
            title="Doc C", area="Testing", released_version=None,
            draft_version="1", status=DocumentStatus.IN_DRAFT,
            last_modified="2026-02-22", author="Carol", page_url="",
        )
        ctx = {
            "project": project,
            "summary": None,
            "initiatives": [],
            "team_reports": [],
            "snapshots": [],
            "dhf_docs": [doc_recent, doc_old, doc_draft],
            "releases": [],
            "new_risks_raw": [],
            "new_decisions_raw": [],
            "meeting_summaries": [],
        }
        metrics = service.compute_metrics(ctx)
        assert metrics["dhf_total"] == 3
        assert metrics["dhf_released"] == 2
        # Only docs modified in last 2 weeks should appear
        recent_titles = {d["title"] for d in metrics["dhf_recently_updated"]}
        assert "Doc A" in recent_titles
        assert "Doc C" in recent_titles
        assert "Doc B" not in recent_titles


# ---------------------------------------------------------------------------
# Confluence XHTML rendering
# ---------------------------------------------------------------------------


class TestRenderXhtml:
    """Test the Confluence XHTML output."""

    def test_basic_render(self, service):
        review = {
            "health_indicator": "On Track",
            "decisions_commentary": "Two key decisions made.",
            "risks_commentary": "No critical risks.",
            "development_commentary": "Good velocity.",
            "documentation_commentary": "DHF progressing.",
            "escalations": [],
            "next_milestones": ["Release candidate by March 1"],
            "metrics": {
                "project_name": "Test Project",
                "new_decisions": [{"key": "RISK-1", "summary": "Use OAuth", "status": "Decided"}],
                "new_risks": [],
                "open_risk_count": 3,
                "total_risk_count": 10,
                "team_progress": [{"team": "AIM", "pct_done": 75, "sp_done": 30, "sp_total": 40, "blockers": 0}],
                "sp_burned_2w": 15,
                "dhf_total": 20,
                "dhf_released": 15,
                "dhf_completion_pct": 75,
                "dhf_recently_updated": [],
            },
        }
        xhtml = service.render_confluence_xhtml(review)
        # Should be a bullet list, not multi-section XHTML
        assert "<ul>" in xhtml
        assert "<li>" in xhtml
        assert "<h2>" not in xhtml
        assert "<h3>" not in xhtml
        assert "<hr/>" not in xhtml
        # Content checks
        assert "Test Project" in xhtml
        assert "On Track" in xhtml
        assert "Green" in xhtml
        assert "Good velocity." in xhtml
        assert "DHF progressing." in xhtml
        assert "3/10 open" in xhtml
        assert "No critical risks." in xhtml
        assert "New decisions: 1." in xhtml
        assert "Two key decisions made." in xhtml
        assert "Release candidate by March 1" in xhtml

    def test_off_track_colour(self, service):
        review = {
            "health_indicator": "Off Track",
            "decisions_commentary": "",
            "risks_commentary": "",
            "development_commentary": "",
            "documentation_commentary": "",
            "escalations": [{"issue": "Budget", "impact": "High", "ask": "More funds"}],
            "next_milestones": [],
            "metrics": {
                "project_name": "X",
                "new_decisions": [],
                "new_risks": [],
                "open_risk_count": 0,
                "total_risk_count": 0,
                "team_progress": [],
                "sp_burned_2w": 0,
                "dhf_total": 0,
                "dhf_released": 0,
                "dhf_completion_pct": 0,
                "dhf_recently_updated": [],
            },
        }
        xhtml = service.render_confluence_xhtml(review)
        assert "<ul>" in xhtml
        assert "<li>" in xhtml
        assert "Red" in xhtml
        assert "Off Track" in xhtml
        assert "Budget" in xhtml
        assert "More funds" in xhtml


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    """Test save / list / get / accept / reject."""

    def test_save_and_list(self, service, project):
        review_data = {"health_indicator": "On Track", "metrics": {}}
        rid = service.save_review(project.id, review_data, "<h1>Test</h1>")
        assert rid > 0

        reviews = service.list_reviews(project.id)
        assert len(reviews) == 1
        assert reviews[0].id == rid
        assert reviews[0].status == CeoReviewStatus.DRAFT

    def test_get_review(self, service, project):
        rid = service.save_review(project.id, {"health_indicator": "At Risk"}, "<p>body</p>")
        review = service.get_review(rid)
        assert review is not None
        assert review.review_json["health_indicator"] == "At Risk"
        assert review.confluence_body == "<p>body</p>"

    def test_reject_review(self, service, project):
        rid = service.save_review(project.id, {}, "")
        result = service.reject_review(rid)
        assert result.status == CeoReviewStatus.REJECTED

    def test_accept_review_no_page(self, service, tmp_db):
        """Accept should fail if project has no ceo_review_id."""
        # Create a project without ceo_review_id
        with get_db(tmp_db) as conn:
            conn.execute(
                "INSERT INTO projects (jira_goal_key, name, status, phase) "
                "VALUES (?, ?, ?, ?)",
                ("PROG-2", "No Page Project", "active", "planning"),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM projects WHERE jira_goal_key = 'PROG-2'").fetchone()
        no_page_project = Project.from_row(row)

        rid = service.save_review(no_page_project.id, {}, "")
        with pytest.raises(ValueError, match="no CEO Review page configured"):
            service.accept_review(rid, no_page_project)

    def test_accept_review_queues(self, service, project):
        """Accept should create an approval queue item."""
        rid = service.save_review(project.id, {"health_indicator": "On Track"}, "<p>test</p>")
        result = service.accept_review(rid, project)
        assert result.status == CeoReviewStatus.QUEUED
        assert result.approval_item_id is not None

        # Verify approval queue entry
        with get_db(service._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM approval_queue WHERE id = ?",
                (result.approval_item_id,),
            ).fetchone()
        assert row is not None
        payload = json.loads(row["payload"])
        assert payload["page_id"] == "99999"
        assert payload["section_replace_mode"] is True
        assert payload["section_name"] == "Summary Status"
        assert payload["new_content"] == "<p>test</p>"
        assert payload["raw_xhtml"] is True


# ---------------------------------------------------------------------------
# Agent tests
# ---------------------------------------------------------------------------


class TestCeoReviewAgent:
    """Test the CeoReviewAgent ask_questions and generate_review methods."""

    @pytest.mark.asyncio
    async def test_ask_questions(self):
        from src.engine.agent import CeoReviewAgent

        mock_provider = AsyncMock()
        mock_provider.generate.return_value = json.dumps({
            "questions": [
                {"question": "Why was the sprint delayed?", "category": "Development", "why_needed": "Context"}
            ]
        })

        agent = CeoReviewAgent(mock_provider)
        result = await agent.ask_questions(
            metrics={"project_name": "Test", "new_risks": [], "new_decisions": []},
            pm_notes="Sprint was delayed",
        )

        assert "questions" in result
        assert len(result["questions"]) == 1
        assert result["questions"][0]["category"] == "Development"

    @pytest.mark.asyncio
    async def test_generate_review(self):
        from src.engine.agent import CeoReviewAgent

        mock_provider = AsyncMock()
        mock_provider.generate.return_value = json.dumps({
            "health_indicator": "On Track",
            "decisions_commentary": "Good decisions.",
            "risks_commentary": "Risks under control.",
            "development_commentary": "On schedule.",
            "documentation_commentary": "Progressing.",
            "escalations": [],
            "next_milestones": ["Release by March 15"],
        })

        agent = CeoReviewAgent(mock_provider)
        result = await agent.generate_review(
            metrics={"project_name": "Test"},
            pm_notes="",
            qa_pairs=[],
        )

        assert result["health_indicator"] == "On Track"
        assert "next_milestones" in result


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_db):
    from starlette.testclient import TestClient

    with patch("src.main.init_db"), \
         patch("src.main.orchestrator"), \
         patch("src.web.deps.DashboardService") as MockDash:
        MockDash.return_value.list_projects.return_value = []
        from src.main import app
        app.state.testing = True
        yield TestClient(app, raise_server_exceptions=False)


class TestRoutes:
    """Test CEO Review route contracts."""

    def test_main_page(self, client, tmp_db, project):
        with patch("src.web.routes.ceo_review.DashboardService") as MockDash, \
             patch("src.web.routes.ceo_review.CeoReviewService") as MockSvc:
            MockDash.return_value.get_project_by_id.return_value = project
            MockSvc.return_value.list_reviews.return_value = []

            resp = client.get(f"/project/{project.id}/ceo-review/")
            assert resp.status_code == 200
            assert "CEO Review" in resp.text

    def test_main_page_not_found(self, client, tmp_db):
        with patch("src.web.routes.ceo_review.DashboardService") as MockDash:
            MockDash.return_value.get_project_by_id.return_value = None
            resp = client.get("/project/999/ceo-review/")
            assert resp.status_code == 404

    def test_ask_returns_questions(self, client, tmp_db, project):
        questions = [{"question": "Why?", "category": "Dev", "why_needed": "Context"}]
        metrics = {"project_name": "Test"}

        with patch("src.web.routes.ceo_review.DashboardService") as MockDash, \
             patch("src.web.routes.ceo_review.CeoReviewService") as MockSvc:
            MockDash.return_value.get_project_by_id.return_value = project
            MockSvc.return_value.generate_questions = AsyncMock(
                return_value=(questions, metrics)
            )

            resp = client.post(
                f"/project/{project.id}/ceo-review/ask",
                data={"pm_notes": "Sprint delayed"},
            )
            assert resp.status_code == 200
            assert "Why?" in resp.text

    def test_analyze_returns_preview(self, client, tmp_db, project):
        review = {
            "health_indicator": "On Track",
            "decisions_commentary": "Good.",
            "risks_commentary": "Fine.",
            "development_commentary": "Ok.",
            "documentation_commentary": "Done.",
            "escalations": [],
            "next_milestones": ["Ship"],
            "metrics": {"project_name": "Test", "new_decisions": [], "new_risks": [],
                        "team_progress": [], "sp_burned_2w": 0, "scope_change_2w": 0,
                        "dhf_total": 0, "dhf_released": 0, "dhf_completion_pct": 0,
                        "dhf_recently_updated": [], "open_risk_count": 0, "total_risk_count": 0},
        }

        with patch("src.web.routes.ceo_review.DashboardService") as MockDash, \
             patch("src.web.routes.ceo_review.CeoReviewService") as MockSvc:
            MockDash.return_value.get_project_by_id.return_value = project
            MockSvc.return_value.generate_review = AsyncMock(return_value=review)
            MockSvc.return_value.render_confluence_xhtml.return_value = "<h1>test</h1>"
            MockSvc.return_value.save_review.return_value = 1

            resp = client.post(
                f"/project/{project.id}/ceo-review/analyze",
                data={"pm_notes": ""},
            )
            assert resp.status_code == 200
            assert "On Track" in resp.text

    def test_accept_queues(self, client, tmp_db, project):
        mock_review = MagicMock()
        mock_review.status.value = "queued"

        with patch("src.web.routes.ceo_review.DashboardService") as MockDash, \
             patch("src.web.routes.ceo_review.CeoReviewService") as MockSvc:
            MockDash.return_value.get_project_by_id.return_value = project
            MockSvc.return_value.accept_review.return_value = mock_review

            resp = client.post(f"/project/{project.id}/ceo-review/1/accept")
            assert resp.status_code == 200
            assert "queued" in resp.text.lower() or "Approval Queue" in resp.text

    def test_reject(self, client, tmp_db, project):
        with patch("src.web.routes.ceo_review.DashboardService") as MockDash, \
             patch("src.web.routes.ceo_review.CeoReviewService") as MockSvc:
            MockDash.return_value.get_project_by_id.return_value = project

            resp = client.post(f"/project/{project.id}/ceo-review/1/reject")
            assert resp.status_code == 200
            assert "rejected" in resp.text.lower() or "Rejected" in resp.text
