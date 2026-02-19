"""Tests for the DHF service — version parsing, document matching, and summary."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.base import ConnectorError
from src.models.dhf import DHFDocument, DHFSummary, DocumentStatus
from src.services.dhf import DHFService, _parse_version, _strip_version


# ---------------------------------------------------------------------------
# _parse_version: Incoming query — assert return value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("title,expected", [
    pytest.param("Risk Plan [V2]", "2", id="single-digit"),
    pytest.param("Doc [V12]", "12", id="multi-digit"),
    pytest.param("Risk Plan", None, id="no-version"),
])
def test_parse_version_extracts_from_title(title, expected):
    result = _parse_version(title)

    assert result == expected


# ---------------------------------------------------------------------------
# _strip_version: Incoming query — assert return value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("title,expected", [
    pytest.param("Risk Plan [V2]", "Risk Plan", id="removes-suffix"),
    pytest.param("Risk Plan", "Risk Plan", id="no-version-unchanged"),
])
def test_strip_version_removes_suffix(title, expected):
    result = _strip_version(title)

    assert result == expected


# ---------------------------------------------------------------------------
# _match_documents: Incoming query — assert return value
# ---------------------------------------------------------------------------


def test_match_documents_both_draft_and_released(make_raw_dhf_doc):
    draft = [make_raw_dhf_doc(page_id="d1", title="Plan", version="3", document_id="abc")]
    released = [make_raw_dhf_doc(page_id="r1", title="Plan", version="2", document_id="abc")]

    result = DHFService._match_documents(draft, released)

    assert len(result) == 1
    assert result[0].status == DocumentStatus.DRAFT_UPDATE
    assert result[0].released_version == "2"
    assert result[0].draft_version == "3"


def test_match_documents_released_only(make_raw_dhf_doc):
    draft = []
    released = [make_raw_dhf_doc(page_id="r1", title="Plan", version="2", document_id="abc")]

    result = DHFService._match_documents(draft, released)

    assert len(result) == 1
    assert result[0].status == DocumentStatus.RELEASED


def test_match_documents_draft_only_with_id(make_raw_dhf_doc):
    draft = [make_raw_dhf_doc(page_id="d1", title="Plan", version="1", document_id="abc")]
    released = []

    result = DHFService._match_documents(draft, released)

    assert len(result) == 1
    assert result[0].status == DocumentStatus.IN_DRAFT


def test_match_documents_draft_without_document_id(make_raw_dhf_doc):
    draft = [make_raw_dhf_doc(page_id="d1", title="New Doc", document_id=None)]
    released = []

    result = DHFService._match_documents(draft, released)

    assert len(result) == 1
    assert result[0].status == DocumentStatus.IN_DRAFT
    assert result[0].title == "New Doc"


def test_match_documents_multiple_documents_classified_correctly(make_raw_dhf_doc):
    draft = [
        make_raw_dhf_doc(page_id="d1", title="A", document_id="id-a", version="2"),
        make_raw_dhf_doc(page_id="d2", title="B", document_id=None, version="1"),
    ]
    released = [
        make_raw_dhf_doc(page_id="r1", title="A", document_id="id-a", version="1"),
        make_raw_dhf_doc(page_id="r2", title="C", document_id="id-c", version="1"),
    ]

    result = DHFService._match_documents(draft, released)

    assert len(result) == 3
    statuses = {d.title: d.status for d in result}
    assert statuses["A"] == DocumentStatus.DRAFT_UPDATE
    assert statuses["B"] == DocumentStatus.IN_DRAFT
    assert statuses["C"] == DocumentStatus.RELEASED


# ---------------------------------------------------------------------------
# get_dhf_summary: Incoming query (async) — assert return value
# ---------------------------------------------------------------------------


async def test_get_dhf_summary_no_config_returns_empty(make_project):
    project = make_project(dhf_draft_root_id=None, dhf_released_root_id=None)
    service = DHFService()

    result = await service.get_dhf_summary(project)

    assert result.total_count == 0
    assert result.error is None


async def test_get_dhf_summary_returns_counts(make_project):
    project = make_project(dhf_draft_root_id="100", dhf_released_root_id="200")
    service = DHFService()
    docs = [
        DHFDocument("A", "Area1", "1", None, DocumentStatus.RELEASED, "", "", ""),
        DHFDocument("B", "Area1", "1", "2", DocumentStatus.DRAFT_UPDATE, "", "", ""),
        DHFDocument("C", "Area2", None, "1", DocumentStatus.IN_DRAFT, "", "", ""),
    ]

    with patch.object(service, "get_dhf_table", new=AsyncMock(return_value=(docs, ["Area1", "Area2"]))):
        result = await service.get_dhf_summary(project)

    assert result.total_count == 3
    assert result.released_count == 1
    assert result.draft_update_count == 1
    assert result.in_draft_count == 1


async def test_get_dhf_summary_connector_error_returns_error(make_project):
    project = make_project(dhf_draft_root_id="100", dhf_released_root_id="200")
    service = DHFService()

    with patch.object(service, "get_dhf_table", new=AsyncMock(side_effect=ConnectorError(500, "fail"))):
        result = await service.get_dhf_summary(project)

    assert result.total_count == 0
    assert result.error is not None


# ---------------------------------------------------------------------------
# _resolve_human_author: Incoming query (async) — assert return value
# ---------------------------------------------------------------------------


async def test_resolve_human_author_returns_human_name():
    connector = AsyncMock()
    connector.get_user_display_name = AsyncMock(return_value="Jane Doe")

    result = await DHFService._resolve_human_author(
        connector, "page1", {"authorId": "user-123"}, {}
    )

    assert result == "Jane Doe"


async def test_resolve_human_author_skips_softcomply_falls_back_to_history():
    connector = AsyncMock()
    connector.get_user_display_name = AsyncMock(side_effect=["SoftComply Bot", "Jane Doe"])
    connector.get_page_versions = AsyncMock(return_value=[
        {"authorId": "user-human"},
    ])

    result = await DHFService._resolve_human_author(
        connector, "page1", {"authorId": "user-bot"}, {}
    )

    assert result == "Jane Doe"
