"""Tests for the spin-up service — queue orchestration, placeholder replacement, sentinel resolution."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.database import get_db
from src.models.approval import ApprovalAction
from src.services.spinup import (
    GOAL_ISSUE_TYPE_ID,
    PROG_PROJECT_KEY,
    RISK_PROJECT_KEY,
    SpinUpService,
    _SENTINEL_CHARTER_PAGE_ID,
    _SENTINEL_GOAL_KEY,
)


@pytest.fixture()
def service(tmp_db):
    return SpinUpService(db_path=tmp_db)


def _patch_templates(service):
    """Context manager that stubs out the Confluence calls in prepare_spinup."""
    return (
        patch.object(service, "_fetch_template_body", new_callable=AsyncMock, return_value="<p>t</p>"),
        patch.object(service, "_find_projects_releases_page", new_callable=AsyncMock, return_value="999"),
    )


# ---------------------------------------------------------------------------
# prepare_spinup: Contract tests (incoming command — assert side effects)
# ---------------------------------------------------------------------------


async def test_prepare_spinup_creates_local_project(service, tmp_db, make_spinup_request):
    req = make_spinup_request()
    p1, p2 = _patch_templates(service)

    with p1, p2:
        result = await service.prepare_spinup(req)

    with get_db(tmp_db) as conn:
        row = conn.execute("SELECT * FROM projects WHERE name = 'HOP Drop 4'").fetchone()
    assert row is not None
    assert row["status"] == "spinning_up"


async def test_prepare_spinup_queues_correct_item_count(service, make_spinup_request):
    req = make_spinup_request(team_projects=["AIM", "CTCV"])
    p1, p2 = _patch_templates(service)

    with p1, p2:
        result = await service.prepare_spinup(req)

    # 1 goal + 1 RISK version + 2 team versions + 1 charter + 1 XFT + 1 update = 7
    assert len(result) == 7


async def test_prepare_spinup_first_item_is_goal(service, make_spinup_request):
    req = make_spinup_request()
    p1, p2 = _patch_templates(service)

    with p1, p2:
        result = await service.prepare_spinup(req)

    item = service._engine.get(result[0])
    payload = json.loads(item.payload)
    assert payload["project_key"] == PROG_PROJECT_KEY
    assert payload["issue_type_id"] == GOAL_ISSUE_TYPE_ID
    assert item.action_type == ApprovalAction.CREATE_JIRA_ISSUE


async def test_prepare_spinup_second_item_is_risk_version(service, make_spinup_request):
    req = make_spinup_request()
    p1, p2 = _patch_templates(service)

    with p1, p2:
        result = await service.prepare_spinup(req)

    item = service._engine.get(result[1])
    payload = json.loads(item.payload)
    assert payload["project_key"] == RISK_PROJECT_KEY
    assert payload["name"] == "HOP Drop 4"
    assert item.action_type == ApprovalAction.CREATE_JIRA_VERSION


async def test_prepare_spinup_team_version_payloads(service, make_spinup_request):
    req = make_spinup_request(team_projects=["AIM", "CTCV"])
    p1, p2 = _patch_templates(service)

    with p1, p2:
        result = await service.prepare_spinup(req)

    # Team versions are items 2 and 3 (after goal and RISK version)
    for i, proj_key in enumerate(["AIM", "CTCV"], start=2):
        item = service._engine.get(result[i])
        payload = json.loads(item.payload)
        assert payload["project_key"] == proj_key


async def test_prepare_spinup_xft_uses_charter_sentinel(service, make_spinup_request):
    req = make_spinup_request(team_projects=[])
    p1, p2 = _patch_templates(service)

    with p1, p2:
        result = await service.prepare_spinup(req)

    # With 0 team projects: goal, RISK version, charter, XFT, update = indices 0-4
    xft_item = service._engine.get(result[3])
    payload = json.loads(xft_item.payload)
    assert payload["parent_id"] == _SENTINEL_CHARTER_PAGE_ID


async def test_prepare_spinup_update_goal_uses_goal_key_sentinel(service, make_spinup_request):
    req = make_spinup_request(team_projects=[])
    p1, p2 = _patch_templates(service)

    with p1, p2:
        result = await service.prepare_spinup(req)

    update_item = service._engine.get(result[-1])
    payload = json.loads(update_item.payload)
    assert payload["key"] == _SENTINEL_GOAL_KEY


# ---------------------------------------------------------------------------
# _replace_placeholders: Incoming query — assert return value
# ---------------------------------------------------------------------------


def test_replace_placeholders_replaces_all_patterns(service, make_spinup_request):
    body = (
        "[Insert project name & release] is great. "
        "[Insert project name] rocks. "
        "[Project Name] page. "
        "[Target Date] soon. "
        "[Program] team."
    )
    req = make_spinup_request()

    result = service._replace_placeholders(body, req)

    assert "[Insert project name & release]" not in result
    assert "[Insert project name]" not in result
    assert "[Project Name]" not in result
    assert "[Target Date]" not in result
    assert "[Program]" not in result
    assert "HOP Drop 4" in result
    assert "HOP" in result


def test_replace_placeholders_empty_target_date_becomes_tbd(service, make_spinup_request):
    body = "[Target Date] is the deadline"
    req = make_spinup_request(target_date="")

    result = service._replace_placeholders(body, req)

    assert "TBD" in result


# ---------------------------------------------------------------------------
# _resolve_sentinels: Incoming query — assert return value
# ---------------------------------------------------------------------------


def test_resolve_sentinels_replaces_charter_page_id(service, tmp_db):
    with get_db(tmp_db) as conn:
        conn.execute(
            "INSERT INTO projects (id, jira_goal_key, name, status) VALUES (?, ?, ?, ?)",
            (100, "pending", "Test", "spinning_up"),
        )
        conn.execute(
            """INSERT INTO approval_queue
               (project_id, action_type, payload, preview, status, result)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (100, "create_confluence_page", '{}', "Charter",
             "executed", json.dumps({"id": "55555", "title": "HOP Charter"})),
        )
        conn.commit()
    payload = {"parent_id": _SENTINEL_CHARTER_PAGE_ID}

    result = service._resolve_sentinels(payload, 100)

    assert result["parent_id"] == "55555"


def test_resolve_sentinels_replaces_goal_key(service, tmp_db):
    with get_db(tmp_db) as conn:
        conn.execute(
            "INSERT INTO projects (id, jira_goal_key, name, status) VALUES (?, ?, ?, ?)",
            (200, "pending", "Test2", "spinning_up"),
        )
        conn.execute(
            """INSERT INTO approval_queue
               (project_id, action_type, payload, preview, status, result)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (200, "create_jira_issue", '{}', "Goal",
             "executed", json.dumps({"key": "PROG-999"})),
        )
        conn.commit()
    payload = {"key": _SENTINEL_GOAL_KEY}

    result = service._resolve_sentinels(payload, 200)

    assert result["key"] == "PROG-999"


# ---------------------------------------------------------------------------
# _build_goal_description: Incoming query — assert return value
# ---------------------------------------------------------------------------


def test_build_goal_description_returns_adf_with_inline_cards(service):
    with patch("src.services.spinup.settings") as mock_settings:
        mock_settings.atlassian.domain = "test-company"

        result = service._build_goal_description("111", "222")

    assert result["type"] == "doc"
    assert result["version"] == 1
    content = result["content"]
    assert len(content) == 2  # charter + XFT paragraphs
    first_para = content[0]["content"]
    assert any(c.get("type") == "inlineCard" for c in first_para)
