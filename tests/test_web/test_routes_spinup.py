"""Tests for spin-up wizard routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


class TestSpinupForm:
    def test_get_returns_200(self, client) -> None:
        resp = client.get("/spinup/")
        assert resp.status_code == 200

    def test_form_contains_expected_fields(self, client) -> None:
        resp = client.get("/spinup/")
        html = resp.text
        assert "project_name" in html
        assert "program" in html
        assert "team_projects" in html
        assert "target_date" in html
        assert "labels" in html
        assert "goal_summary" in html


class TestSpinupSubmit:
    def test_post_queues_actions(self, client) -> None:
        with patch("src.web.routes.spinup.SpinUpService") as MockSvc:
            instance = MockSvc.return_value
            instance.prepare_spinup = AsyncMock(return_value=[1, 2, 3, 4, 5, 6])

            resp = client.post(
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

        assert resp.status_code == 200
        assert "6" in resp.text  # item_count
        assert "HOP Drop 4" in resp.text

    def test_post_required_fields_only(self, client) -> None:
        with patch("src.web.routes.spinup.SpinUpService") as MockSvc:
            instance = MockSvc.return_value
            instance.prepare_spinup = AsyncMock(return_value=[1, 2, 3])

            resp = client.post(
                "/spinup/",
                data={
                    "project_name": "Minimal",
                    "program": "AIM",
                },
            )

        assert resp.status_code == 200
