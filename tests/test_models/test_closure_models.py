"""Tests for Closure Report domain models."""

from __future__ import annotations

import json

from src.models.closure import ClosureReport, ClosureReportStatus


# ---------------------------------------------------------------------------
# ClosureReportStatus enum
# ---------------------------------------------------------------------------


def test_closure_report_status_values():
    assert ClosureReportStatus.DRAFT.value == "draft"
    assert ClosureReportStatus.QUEUED.value == "queued"
    assert ClosureReportStatus.PUBLISHED.value == "published"
    assert ClosureReportStatus.REJECTED.value == "rejected"


def test_closure_report_status_is_str_enum():
    """ClosureReportStatus members are also plain strings."""
    assert isinstance(ClosureReportStatus.DRAFT, str)
    assert ClosureReportStatus.REJECTED == "rejected"


def test_closure_report_status_all_members():
    members = {s.value for s in ClosureReportStatus}
    assert members == {"draft", "queued", "published", "rejected"}


# ---------------------------------------------------------------------------
# ClosureReport.from_row
# ---------------------------------------------------------------------------


def _make_closure_row(
    *,
    id: int = 1,
    project_id: int = 42,
    report_json: str = '{"outcome": "success"}',
    confluence_body: str = "<h2>Closure</h2><p>Done</p>",
    approval_item_id: int | None = 5,
    status: str = "draft",
    created_at: str = "2026-03-01T14:00:00",
) -> dict:
    return {
        "id": id,
        "project_id": project_id,
        "report_json": report_json,
        "confluence_body": confluence_body,
        "approval_item_id": approval_item_id,
        "status": status,
        "created_at": created_at,
    }


def test_closure_report_from_row_all_fields():
    row = _make_closure_row()
    report = ClosureReport.from_row(row)

    assert report.id == 1
    assert report.project_id == 42
    assert report.report_json == {"outcome": "success"}
    assert report.confluence_body == "<h2>Closure</h2><p>Done</p>"
    assert report.approval_item_id == 5
    assert report.status == ClosureReportStatus.DRAFT
    assert report.created_at == "2026-03-01T14:00:00"


def test_closure_report_from_row_published_status():
    row = _make_closure_row(status="published", approval_item_id=None)
    report = ClosureReport.from_row(row)

    assert report.status == ClosureReportStatus.PUBLISHED
    assert report.approval_item_id is None


def test_closure_report_from_row_empty_report_json():
    """When report_json is empty/None, from_row returns an empty dict."""
    row = _make_closure_row(report_json="")
    report = ClosureReport.from_row(row)

    assert report.report_json == {}


def test_closure_report_from_row_complex_report_json():
    payload = {
        "outcome": "partial",
        "lessons_learned": ["Start testing earlier"],
        "success_criteria": {"on_time": False, "on_budget": True},
    }
    row = _make_closure_row(report_json=json.dumps(payload))
    report = ClosureReport.from_row(row)

    assert report.report_json == payload
    assert report.report_json["lessons_learned"] == ["Start testing earlier"]


def test_closure_report_from_row_rejected_status():
    row = _make_closure_row(status="rejected")
    report = ClosureReport.from_row(row)

    assert report.status == ClosureReportStatus.REJECTED
