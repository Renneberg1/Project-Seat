"""Tests for the Closure Report service."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.database import init_db, get_db
from src.models.closure import ClosureReport, ClosureReportStatus
from src.models.dhf import DHFDocument, DocumentStatus
from src.models.project import Project
from src.services.closure import ClosureService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase, "
            "team_projects, confluence_charter_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("PROG-1", "Test Project", "active", "development",
             json.dumps([["AIM", "Drop 1"]]), "88888"),
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
    settings.atlassian.confluence_space_key = "HPP"
    return ClosureService(db_path=tmp_db, settings=settings)


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------


class TestComputeClosureMetrics:
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
            "risks_raw": [],
            "decisions_raw": [],
            "charter_content": None,
            "xft_content": None,
            "meeting_summaries": [],
        }
        metrics = service.compute_closure_metrics(ctx)
        assert metrics["project_name"] == "Test Project"
        assert metrics["phase"] == "development"
        assert metrics["all_risks"] == []
        assert metrics["all_decisions"] == []
        assert metrics["team_progress"] == []
        assert metrics["scope_delivered"] == []
        assert metrics["scope_not_delivered"] == []
        assert metrics["dhf_total"] == 0

    def test_risks_parsed(self, service, project):
        ctx = {
            "project": project,
            "summary": None,
            "initiatives": [],
            "team_reports": [],
            "snapshots": [],
            "dhf_docs": [],
            "releases": [],
            "risks_raw": [
                {
                    "key": "RISK-10",
                    "fields": {
                        "summary": "Regulatory risk",
                        "priority": {"name": "High"},
                        "status": {
                            "name": "Open",
                            "statusCategory": {"name": "To Do"},
                        },
                        "components": [{"name": "Backend"}],
                    },
                }
            ],
            "decisions_raw": [
                {
                    "key": "RISK-20",
                    "fields": {
                        "summary": "Architecture decision",
                        "status": {
                            "name": "Decided",
                            "statusCategory": {"name": "Done"},
                        },
                    },
                }
            ],
            "charter_content": None,
            "xft_content": None,
            "meeting_summaries": [],
        }
        metrics = service.compute_closure_metrics(ctx)
        assert len(metrics["all_risks"]) == 1
        assert metrics["all_risks"][0]["key"] == "RISK-10"
        assert metrics["all_risks"][0]["priority"] == "High"
        assert metrics["all_risks"][0]["components"] == "Backend"
        assert len(metrics["all_decisions"]) == 1
        assert metrics["all_decisions"][0]["key"] == "RISK-20"

    def test_scope_classification(self, service, project):
        mock_init_done = MagicMock()
        mock_init_done.key = "AIM-1"
        mock_init_done.summary = "Feature A"
        mock_init_done.status = "Done"

        mock_init_open = MagicMock()
        mock_init_open.key = "AIM-2"
        mock_init_open.summary = "Feature B"
        mock_init_open.status = "In Progress"

        ctx = {
            "project": project,
            "summary": None,
            "initiatives": [mock_init_done, mock_init_open],
            "team_reports": [],
            "snapshots": [],
            "dhf_docs": [],
            "releases": [],
            "risks_raw": [],
            "decisions_raw": [],
            "charter_content": None,
            "xft_content": None,
            "meeting_summaries": [],
        }
        metrics = service.compute_closure_metrics(ctx)
        assert len(metrics["scope_delivered"]) == 1
        assert metrics["scope_delivered"][0]["key"] == "AIM-1"
        assert len(metrics["scope_not_delivered"]) == 1
        assert metrics["scope_not_delivered"][0]["key"] == "AIM-2"

    def test_dhf_counting(self, service, project):
        doc_released = DHFDocument(
            title="Doc A", area="Design", released_version="1",
            draft_version=None, status=DocumentStatus.RELEASED,
            last_modified="2026-02-20", author="Alice", page_url="",
        )
        doc_draft = DHFDocument(
            title="Doc B", area="Testing", released_version=None,
            draft_version="1", status=DocumentStatus.IN_DRAFT,
            last_modified="2026-02-22", author="Bob", page_url="",
        )
        ctx = {
            "project": project,
            "summary": None,
            "initiatives": [],
            "team_reports": [],
            "snapshots": [],
            "dhf_docs": [doc_released, doc_draft],
            "releases": [],
            "risks_raw": [],
            "decisions_raw": [],
            "charter_content": None,
            "xft_content": None,
            "meeting_summaries": [],
        }
        metrics = service.compute_closure_metrics(ctx)
        assert metrics["dhf_total"] == 2
        assert metrics["dhf_released"] == 1
        assert metrics["dhf_completion_pct"] == 50


# ---------------------------------------------------------------------------
# Confluence XHTML rendering
# ---------------------------------------------------------------------------


class TestRenderXhtml:
    """Test the Confluence XHTML output."""

    def test_basic_render(self, service):
        report = {
            "final_delivery_outcome": "Project delivered successfully.",
            "success_criteria_assessments": [
                {
                    "criterion": "Regulatory submission",
                    "expected_outcome": "Submission by Q1",
                    "measurement_method": "Date check",
                    "actual_performance": "Submitted on time",
                    "status": "Met",
                    "comments": "On schedule",
                }
            ],
            "lessons_learned": [
                {
                    "category": "Planning",
                    "description": "Early vendor engagement",
                    "effect_triggers": "Late vendor",
                    "recommendations": "Engage vendors in phase 1",
                    "owner": "PM",
                }
            ],
            "metrics": {
                "project_name": "Test Project",
                "pm": "Alice",
                "sponsor": "Bob",
                "phase": "closed",
                "timeline": {"planned_end": "2026-03-01", "actual_end": "2026-03-05", "deviation": "+4 days"},
                "scope_delivered": [{"key": "AIM-1", "summary": "Feature A"}],
                "scope_not_delivered": [],
                "all_risks": [{"key": "RISK-1", "summary": "Risk A", "priority": "High", "status": "Closed", "components": "Backend"}],
                "all_decisions": [{"key": "RISK-2", "summary": "Decision A", "status": "Decided"}],
                "dhf_total": 10,
                "dhf_released": 8,
                "dhf_completion_pct": 80,
                "team_progress": [],
                "releases": [],
            },
        }
        xhtml = service.render_confluence_xhtml(report)
        assert "Test Project" in xhtml
        assert "Project delivered successfully." in xhtml
        assert "Regulatory submission" in xhtml
        assert "Early vendor engagement" in xhtml
        assert "RISK-1" in xhtml
        assert "<table>" in xhtml
        assert "<h2>" in xhtml


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    """Test save / list / get / accept / reject."""

    def test_save_and_list(self, service, project):
        report_data = {"final_delivery_outcome": "Done", "metrics": {}}
        rid = service.save_report(project.id, report_data, "<h1>Test</h1>")
        assert rid > 0

        reports = service.list_reports(project.id)
        assert len(reports) == 1
        assert reports[0].id == rid
        assert reports[0].status == ClosureReportStatus.DRAFT

    def test_get_report(self, service, project):
        rid = service.save_report(project.id, {"final_delivery_outcome": "Done"}, "<p>body</p>")
        report = service.get_report(rid)
        assert report is not None
        assert report.report_json["final_delivery_outcome"] == "Done"
        assert report.confluence_body == "<p>body</p>"

    def test_reject_report(self, service, project):
        rid = service.save_report(project.id, {}, "")
        result = service.reject_report(rid)
        assert result.status == ClosureReportStatus.REJECTED

    def test_accept_report_no_charter(self, service, tmp_db):
        """Accept should fail if project has no charter page."""
        with get_db(tmp_db) as conn:
            conn.execute(
                "INSERT INTO projects (jira_goal_key, name, status, phase) "
                "VALUES (?, ?, ?, ?)",
                ("PROG-2", "No Charter Project", "active", "planning"),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM projects WHERE jira_goal_key = 'PROG-2'").fetchone()
        no_charter_project = Project.from_row(row)

        rid = service.save_report(no_charter_project.id, {}, "")
        with pytest.raises(ValueError, match="no Charter page configured"):
            service.accept_report(rid, no_charter_project)

    def test_accept_report_queues(self, service, project):
        """Accept should create an approval queue item."""
        rid = service.save_report(project.id, {"final_delivery_outcome": "Done"}, "<p>test</p>")
        result = service.accept_report(rid, project)
        assert result.status == ClosureReportStatus.QUEUED
        assert result.approval_item_id is not None

        # Verify approval queue entry
        with get_db(service._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM approval_queue WHERE id = ?",
                (result.approval_item_id,),
            ).fetchone()
        assert row is not None
        payload = json.loads(row["payload"])
        assert payload["space_key"] == "HPP"
        assert payload["title"] == "Test Project Closure Report"
        assert payload["body_storage"] == "<p>test</p>"
        assert payload["parent_id"] == "88888"
