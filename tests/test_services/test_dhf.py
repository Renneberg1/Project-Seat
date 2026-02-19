"""Tests for the DHF service."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.models.dhf import DHFDocument, DHFSummary, DocumentStatus
from src.models.project import Project
from src.services.dhf import DHFService, _parse_version, _strip_version


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_project(**overrides) -> Project:
    defaults = dict(
        id=1, jira_goal_key="PROG-1", name="Alpha",
        confluence_charter_id=None, confluence_xft_id=None,
        status="active", phase="planning", created_at="2026-01-01",
        dhf_draft_root_id="100", dhf_released_root_id="200",
    )
    defaults.update(overrides)
    return Project(**defaults)


def _make_raw_doc(
    page_id: str = "1",
    title: str = "Doc",
    area: str = "Area",
    version: str | None = "1",
    document_id: str | None = "doc-abc",
    last_modified: str = "2026-01-01T00:00:00Z",
    author: str = "Jane",
    page_url: str = "https://example.atlassian.net/wiki/page/1",
) -> dict:
    return {
        "page_id": page_id,
        "title": title,
        "area": area,
        "version": version,
        "document_id": document_id,
        "last_modified": last_modified,
        "author": author,
        "page_url": page_url,
    }


# ---------------------------------------------------------------------------
# Version parsing helpers
# ---------------------------------------------------------------------------

class TestParseVersion:
    def test_extracts_version(self) -> None:
        assert _parse_version("Risk Plan [V2]") == "2"

    def test_no_version(self) -> None:
        assert _parse_version("Risk Plan") is None

    def test_multi_digit(self) -> None:
        assert _parse_version("Doc [V12]") == "12"


class TestStripVersion:
    def test_removes_suffix(self) -> None:
        assert _strip_version("Risk Plan [V2]") == "Risk Plan"

    def test_no_version(self) -> None:
        assert _strip_version("Risk Plan") == "Risk Plan"


# ---------------------------------------------------------------------------
# Document matching
# ---------------------------------------------------------------------------

class TestMatchDocuments:
    def test_both_draft_and_released(self) -> None:
        draft = [_make_raw_doc(page_id="d1", title="Plan", version="3", document_id="abc")]
        released = [_make_raw_doc(page_id="r1", title="Plan", version="2", document_id="abc")]

        rows = DHFService._match_documents(draft, released)
        assert len(rows) == 1
        assert rows[0].status == DocumentStatus.DRAFT_UPDATE
        assert rows[0].released_version == "2"
        assert rows[0].draft_version == "3"

    def test_released_only(self) -> None:
        draft: list[dict] = []
        released = [_make_raw_doc(page_id="r1", title="Plan", version="2", document_id="abc")]

        rows = DHFService._match_documents(draft, released)
        assert len(rows) == 1
        assert rows[0].status == DocumentStatus.RELEASED

    def test_draft_only_with_id(self) -> None:
        draft = [_make_raw_doc(page_id="d1", title="Plan", version="1", document_id="abc")]
        released: list[dict] = []

        rows = DHFService._match_documents(draft, released)
        assert len(rows) == 1
        assert rows[0].status == DocumentStatus.IN_DRAFT

    def test_draft_without_document_id(self) -> None:
        draft = [_make_raw_doc(page_id="d1", title="New Doc", document_id=None)]
        released: list[dict] = []

        rows = DHFService._match_documents(draft, released)
        assert len(rows) == 1
        assert rows[0].status == DocumentStatus.IN_DRAFT
        assert rows[0].title == "New Doc"

    def test_multiple_documents(self) -> None:
        draft = [
            _make_raw_doc(page_id="d1", title="A", document_id="id-a", version="2"),
            _make_raw_doc(page_id="d2", title="B", document_id=None, version="1"),
        ]
        released = [
            _make_raw_doc(page_id="r1", title="A", document_id="id-a", version="1"),
            _make_raw_doc(page_id="r2", title="C", document_id="id-c", version="1"),
        ]

        rows = DHFService._match_documents(draft, released)
        assert len(rows) == 3
        statuses = {d.title: d.status for d in rows}
        assert statuses["A"] == DocumentStatus.DRAFT_UPDATE
        assert statuses["B"] == DocumentStatus.IN_DRAFT
        assert statuses["C"] == DocumentStatus.RELEASED


# ---------------------------------------------------------------------------
# DHF Summary
# ---------------------------------------------------------------------------

class TestGetDHFSummary:
    async def test_no_config_returns_empty(self) -> None:
        project = _make_project(dhf_draft_root_id=None, dhf_released_root_id=None)
        service = DHFService()
        summary = await service.get_dhf_summary(project)
        assert summary.total_count == 0
        assert summary.error is None

    async def test_returns_counts(self) -> None:
        project = _make_project()
        service = DHFService()

        docs = [
            DHFDocument("A", "Area1", "1", None, DocumentStatus.RELEASED, "", "", ""),
            DHFDocument("B", "Area1", "1", "2", DocumentStatus.DRAFT_UPDATE, "", "", ""),
            DHFDocument("C", "Area2", None, "1", DocumentStatus.IN_DRAFT, "", "", ""),
        ]

        with patch.object(service, "get_dhf_table", new=AsyncMock(return_value=(docs, ["Area1", "Area2"]))):
            summary = await service.get_dhf_summary(project)

        assert summary.total_count == 3
        assert summary.released_count == 1
        assert summary.draft_update_count == 1
        assert summary.in_draft_count == 1

    async def test_connector_error_returns_error_summary(self) -> None:
        from src.connectors.base import ConnectorError

        project = _make_project()
        service = DHFService()

        with patch.object(service, "get_dhf_table", new=AsyncMock(side_effect=ConnectorError(500, "fail"))):
            summary = await service.get_dhf_summary(project)

        assert summary.total_count == 0
        assert summary.error is not None


# ---------------------------------------------------------------------------
# Resolve human author
# ---------------------------------------------------------------------------

class TestResolveHumanAuthor:
    async def test_returns_human_author(self) -> None:
        connector = AsyncMock()
        connector.get_user_display_name = AsyncMock(return_value="Jane Doe")

        result = await DHFService._resolve_human_author(
            connector, "page1", {"authorId": "user-123"}, {}
        )
        assert result == "Jane Doe"

    async def test_skips_softcomply_falls_back_to_history(self) -> None:
        connector = AsyncMock()
        connector.get_user_display_name = AsyncMock(side_effect=["SoftComply Bot", "Jane Doe"])
        connector.get_page_versions = AsyncMock(return_value=[
            {"authorId": "user-human"},
        ])

        result = await DHFService._resolve_human_author(
            connector, "page1", {"authorId": "user-bot"}, {}
        )
        assert result == "Jane Doe"
