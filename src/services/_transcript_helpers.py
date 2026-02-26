"""Shared helpers for transcript-related services."""

from __future__ import annotations

from typing import Any

from src.models.transcript import SuggestionType, TranscriptSuggestion


def get_suggestion(db_path: str, suggestion_id: int) -> TranscriptSuggestion | None:
    """Fetch a single transcript suggestion by ID."""
    from src.repositories.transcript_repo import TranscriptRepository
    repo = TranscriptRepository(db_path)
    return repo.get_suggestion(suggestion_id)


def build_preview(suggestion: dict[str, Any], stype: SuggestionType) -> str:
    """Build a human-readable preview string for a suggestion."""
    lines: list[str] = []
    lines.append(f"Type: {stype.value}")
    lines.append(f"Title: {suggestion.get('title', 'Untitled')}")
    if suggestion.get("priority"):
        lines.append(f"Priority: {suggestion['priority']}")
    if suggestion.get("confidence"):
        lines.append(f"Confidence: {suggestion['confidence']:.0%}")
    if suggestion.get("background"):
        lines.append(f"Background: {suggestion['background'][:200]}")
    if suggestion.get("evidence"):
        lines.append(f"Evidence: {suggestion['evidence'][:200]}")
    return "\n".join(lines)


def extract_adf_text(adf_doc: dict[str, Any] | None) -> str:
    """Extract plain text from an ADF document structure."""
    if not adf_doc or not isinstance(adf_doc, dict):
        return ""
    texts: list[str] = []
    for node in adf_doc.get("content", []):
        if node.get("type") == "paragraph":
            for child in node.get("content", []):
                if child.get("type") == "text":
                    text = child.get("text", "")
                    # Skip section headers (bold-only paragraphs)
                    marks = child.get("marks", [])
                    is_heading = any(m.get("type") == "strong" for m in marks)
                    if not is_heading:
                        texts.append(text)
    return " ".join(texts).strip()
