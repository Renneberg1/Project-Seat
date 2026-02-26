"""Tests for import project routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.connectors.base import ConnectorError
from src.database import get_db
from src.services.import_project import DetectedPage, ImportPreview


def _insert_project(db_path, name="Test", goal_key="PROG-100"):
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase) VALUES (?, ?, ?, ?)",
            (goal_key, name, "active", "planning"),
        )
        conn.commit()
        return cursor.lastrowid


# ---------------------------------------------------------------------------
# GET /import/ — form page: Contract tests
# ---------------------------------------------------------------------------


def test_import_form_get_returns_200(client):
    result = client.get("/import/")

    assert result.status_code == 200
    assert "goal_key" in result.text


def test_import_form_has_htmx_attributes(client):
    result = client.get("/import/")

    assert "hx-post" in result.text
    assert "/import/fetch" in result.text


# ---------------------------------------------------------------------------
# POST /import/fetch — fetch preview: Contract tests
# ---------------------------------------------------------------------------


def test_import_fetch_returns_confirm_partial(client):
    preview = ImportPreview(
        goal_key="PROG-256",
        goal_summary="HOP Drop 2",
        detected_pages=[
            DetectedPage(page_id="100", url="https://x/pages/100/Charter", slug="Charter"),
            DetectedPage(page_id="200", url="https://x/pages/200/Scope", slug="Scope"),
        ],
        charter_id="100",
        xft_id="200",
        detected_teams={"AIM": "HOP Drop 2", "CTCV": "HOP Drop 2"},
    )

    with patch("src.web.deps.ImportService") as MockSvc:
        MockSvc.return_value.fetch_preview = AsyncMock(return_value=preview)

        result = client.post("/import/fetch", data={"goal_key": "PROG-256"})

    assert result.status_code == 200
    assert "HOP Drop 2" in result.text
    assert "100" in result.text
    assert "200" in result.text
    assert "Charter" in result.text
    assert "Auto-detected 2 team(s)" in result.text
    assert "AIM:HOP Drop 2" in result.text


def test_import_fetch_handles_connector_error(client):
    with patch("src.web.deps.ImportService") as MockSvc:
        MockSvc.return_value.fetch_preview = AsyncMock(side_effect=ConnectorError(404, "Not found"))

        result = client.post("/import/fetch", data={"goal_key": "PROG-999"})

    assert result.status_code == 200
    assert "Failed to fetch" in result.text


def test_import_fetch_uppercases_goal_key(client):
    preview = ImportPreview(goal_key="PROG-256", goal_summary="Test")

    with patch("src.web.deps.ImportService") as MockSvc:
        instance = MockSvc.return_value
        instance.fetch_preview = AsyncMock(return_value=preview)

        result = client.post("/import/fetch", data={"goal_key": "prog-256"})

    instance.fetch_preview.assert_called_once_with("PROG-256")


# ---------------------------------------------------------------------------
# POST /import/save — save project: Contract tests
# ---------------------------------------------------------------------------


def test_import_save_redirects_to_dashboard(client, tmp_db):
    with patch("src.web.deps.ImportService") as MockSvc:
        MockSvc.return_value.save_project.return_value = 42

        result = client.post(
            "/import/save",
            data={
                "goal_key": "PROG-256",
                "name": "HOP Drop 2",
                "charter_id": "100",
                "xft_id": "200",
                "team_projects": "AIM:HOP Drop 2, CTCV:HOP Drop 2",
            },
            follow_redirects=False,
        )

    assert result.status_code == 303
    assert "/project/42/dashboard" in result.headers["location"]
    # Verify team_projects was parsed as list of pairs
    MockSvc.return_value.save_project.assert_called_once_with(
        goal_key="PROG-256",
        name="HOP Drop 2",
        charter_id="100",
        xft_id="200",
        pi_version=None,
        team_projects=[["AIM", "HOP Drop 2"], ["CTCV", "HOP Drop 2"]],
        jira_plan_url=None,
        ceo_review_id=None,
    )


def test_import_save_duplicate_shows_error(client, tmp_db):
    with patch("src.web.deps.ImportService") as MockSvc:
        MockSvc.return_value.save_project.side_effect = ValueError("already exists (id=1)")

        result = client.post(
            "/import/save",
            data={"goal_key": "PROG-256", "name": "HOP Drop 2"},
        )

    assert result.status_code == 200
    assert "already exists" in result.text


def test_import_save_empty_page_ids_saved_as_none(client, tmp_db):
    with patch("src.web.deps.ImportService") as MockSvc:
        instance = MockSvc.return_value
        instance.save_project.return_value = 1

        result = client.post(
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
        pi_version=None,
        team_projects=None,
        jira_plan_url=None,
        ceo_review_id=None,
    )
