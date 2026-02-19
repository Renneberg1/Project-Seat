"""Tests for DHF domain models."""

from __future__ import annotations

from src.models.dhf import DHFDocument, DHFSummary, DocumentStatus


class TestDocumentStatus:
    def test_enum_values(self) -> None:
        assert DocumentStatus.RELEASED.value == "released"
        assert DocumentStatus.DRAFT_UPDATE.value == "draft_update"
        assert DocumentStatus.IN_DRAFT.value == "in_draft"

    def test_str_mixin(self) -> None:
        # DocumentStatus inherits from str
        assert isinstance(DocumentStatus.RELEASED, str)
        assert DocumentStatus.RELEASED == "released"


class TestDHFDocument:
    def test_creation(self) -> None:
        doc = DHFDocument(
            title="Risk Management Plan",
            area="Risk",
            released_version="2",
            draft_version="3",
            status=DocumentStatus.DRAFT_UPDATE,
            last_modified="2026-01-15T10:00:00Z",
            author="Jane Doe",
            page_url="https://example.atlassian.net/wiki/spaces/DRAFT/pages/123",
        )
        assert doc.title == "Risk Management Plan"
        assert doc.area == "Risk"
        assert doc.released_version == "2"
        assert doc.draft_version == "3"
        assert doc.status == DocumentStatus.DRAFT_UPDATE
        assert doc.author == "Jane Doe"

    def test_nullable_versions(self) -> None:
        doc = DHFDocument(
            title="New Doc",
            area="Design",
            released_version=None,
            draft_version="1",
            status=DocumentStatus.IN_DRAFT,
            last_modified="",
            author="",
            page_url="",
        )
        assert doc.released_version is None
        assert doc.draft_version == "1"


class TestDHFSummary:
    def test_creation(self) -> None:
        summary = DHFSummary(
            total_count=10,
            released_count=5,
            draft_update_count=3,
            in_draft_count=2,
        )
        assert summary.total_count == 10
        assert summary.error is None

    def test_with_error(self) -> None:
        summary = DHFSummary(
            total_count=0,
            released_count=0,
            draft_update_count=0,
            in_draft_count=0,
            error="Connection refused",
        )
        assert summary.error == "Connection refused"
