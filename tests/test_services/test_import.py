"""Tests for import project service — ADF parsing, charter/XFT guessing, save, delete."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.database import get_db, init_db
from src.services.import_project import (
    DetectedPage,
    ImportPreview,
    ImportService,
    _detect_team_projects,
    extract_confluence_page_ids,
    guess_charter_xft,
)

_SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "samples"


def _load_json(relpath: str) -> Any:
    with open(_SAMPLES_DIR / relpath) as f:
        return json.load(f)


# Need a local tmp_db fixture because this module defines its own
@pytest.fixture()
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# extract_confluence_page_ids: Incoming query — assert return value
# ---------------------------------------------------------------------------


def test_extract_confluence_page_ids_from_real_sample():
    issue = _load_json("jira/prog-256.json")
    adf = issue["fields"]["description"]

    result = extract_confluence_page_ids(adf)

    page_ids = [p.page_id for p in result]
    assert "3559365026" in page_ids
    assert "3559365007" in page_ids


def test_extract_confluence_page_ids_extracts_slugs():
    issue = _load_json("jira/prog-256.json")
    adf = issue["fields"]["description"]

    result = extract_confluence_page_ids(adf)

    by_id = {p.page_id: p for p in result}
    assert "FPL" in by_id["3559365026"].slug
    assert "Scope" in by_id["3559365007"].slug


@pytest.mark.parametrize("adf", [
    pytest.param(None, id="none-adf"),
    pytest.param({}, id="empty-dict"),
])
def test_extract_confluence_page_ids_empty_adf_returns_empty(adf):
    result = extract_confluence_page_ids(adf)

    assert result == []


def test_extract_confluence_page_ids_no_inline_cards_returns_empty():
    adf = {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "No links here"}]},
        ],
    }

    result = extract_confluence_page_ids(adf)

    assert result == []


def test_extract_confluence_page_ids_non_confluence_urls_ignored():
    adf = {
        "type": "doc",
        "version": 1,
        "content": [{
            "type": "paragraph",
            "content": [{
                "type": "inlineCard",
                "attrs": {"url": "https://example.com/not-confluence"},
            }],
        }],
    }

    result = extract_confluence_page_ids(adf)

    assert result == []


# ---------------------------------------------------------------------------
# guess_charter_xft: Incoming query — assert return value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug1,slug2,expected_charter,expected_xft", [
    pytest.param("Charter", "Scope", "100", "200", id="charter-scope-slugs"),
    pytest.param("V2 FPL", "V2 XFT", "100", "200", id="fpl-xft-slugs"),
])
def test_guess_charter_xft_by_slug_keywords(slug1, slug2, expected_charter, expected_xft):
    pages = [
        DetectedPage(page_id="100", url="https://x/pages/100/A", slug=slug1),
        DetectedPage(page_id="200", url="https://x/pages/200/B", slug=slug2),
    ]

    result = guess_charter_xft(pages)

    assert result == (expected_charter, expected_xft)


def test_guess_charter_xft_real_prog256_pages():
    pages = [
        DetectedPage(page_id="3559365026", url="https://x/pages/3559365026/V2+Drop+2+-+FPL", slug="V2 Drop 2 - FPL"),
        DetectedPage(page_id="3559365007", url="https://x/pages/3559365007/V2+Drop+2+Scope", slug="V2 Drop 2 Scope"),
    ]

    result = guess_charter_xft(pages)

    assert result == ("3559365026", "3559365007")


def test_guess_charter_xft_fallback_two_unknown_pages():
    pages = [
        DetectedPage(page_id="100", url="https://x/pages/100/Page-A", slug="Page A"),
        DetectedPage(page_id="200", url="https://x/pages/200/Page-B", slug="Page B"),
    ]

    result = guess_charter_xft(pages)

    assert result == ("100", "200")


def test_guess_charter_xft_no_pages_returns_none():
    result = guess_charter_xft([])

    assert result == (None, None)


def test_guess_charter_xft_single_unmatched_page_returns_none():
    pages = [
        DetectedPage(page_id="100", url="https://x/pages/100/Random", slug="Random"),
    ]

    result = guess_charter_xft(pages)

    assert result == (None, None)


# ---------------------------------------------------------------------------
# _detect_team_projects: Incoming query — assert return value
# ---------------------------------------------------------------------------


def test_detect_team_projects_extracts_unique_keys_and_versions():
    initiatives = [
        {"fields": {"project": {"key": "AIM"}, "fixVersions": [{"name": "HOP Drop 2"}]}},
        {"fields": {"project": {"key": "AIM"}, "fixVersions": [{"name": "HOP Drop 2"}]}},
        {"fields": {"project": {"key": "CTCV"}, "fixVersions": [{"name": "HOP Drop 3"}]}},
    ]

    result = _detect_team_projects(initiatives)

    assert result == {"AIM": "HOP Drop 2", "CTCV": "HOP Drop 3"}


def test_detect_team_projects_excludes_prog_and_risk():
    initiatives = [
        {"fields": {"project": {"key": "PROG"}, "fixVersions": [{"name": "v1"}]}},
        {"fields": {"project": {"key": "RISK"}, "fixVersions": [{"name": "v1"}]}},
        {"fields": {"project": {"key": "AIM"}, "fixVersions": [{"name": "v1"}]}},
    ]

    result = _detect_team_projects(initiatives)

    assert result == {"AIM": "v1"}


def test_detect_team_projects_no_fix_version_returns_empty_string():
    initiatives = [
        {"fields": {"project": {"key": "AIM"}, "fixVersions": []}},
    ]

    result = _detect_team_projects(initiatives)

    assert result == {"AIM": ""}


def test_detect_team_projects_empty_list():
    result = _detect_team_projects([])

    assert result == {}


# ---------------------------------------------------------------------------
# ImportService.save_project: Incoming command — assert side effect
# ---------------------------------------------------------------------------


def test_save_project_inserts_and_returns_id(tmp_db):
    service = ImportService(db_path=tmp_db)

    result = service.save_project("PROG-256", "HOP Drop 2", "100", "200")

    assert result > 0
    with get_db(tmp_db) as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (result,)).fetchone()
    assert row["jira_goal_key"] == "PROG-256"
    assert row["name"] == "HOP Drop 2"
    assert row["confluence_charter_id"] == "100"
    assert row["confluence_xft_id"] == "200"
    assert row["status"] == "active"


def test_save_project_stores_jira_plan_url(tmp_db):
    service = ImportService(db_path=tmp_db)
    url = "https://test.atlassian.net/jira/plans/1/scenarios/1"

    result = service.save_project("PROG-800", "Plan Project", jira_plan_url=url)

    with get_db(tmp_db) as conn:
        row = conn.execute("SELECT jira_plan_url FROM projects WHERE id = ?", (result,)).fetchone()
    assert row["jira_plan_url"] == url


def test_save_project_without_page_ids(tmp_db):
    service = ImportService(db_path=tmp_db)

    result = service.save_project("PROG-300", "Minimal Project")

    assert result > 0
    with get_db(tmp_db) as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (result,)).fetchone()
    assert row["confluence_charter_id"] is None
    assert row["confluence_xft_id"] is None


def test_save_project_duplicate_raises_value_error(tmp_db):
    service = ImportService(db_path=tmp_db)
    service.save_project("PROG-256", "HOP Drop 2")

    with pytest.raises(ValueError, match="already exists"):
        service.save_project("PROG-256", "HOP Drop 2 Again")


# ---------------------------------------------------------------------------
# ImportService.delete_project: Incoming command — assert side effect
# ---------------------------------------------------------------------------


def test_delete_project_cascades_to_related_tables(tmp_db):
    service = ImportService(db_path=tmp_db)
    pid = service.save_project("PROG-500", "To Delete")
    with get_db(tmp_db) as conn:
        conn.execute(
            "INSERT INTO approval_queue (project_id, action_type, payload) VALUES (?, ?, ?)",
            (pid, "test", "{}"),
        )
        conn.execute(
            "INSERT INTO approval_log (project_id, action_type, payload) VALUES (?, ?, ?)",
            (pid, "test", "{}"),
        )
        conn.execute(
            "INSERT INTO transcript_cache (project_id, filename, raw_text) VALUES (?, ?, ?)",
            (pid, "test.txt", "content"),
        )
        conn.commit()

    service.delete_project(pid)

    with get_db(tmp_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM projects WHERE id = ?", (pid,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM approval_queue WHERE project_id = ?", (pid,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM approval_log WHERE project_id = ?", (pid,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM transcript_cache WHERE project_id = ?", (pid,)).fetchone()[0] == 0


def test_delete_project_nonexistent_does_not_raise(tmp_db):
    service = ImportService(db_path=tmp_db)

    result = service.delete_project(99999)  # Should not raise

    assert result is None


# ---------------------------------------------------------------------------
# ImportService.fetch_preview: Incoming query (async) — assert return value
# ---------------------------------------------------------------------------


async def test_fetch_preview_returns_preview_with_detected_pages(tmp_db):
    mock_issue = {
        "fields": {
            "summary": "HOP Drop 2",
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "inlineCard",
                            "attrs": {"url": "https://harrison-ai.atlassian.net/wiki/spaces/HPP/pages/123/Charter"},
                        },
                        {
                            "type": "inlineCard",
                            "attrs": {"url": "https://harrison-ai.atlassian.net/wiki/spaces/HPP/pages/456/Scope"},
                        },
                    ],
                }],
            },
        },
    }
    service = ImportService(db_path=tmp_db)

    mock_children = [
        {"fields": {"project": {"key": "AIM"}, "fixVersions": [{"name": "HOP Drop 2"}]}},
        {"fields": {"project": {"key": "CTCV"}, "fixVersions": [{"name": "HOP Drop 2"}]}},
    ]

    with patch("src.services.import_project.JiraConnector") as MockJira:
        instance = MockJira.return_value
        instance.get_issue = AsyncMock(return_value=mock_issue)
        instance.search = AsyncMock(return_value=mock_children)
        instance.close = AsyncMock()
        result = await service.fetch_preview("PROG-256")

    assert result.goal_key == "PROG-256"
    assert result.goal_summary == "HOP Drop 2"
    assert len(result.detected_pages) == 2
    assert result.charter_id == "123"
    assert result.xft_id == "456"
    assert result.detected_teams == {"AIM": "HOP Drop 2", "CTCV": "HOP Drop 2"}
