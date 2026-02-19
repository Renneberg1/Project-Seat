"""Tests for spin-up wizard routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# GET /spinup/ — form page: Contract tests
# ---------------------------------------------------------------------------


def test_spinup_form_get_returns_200(client):
    result = client.get("/spinup/")

    assert result.status_code == 200


def test_spinup_form_contains_expected_fields(client):
    result = client.get("/spinup/")

    html = result.text
    assert "project_name" in html
    assert "program" in html
    assert "team_projects" in html
    assert "target_date" in html
    assert "labels" in html
    assert "goal_summary" in html


# ---------------------------------------------------------------------------
# POST /spinup/ — submit form: Contract tests
# ---------------------------------------------------------------------------


def test_spinup_submit_queues_actions_and_shows_result(client):
    with patch("src.web.routes.spinup.SpinUpService") as MockSvc:
        instance = MockSvc.return_value
        instance.prepare_spinup = AsyncMock(return_value=[1, 2, 3, 4, 5, 6])

        result = client.post(
            "/spinup/",
            data={
                "project_name": "HOP Drop 4",
                "program": "HOP",
                "team_projects": "AIM, CTCV",
                "target_date": "2026-09-01",
                "labels": "release-4",
                "goal_summary": "Fourth drop",
            },
        )

    assert result.status_code == 200
    assert "6" in result.text
    assert "HOP Drop 4" in result.text


def test_spinup_submit_required_fields_only(client):
    with patch("src.web.routes.spinup.SpinUpService") as MockSvc:
        instance = MockSvc.return_value
        instance.prepare_spinup = AsyncMock(return_value=[1, 2, 3])

        result = client.post(
            "/spinup/",
            data={
                "project_name": "Minimal",
                "program": "AIM",
            },
        )

    assert result.status_code == 200
