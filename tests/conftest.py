"""Shared test fixtures — factory helpers, sample data loaders, temp DB, and test client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from src.config import AtlassianSettings, LLMSettings, Settings
from src.database import init_db

_SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


# ---------------------------------------------------------------------------
# Factory fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def make_response():
    """Factory fixture: build fake ``httpx.Response`` objects for mocking."""

    def _make(
        status_code: int = 200,
        json_data: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        content = json.dumps(json_data or {}).encode()
        return httpx.Response(
            status_code=status_code,
            content=content,
            headers=headers or {},
            request=httpx.Request("GET", "https://fake.atlassian.net"),
        )

    return _make


@pytest.fixture()
def make_jira_issue_response():
    """Factory fixture: build Jira issue API response dicts."""

    def _make(
        key: str = "PROG-100",
        summary: str = "Test Project",
        status: str = "In Progress",
        issue_type: str = "Goal",
        project_key: str = "PROG",
        labels: list[str] | None = None,
        fix_versions: list[str] | None = None,
        due_date: str | None = None,
        parent_key: str | None = None,
        description: dict | None = None,
    ) -> dict:
        parent = {"key": parent_key} if parent_key else None
        versions = [{"name": v} for v in (fix_versions or [])]
        return {
            "id": "10000",
            "key": key,
            "fields": {
                "summary": summary,
                "status": {"name": status},
                "issuetype": {"name": issue_type},
                "project": {"key": project_key},
                "labels": labels or [],
                "fixVersions": versions,
                "duedate": due_date,
                "parent": parent,
                "description": description,
            },
        }

    return _make


@pytest.fixture()
def make_project():
    """Factory fixture: build Project dataclass instances."""
    from src.models.project import Project

    def _make(
        id: int = 1,
        jira_goal_key: str = "PROG-100",
        name: str = "Test Project",
        confluence_charter_id: str | None = None,
        confluence_xft_id: str | None = None,
        status: str = "active",
        phase: str = "planning",
        created_at: str = "2026-01-01T00:00:00",
        dhf_draft_root_id: str | None = None,
        dhf_released_root_id: str | None = None,
        default_component: str | None = None,
        default_label: str | None = None,
        **overrides,
    ) -> Project:
        kwargs = dict(
            id=id,
            jira_goal_key=jira_goal_key,
            name=name,
            confluence_charter_id=confluence_charter_id,
            confluence_xft_id=confluence_xft_id,
            status=status,
            phase=phase,
            created_at=created_at,
            dhf_draft_root_id=dhf_draft_root_id,
            dhf_released_root_id=dhf_released_root_id,
            default_component=default_component,
            default_label=default_label,
        )
        kwargs.update(overrides)
        return Project(**kwargs)

    return _make


@pytest.fixture()
def make_jira_issue():
    """Factory fixture: build JiraIssue dataclass instances."""
    from src.models.jira import JiraIssue

    def _make(
        id: str = "10000",
        key: str = "PROG-100",
        summary: str = "Test Project",
        status: str = "In Progress",
        issue_type: str = "Goal",
        project_key: str = "PROG",
        labels: list[str] | None = None,
        parent_key: str | None = None,
        fix_versions: list[str] | None = None,
        due_date: str | None = "2026-06-01",
        description_adf: dict | None = None,
        **overrides,
    ) -> JiraIssue:
        kwargs = dict(
            id=id,
            key=key,
            summary=summary,
            status=status,
            issue_type=issue_type,
            project_key=project_key,
            labels=labels or [],
            parent_key=parent_key,
            fix_versions=fix_versions or [],
            due_date=due_date,
            description_adf=description_adf,
        )
        kwargs.update(overrides)
        return JiraIssue(**kwargs)

    return _make


@pytest.fixture()
def make_spinup_request():
    """Factory fixture: build SpinUpRequest dataclass instances."""
    from src.models.project import SpinUpRequest

    def _make(
        project_name: str = "HOP Drop 4",
        program: str = "HOP",
        team_projects: list[str] | None = None,
        target_date: str = "2026-09-01",
        labels: list[str] | None = None,
        goal_summary: str = "Fourth HOP drop",
        confluence_space_key: str = "HPP",
        **overrides,
    ) -> SpinUpRequest:
        kwargs = dict(
            project_name=project_name,
            program=program,
            team_projects=team_projects if team_projects is not None else ["AIM", "CTCV"],
            target_date=target_date,
            labels=labels or ["release-4"],
            goal_summary=goal_summary,
            confluence_space_key=confluence_space_key,
        )
        kwargs.update(overrides)
        return SpinUpRequest(**kwargs)

    return _make


@pytest.fixture()
def make_raw_dhf_doc():
    """Factory fixture: build raw DHF document dicts (pre-matching)."""

    def _make(
        page_id: str = "1",
        title: str = "Doc",
        area: str = "Area",
        version: str | None = "1",
        document_id: str | None = "doc-abc",
        last_modified: str = "2026-01-01T00:00:00Z",
        author: str = "Jane",
        page_url: str = "https://example.atlassian.net/wiki/page/1",
        **overrides,
    ) -> dict:
        doc = {
            "page_id": page_id,
            "title": title,
            "area": area,
            "version": version,
            "document_id": document_id,
            "last_modified": last_modified,
            "author": author,
            "page_url": page_url,
        }
        doc.update(overrides)
        return doc

    return _make


@pytest.fixture()
def make_release():
    """Factory fixture: build Release dataclass instances."""
    from src.models.release import Release

    def _make(
        id: int = 1,
        project_id: int = 1,
        name: str = "v1.0",
        locked: bool = False,
        created_at: str = "2026-01-01T00:00:00",
        version_snapshot: dict | None = None,
        **overrides,
    ) -> Release:
        kwargs = dict(
            id=id,
            project_id=project_id,
            name=name,
            locked=locked,
            created_at=created_at,
            version_snapshot=version_snapshot,
        )
        kwargs.update(overrides)
        return Release(**kwargs)

    return _make


# ---------------------------------------------------------------------------
# Sample data fixtures — load once per session
# ---------------------------------------------------------------------------


def _load_json(relpath: str) -> Any:
    with open(_SAMPLES_DIR / relpath) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def sample_field_map() -> dict[str, str]:
    return _load_json("jira/field-name-to-id.json")


@pytest.fixture(scope="session")
def sample_jira_goal() -> dict[str, Any]:
    return _load_json("jira/prog-256.json")


@pytest.fixture(scope="session")
def sample_jira_initiative() -> dict[str, Any]:
    return _load_json("jira/aim-3295.json")


@pytest.fixture(scope="session")
def sample_jira_risk() -> dict[str, Any]:
    return _load_json("jira/risk-145.json")


@pytest.fixture(scope="session")
def sample_prog_issue_types() -> dict[str, Any]:
    return _load_json("jira/prog-issue-types.json")


@pytest.fixture(scope="session")
def sample_risk_issue_types() -> dict[str, Any]:
    return _load_json("jira/risk-issue-types.json")


@pytest.fixture(scope="session")
def sample_risk_versions() -> list[dict[str, Any]]:
    return _load_json("jira/risk-versions.json")


@pytest.fixture(scope="session")
def sample_charter_template() -> dict[str, Any]:
    return _load_json("confluence/charter-template.json")


@pytest.fixture(scope="session")
def sample_xft_template() -> dict[str, Any]:
    return _load_json("confluence/xft-template.json")


# ---------------------------------------------------------------------------
# Settings fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def test_settings(sample_field_map: dict[str, str]) -> Settings:
    return Settings(
        atlassian=AtlassianSettings(
            domain="test-company",
            email="test@example.com",
            api_token="fake-token",
        ),
        llm=LLMSettings(),
        db_path=":memory:",
        jira_field_map=sample_field_map,
    )


# ---------------------------------------------------------------------------
# Temp database fixture (file-based, not :memory:)
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# TestClient fixture — patches settings.db_path
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_db: str):
    from starlette.testclient import TestClient

    from src.main import app

    with patch("src.config.settings", Settings(
        atlassian=AtlassianSettings(
            domain="test-company",
            email="test@example.com",
            api_token="fake-token",
        ),
        llm=LLMSettings(),
        db_path=tmp_db,
    )):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
