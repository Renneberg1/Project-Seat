"""Shared test fixtures — sample data loaders, temp DB, and test client."""

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
# Helper: build a fake httpx.Response for mocking
# ---------------------------------------------------------------------------

def make_response(
    status_code: int = 200,
    json_data: Any = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Build a fake ``httpx.Response`` suitable for mock return values."""
    content = json.dumps(json_data or {}).encode()
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers=headers or {},
        request=httpx.Request("GET", "https://fake.atlassian.net"),
    )


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
