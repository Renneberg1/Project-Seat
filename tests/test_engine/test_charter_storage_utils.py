"""Tests for Charter XHTML section extraction and replacement."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engine.charter_storage_utils import extract_sections, replace_section_content

_SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "samples"


@pytest.fixture(scope="module")
def charter_body() -> str:
    """Load the real Charter template storage body from sample data."""
    with open(_SAMPLES_DIR / "confluence" / "charter-template.json") as f:
        data = json.load(f)
    return data["body"]["storage"]["value"]


# ---------------------------------------------------------------------------
# extract_sections
# ---------------------------------------------------------------------------


class TestExtractSections:

    def test_extracts_all_expected_sections(self, charter_body):
        sections = extract_sections(charter_body)
        names = [s["name"] for s in sections]

        assert "Project Name/Release" in names
        assert "Date" in names
        assert "Project Manager" in names
        assert "Executive Sponsor" in names
        assert "Status" in names
        assert "OKR alignment" in names
        assert "Commercial Objective" in names
        assert "Commercial Driver" in names
        assert "Success Criteria" in names
        assert "Stakeholders" in names

    def test_handles_rowspan_project_scope(self, charter_body):
        sections = extract_sections(charter_body)
        names = [s["name"] for s in sections]

        assert "Project Scope — In Scope" in names
        assert "Project Scope — Out of Scope" in names

    def test_in_scope_has_content(self, charter_body):
        sections = extract_sections(charter_body)
        in_scope = next(s for s in sections if s["name"] == "Project Scope — In Scope")
        assert "In Scope" in in_scope["content"]

    def test_out_of_scope_has_content(self, charter_body):
        sections = extract_sections(charter_body)
        out_scope = next(s for s in sections if s["name"] == "Project Scope — Out of Scope")
        assert "Out of Scope" in out_scope["content"]

    def test_returns_plain_text_content(self, charter_body):
        sections = extract_sections(charter_body)
        # Content should not contain HTML tags
        for section in sections:
            assert "<th" not in section["content"]
            assert "<td" not in section["content"]

    def test_empty_body_returns_empty_list(self):
        assert extract_sections("") == []
        assert extract_sections("<p>No table here</p>") == []

    def test_section_count(self, charter_body):
        sections = extract_sections(charter_body)
        # Template has: Project Name, Date, Project Manager, Executive Sponsor,
        # Status, OKR alignment, Commercial Objective, Project Scope In, Out,
        # Commercial Driver, Success Criteria, Stakeholders = 12
        assert len(sections) == 12


# ---------------------------------------------------------------------------
# replace_section_content
# ---------------------------------------------------------------------------


class TestReplaceSectionContent:

    def test_replace_simple_section(self, charter_body):
        result = replace_section_content(
            charter_body,
            "Commercial Objective",
            "Launch AI-powered triage for emergency departments.",
        )
        assert "Launch AI-powered triage" in result
        # Original placeholder should be gone
        assert "[Description of the project" not in result

    def test_replace_preserves_other_sections(self, charter_body):
        result = replace_section_content(
            charter_body,
            "Date",
            "2026-03-01",
        )
        # Other sections still present
        assert "Project Manager" in result
        assert "Commercial Objective" in result

    def test_replace_in_scope(self, charter_body):
        result = replace_section_content(
            charter_body,
            "Project Scope — In Scope",
            "New scope items: CTCV integration, AIM model v2",
        )
        assert "New scope items" in result

    def test_replace_out_of_scope(self, charter_body):
        result = replace_section_content(
            charter_body,
            "Project Scope — Out of Scope",
            "Mobile app development is out of scope.",
        )
        assert "Mobile app development" in result

    def test_unknown_section_raises(self, charter_body):
        with pytest.raises(ValueError, match="Charter section not found"):
            replace_section_content(
                charter_body,
                "Nonexistent Section",
                "content",
            )

    def test_html_escaping(self, charter_body):
        result = replace_section_content(
            charter_body,
            "Commercial Objective",
            "Revenue > $1M & <critical> objective",
        )
        # Should be escaped
        assert "&gt;" in result
        assert "&amp;" in result
        assert "&lt;critical&gt;" in result

    def test_roundtrip_extract_after_replace(self, charter_body):
        """Replace a section, then re-extract and verify the new content."""
        new_text = "Updated commercial objective text here"
        modified = replace_section_content(
            charter_body,
            "Commercial Objective",
            new_text,
        )
        sections = extract_sections(modified)
        obj = next(s for s in sections if s["name"] == "Commercial Objective")
        assert obj["content"] == new_text

    def test_raw_xhtml_inserts_verbatim(self, charter_body):
        """raw_xhtml=True should insert HTML without escaping or <p> wrapping."""
        raw_content = '<ul><li>Item one</li><li>Item &amp; two</li></ul>'
        modified = replace_section_content(
            charter_body,
            "Commercial Objective",
            raw_content,
            raw_xhtml=True,
        )
        # Raw HTML should appear verbatim in the output
        assert raw_content in modified
        # Should NOT be wrapped in extra <p> tags
        assert f"<p>{raw_content}</p>" not in modified
