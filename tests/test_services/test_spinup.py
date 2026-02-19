"""Tests for the spin-up service."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.database import get_db
from src.models.approval import ApprovalAction, ApprovalStatus
from src.models.project import SpinUpRequest
from src.services.spinup import (
    GOAL_ISSUE_TYPE_ID,
    PROG_PROJECT_KEY,
    RISK_PROJECT_KEY,
    SpinUpService,
    _SENTINEL_CHARTER_PAGE_ID,
    _SENTINEL_GOAL_KEY,
)


def _make_request(**overrides) -> SpinUpRequest:
    defaults = dict(
        project_name="HOP Drop 4",
        program="HOP",
        team_projects=["AIM", "CTCV"],
        target_date="2026-09-01",
        labels=["release-4"],
        goal_summary="Fourth HOP drop",
    )
    defaults.update(overrides)
    return SpinUpRequest(**defaults)


@pytest.fixture()
def service(tmp_db: str) -> SpinUpService:
    return SpinUpService(db_path=tmp_db)


# ---------------------------------------------------------------------------
# prepare_spinup
# ---------------------------------------------------------------------------


class TestPrepareSpinup:
    async def test_creates_local_project(self, service: SpinUpService, tmp_db: str) -> None:
        req = _make_request()
        with patch.object(service, "_fetch_template_body", new_callable=AsyncMock, return_value="<p>template</p>"), \
             patch.object(service, "_find_projects_releases_page", new_callable=AsyncMock, return_value="999"):
            await service.prepare_spinup(req)

        with get_db(tmp_db) as conn:
            row = conn.execute("SELECT * FROM projects WHERE name = 'HOP Drop 4'").fetchone()
        assert row is not None
        assert row["status"] == "spinning_up"

    async def test_correct_number_of_items(self, service: SpinUpService) -> None:
        req = _make_request(team_projects=["AIM", "CTCV"])
        with patch.object(service, "_fetch_template_body", new_callable=AsyncMock, return_value="<p>t</p>"), \
             patch.object(service, "_find_projects_releases_page", new_callable=AsyncMock, return_value="999"):
            item_ids = await service.prepare_spinup(req)
        # 1 goal + 1 RISK version + 2 team versions + 1 charter + 1 XFT + 1 update = 7
        assert len(item_ids) == 7

    async def test_goal_payload(self, service: SpinUpService, tmp_db: str) -> None:
        req = _make_request()
        with patch.object(service, "_fetch_template_body", new_callable=AsyncMock, return_value="<p>t</p>"), \
             patch.object(service, "_find_projects_releases_page", new_callable=AsyncMock, return_value="999"):
            item_ids = await service.prepare_spinup(req)

        item = service._engine.get(item_ids[0])
        payload = json.loads(item.payload)
        assert payload["project_key"] == PROG_PROJECT_KEY
        assert payload["issue_type_id"] == GOAL_ISSUE_TYPE_ID
        assert item.action_type == ApprovalAction.CREATE_JIRA_ISSUE

    async def test_risk_version_payload(self, service: SpinUpService) -> None:
        req = _make_request()
        with patch.object(service, "_fetch_template_body", new_callable=AsyncMock, return_value="<p>t</p>"), \
             patch.object(service, "_find_projects_releases_page", new_callable=AsyncMock, return_value="999"):
            item_ids = await service.prepare_spinup(req)

        item = service._engine.get(item_ids[1])
        payload = json.loads(item.payload)
        assert payload["project_key"] == RISK_PROJECT_KEY
        assert payload["name"] == "HOP Drop 4"
        assert item.action_type == ApprovalAction.CREATE_JIRA_VERSION

    async def test_team_version_payloads(self, service: SpinUpService) -> None:
        req = _make_request(team_projects=["AIM", "CTCV"])
        with patch.object(service, "_fetch_template_body", new_callable=AsyncMock, return_value="<p>t</p>"), \
             patch.object(service, "_find_projects_releases_page", new_callable=AsyncMock, return_value="999"):
            item_ids = await service.prepare_spinup(req)

        # Team versions are items 2 and 3 (after goal and RISK version)
        for i, proj_key in enumerate(["AIM", "CTCV"], start=2):
            item = service._engine.get(item_ids[i])
            payload = json.loads(item.payload)
            assert payload["project_key"] == proj_key

    async def test_xft_uses_charter_sentinel(self, service: SpinUpService) -> None:
        req = _make_request(team_projects=[])
        with patch.object(service, "_fetch_template_body", new_callable=AsyncMock, return_value="<p>t</p>"), \
             patch.object(service, "_find_projects_releases_page", new_callable=AsyncMock, return_value="999"):
            item_ids = await service.prepare_spinup(req)

        # With 0 team projects: goal, RISK version, charter, XFT, update = indices 0-4
        xft_item = service._engine.get(item_ids[3])
        payload = json.loads(xft_item.payload)
        assert payload["parent_id"] == _SENTINEL_CHARTER_PAGE_ID

    async def test_update_goal_uses_goal_key_sentinel(self, service: SpinUpService) -> None:
        req = _make_request(team_projects=[])
        with patch.object(service, "_fetch_template_body", new_callable=AsyncMock, return_value="<p>t</p>"), \
             patch.object(service, "_find_projects_releases_page", new_callable=AsyncMock, return_value="999"):
            item_ids = await service.prepare_spinup(req)

        update_item = service._engine.get(item_ids[-1])
        payload = json.loads(update_item.payload)
        assert payload["key"] == _SENTINEL_GOAL_KEY


# ---------------------------------------------------------------------------
# _replace_placeholders
# ---------------------------------------------------------------------------


class TestReplacePlaceholders:
    def test_replaces_all_patterns(self, service: SpinUpService) -> None:
        body = (
            "[Insert project name & release] is great. "
            "[Insert project name] rocks. "
            "[Project Name] page. "
            "[Target Date] soon. "
            "[Program] team."
        )
        req = _make_request()
        result = service._replace_placeholders(body, req)
        assert "[Insert project name & release]" not in result
        assert "[Insert project name]" not in result
        assert "[Project Name]" not in result
        assert "[Target Date]" not in result
        assert "[Program]" not in result
        assert "HOP Drop 4" in result
        assert "HOP" in result

    def test_empty_target_date_becomes_tbd(self, service: SpinUpService) -> None:
        body = "[Target Date] is the deadline"
        req = _make_request(target_date="")
        result = service._replace_placeholders(body, req)
        assert "TBD" in result


# ---------------------------------------------------------------------------
# _resolve_sentinels
# ---------------------------------------------------------------------------


class TestResolveSentinels:
    def test_replaces_charter_page_id(self, service: SpinUpService, tmp_db: str) -> None:
        # Create a project and a fake executed charter item
        with get_db(tmp_db) as conn:
            conn.execute(
                "INSERT INTO projects (id, jira_goal_key, name, status) VALUES (?, ?, ?, ?)",
                (100, "pending", "Test", "spinning_up"),
            )
            conn.execute(
                """INSERT INTO approval_queue
                   (project_id, action_type, payload, preview, status, result)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    100,
                    "create_confluence_page",
                    '{}',
                    "Charter",
                    "executed",
                    json.dumps({"id": "55555", "title": "HOP Charter"}),
                ),
            )
            conn.commit()

        payload = {"parent_id": _SENTINEL_CHARTER_PAGE_ID}
        resolved = service._resolve_sentinels(payload, 100)
        assert resolved["parent_id"] == "55555"

    def test_replaces_goal_key(self, service: SpinUpService, tmp_db: str) -> None:
        with get_db(tmp_db) as conn:
            conn.execute(
                "INSERT INTO projects (id, jira_goal_key, name, status) VALUES (?, ?, ?, ?)",
                (200, "pending", "Test2", "spinning_up"),
            )
            conn.execute(
                """INSERT INTO approval_queue
                   (project_id, action_type, payload, preview, status, result)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    200,
                    "create_jira_issue",
                    '{}',
                    "Goal",
                    "executed",
                    json.dumps({"key": "PROG-999"}),
                ),
            )
            conn.commit()

        payload = {"key": _SENTINEL_GOAL_KEY}
        resolved = service._resolve_sentinels(payload, 200)
        assert resolved["key"] == "PROG-999"


# ---------------------------------------------------------------------------
# _build_goal_description
# ---------------------------------------------------------------------------


class TestBuildGoalDescription:
    def test_returns_adf_with_inline_card(self, service: SpinUpService) -> None:
        with patch("src.services.spinup.settings") as mock_settings:
            mock_settings.atlassian.domain = "test-company"
            result = service._build_goal_description("111", "222")

        assert result["type"] == "doc"
        assert result["version"] == 1
        content = result["content"]
        assert len(content) == 2  # charter + XFT paragraphs
        # Check inlineCard is present
        first_para = content[0]["content"]
        assert any(c.get("type") == "inlineCard" for c in first_para)
