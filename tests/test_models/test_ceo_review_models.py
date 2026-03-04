"""Tests for CEO Review domain models."""

from __future__ import annotations

import json

from src.models.ceo_review import CeoReview, CeoReviewStatus


# ---------------------------------------------------------------------------
# CeoReviewStatus enum
# ---------------------------------------------------------------------------


def test_ceo_review_status_values():
    assert CeoReviewStatus.DRAFT.value == "draft"
    assert CeoReviewStatus.QUEUED.value == "queued"
    assert CeoReviewStatus.PUBLISHED.value == "published"
    assert CeoReviewStatus.REJECTED.value == "rejected"


def test_ceo_review_status_is_str_enum():
    """CeoReviewStatus members are also plain strings."""
    assert isinstance(CeoReviewStatus.DRAFT, str)
    assert CeoReviewStatus.PUBLISHED == "published"


def test_ceo_review_status_all_members():
    members = {s.value for s in CeoReviewStatus}
    assert members == {"draft", "queued", "published", "rejected"}


# ---------------------------------------------------------------------------
# CeoReview.from_row
# ---------------------------------------------------------------------------


def _make_ceo_review_row(
    *,
    id: int = 1,
    project_id: int = 42,
    review_json: str = '{"health": "green"}',
    confluence_body: str = "<p>Review body</p>",
    approval_item_id: int | None = 10,
    status: str = "draft",
    created_at: str = "2026-03-01T10:00:00",
) -> dict:
    return {
        "id": id,
        "project_id": project_id,
        "review_json": review_json,
        "confluence_body": confluence_body,
        "approval_item_id": approval_item_id,
        "status": status,
        "created_at": created_at,
    }


def test_ceo_review_from_row_all_fields():
    row = _make_ceo_review_row()
    review = CeoReview.from_row(row)

    assert review.id == 1
    assert review.project_id == 42
    assert review.review_json == {"health": "green"}
    assert review.confluence_body == "<p>Review body</p>"
    assert review.approval_item_id == 10
    assert review.status == CeoReviewStatus.DRAFT
    assert review.created_at == "2026-03-01T10:00:00"


def test_ceo_review_from_row_published_status():
    row = _make_ceo_review_row(status="published", approval_item_id=None)
    review = CeoReview.from_row(row)

    assert review.status == CeoReviewStatus.PUBLISHED
    assert review.approval_item_id is None


def test_ceo_review_from_row_empty_review_json():
    """When review_json is empty/None, from_row returns an empty dict."""
    row = _make_ceo_review_row(review_json="")
    review = CeoReview.from_row(row)

    assert review.review_json == {}


def test_ceo_review_from_row_complex_review_json():
    payload = {"health": "amber", "escalations": ["Budget overrun"], "milestones": []}
    row = _make_ceo_review_row(review_json=json.dumps(payload))
    review = CeoReview.from_row(row)

    assert review.review_json == payload
    assert review.review_json["escalations"] == ["Budget overrun"]
