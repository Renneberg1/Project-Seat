"""Tests for DHF domain models."""

from __future__ import annotations

import pytest

from src.models.dhf import DHFDocument, DHFSummary, DocumentStatus


# ---------------------------------------------------------------------------
# DocumentStatus enum: Contract tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("member,expected_value", [
    pytest.param(DocumentStatus.RELEASED, "released", id="released"),
    pytest.param(DocumentStatus.DRAFT_UPDATE, "draft_update", id="draft-update"),
    pytest.param(DocumentStatus.IN_DRAFT, "in_draft", id="in-draft"),
])
def test_document_status_enum_values(member, expected_value):
    result = member.value

    assert result == expected_value


def test_document_status_is_str_mixin():
    result = isinstance(DocumentStatus.RELEASED, str)

    assert result is True
    assert DocumentStatus.RELEASED == "released"


# ---------------------------------------------------------------------------
# DHFDocument: Contract tests
# ---------------------------------------------------------------------------


def test_dhf_document_creation_with_all_fields():
    result = DHFDocument(
        title="Risk Management Plan",
        area="Risk",
        released_version="2",
        draft_version="3",
        status=DocumentStatus.DRAFT_UPDATE,
        last_modified="2026-01-15T10:00:00Z",
        author="Jane Doe",
        page_url="https://example.atlassian.net/wiki/spaces/DRAFT/pages/123",
    )

    assert result.title == "Risk Management Plan"
    assert result.area == "Risk"
    assert result.released_version == "2"
    assert result.draft_version == "3"
    assert result.status == DocumentStatus.DRAFT_UPDATE
    assert result.author == "Jane Doe"


def test_dhf_document_nullable_versions():
    result = DHFDocument(
        title="New Doc",
        area="Design",
        released_version=None,
        draft_version="1",
        status=DocumentStatus.IN_DRAFT,
        last_modified="",
        author="",
        page_url="",
    )

    assert result.released_version is None
    assert result.draft_version == "1"


# ---------------------------------------------------------------------------
# DHFSummary: Contract tests
# ---------------------------------------------------------------------------


def test_dhf_summary_creation_defaults_error_to_none():
    result = DHFSummary(
        total_count=10,
        released_count=5,
        draft_update_count=3,
        in_draft_count=2,
    )

    assert result.total_count == 10
    assert result.error is None


def test_dhf_summary_creation_with_error():
    result = DHFSummary(
        total_count=0,
        released_count=0,
        draft_update_count=0,
        in_draft_count=0,
        error="Connection refused",
    )

    assert result.error == "Connection refused"
