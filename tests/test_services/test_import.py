"""Tests for import project service — ADF parsing, save, duplicate detection, delete."""

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
    extract_confluence_page_ids,
    guess_charter_xft,
)

_SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "samples"


def _load_json(relpath: str) -> Any:
    with open(_SAMPLES_DIR / relpath) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# ADF parsing tests
# ---------------------------------------------------------------------------

class TestExtractConfluencePageIds:
    def test_extracts_from_real_prog256(self) -> None:
        """Validate against real sample data (prog-256.json)."""
        issue = _load_json("jira/prog-256.json")
        adf = issue["fields"]["description"]
        pages = extract_confluence_page_ids(adf)

        page_ids = [p.page_id for p in pages]
        assert "3559365026" in page_ids
        assert "3559365007" in page_ids

    def test_extracts_slugs(self) -> None:
        issue = _load_json("jira/prog-256.json")
        adf = issue["fields"]["description"]
        pages = extract_confluence_page_ids(adf)

        by_id = {p.page_id: p for p in pages}
        assert "FPL" in by_id["3559365026"].slug
        assert "Scope" in by_id["3559365007"].slug

    def test_empty_adf_returns_empty(self) -> None:
        assert extract_confluence_page_ids(None) == []
        assert extract_confluence_page_ids({}) == []

    def test_no_inline_cards(self) -> None:
        adf = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "No links here"}]},
            ],
        }
        assert extract_confluence_page_ids(adf) == []

    def test_non_confluence_urls_ignored(self) -> None:
        adf = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "inlineCard",
                            "attrs": {"url": "https://example.com/not-confluence"},
                        },
                    ],
                },
            ],
        }
        assert extract_confluence_page_ids(adf) == []


# ---------------------------------------------------------------------------
# Charter/XFT guessing tests
# ---------------------------------------------------------------------------

class TestGuessCharterXft:
    def test_fpl_and_scope_slugs(self) -> None:
        pages = [
            DetectedPage(page_id="100", url="https://x/pages/100/Charter", slug="Charter"),
            DetectedPage(page_id="200", url="https://x/pages/200/Scope", slug="Scope"),
        ]
        charter, xft = guess_charter_xft(pages)
        assert charter == "100"
        assert xft == "200"

    def test_fpl_slug(self) -> None:
        pages = [
            DetectedPage(page_id="100", url="https://x/pages/100/V2-FPL", slug="V2 FPL"),
            DetectedPage(page_id="200", url="https://x/pages/200/V2-XFT", slug="V2 XFT"),
        ]
        charter, xft = guess_charter_xft(pages)
        assert charter == "100"
        assert xft == "200"

    def test_real_prog256_pages(self) -> None:
        """Test with real page data from prog-256."""
        pages = [
            DetectedPage(page_id="3559365026", url="https://x/pages/3559365026/V2+Drop+2+-+FPL", slug="V2 Drop 2 - FPL"),
            DetectedPage(page_id="3559365007", url="https://x/pages/3559365007/V2+Drop+2+Scope", slug="V2 Drop 2 Scope"),
        ]
        charter, xft = guess_charter_xft(pages)
        assert charter == "3559365026"
        assert xft == "3559365007"

    def test_fallback_two_pages(self) -> None:
        pages = [
            DetectedPage(page_id="100", url="https://x/pages/100/Page-A", slug="Page A"),
            DetectedPage(page_id="200", url="https://x/pages/200/Page-B", slug="Page B"),
        ]
        charter, xft = guess_charter_xft(pages)
        assert charter == "100"
        assert xft == "200"

    def test_no_pages_returns_none(self) -> None:
        charter, xft = guess_charter_xft([])
        assert charter is None
        assert xft is None

    def test_single_page_no_match(self) -> None:
        pages = [
            DetectedPage(page_id="100", url="https://x/pages/100/Random", slug="Random"),
        ]
        charter, xft = guess_charter_xft(pages)
        assert charter is None
        assert xft is None


# ---------------------------------------------------------------------------
# ImportService tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    return db_path


class TestSaveProject:
    def test_saves_and_returns_id(self, tmp_db: str) -> None:
        service = ImportService(db_path=tmp_db)
        pid = service.save_project("PROG-256", "HOP Drop 2", "100", "200")
        assert pid > 0

        with get_db(tmp_db) as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
        assert row["jira_goal_key"] == "PROG-256"
        assert row["name"] == "HOP Drop 2"
        assert row["confluence_charter_id"] == "100"
        assert row["confluence_xft_id"] == "200"
        assert row["status"] == "active"

    def test_saves_without_page_ids(self, tmp_db: str) -> None:
        service = ImportService(db_path=tmp_db)
        pid = service.save_project("PROG-300", "Minimal Project")
        assert pid > 0

        with get_db(tmp_db) as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
        assert row["confluence_charter_id"] is None
        assert row["confluence_xft_id"] is None

    def test_duplicate_detection(self, tmp_db: str) -> None:
        service = ImportService(db_path=tmp_db)
        service.save_project("PROG-256", "HOP Drop 2")

        with pytest.raises(ValueError, match="already exists"):
            service.save_project("PROG-256", "HOP Drop 2 Again")


class TestDeleteProject:
    def test_deletes_project_and_related_data(self, tmp_db: str) -> None:
        service = ImportService(db_path=tmp_db)
        pid = service.save_project("PROG-500", "To Delete")

        # Insert related rows
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

    def test_delete_nonexistent_is_safe(self, tmp_db: str) -> None:
        """Deleting a non-existent project should not raise."""
        service = ImportService(db_path=tmp_db)
        service.delete_project(99999)  # Should not raise


class TestFetchPreview:
    @pytest.mark.asyncio
    async def test_fetch_preview_returns_preview(self, tmp_db: str) -> None:
        mock_issue = {
            "fields": {
                "summary": "HOP Drop 2",
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "inlineCard",
                                    "attrs": {
                                        "url": "https://harrison-ai.atlassian.net/wiki/spaces/HPP/pages/123/Charter"
                                    },
                                },
                                {
                                    "type": "inlineCard",
                                    "attrs": {
                                        "url": "https://harrison-ai.atlassian.net/wiki/spaces/HPP/pages/456/Scope"
                                    },
                                },
                            ],
                        },
                    ],
                },
            },
        }

        service = ImportService(db_path=tmp_db)
        with patch("src.services.import_project.JiraConnector") as MockJira:
            instance = MockJira.return_value
            instance.get_issue = AsyncMock(return_value=mock_issue)
            instance.close = AsyncMock()

            preview = await service.fetch_preview("PROG-256")

        assert preview.goal_key == "PROG-256"
        assert preview.goal_summary == "HOP Drop 2"
        assert len(preview.detected_pages) == 2
        assert preview.charter_id == "123"
        assert preview.xft_id == "456"
