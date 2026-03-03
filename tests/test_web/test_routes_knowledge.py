"""Tests for knowledge base routes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import Settings, AtlassianSettings, LLMSettings
from src.database import init_db, get_db


@pytest.fixture()
def knowledge_db(tmp_path: Path) -> str:
    path = str(tmp_path / "knowledge_web_test.db")
    init_db(path)
    return path


def _seed_project(db_path: str) -> int:
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase) VALUES (?, ?, ?, ?)",
            ("PROG-1", "Test Project", "active", "planning"),
        )
        conn.commit()
        return cursor.lastrowid


@pytest.fixture()
def client_with_knowledge(knowledge_db: str):
    from starlette.testclient import TestClient
    from src.main import app

    pid = _seed_project(knowledge_db)

    settings = Settings(
        atlassian=AtlassianSettings(domain="test", email="test@test.com", api_token="fake"),
        llm=LLMSettings(),
        db_path=knowledge_db,
    )

    with patch("src.config.settings", settings):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c, pid


def test_knowledge_page_empty(client_with_knowledge) -> None:
    client, pid = client_with_knowledge
    resp = client.get(f"/project/{pid}/knowledge/")
    assert resp.status_code == 200
    assert "Knowledge Base" in resp.text


def test_add_action_item(client_with_knowledge) -> None:
    client, pid = client_with_knowledge
    resp = client.post(
        f"/project/{pid}/knowledge/action-items/add",
        data={"title": "Test Action", "owner": "Alice", "due_date": "2026-04-01"},
    )
    assert resp.status_code == 200
    assert "Test Action" in resp.text


def test_add_note(client_with_knowledge) -> None:
    client, pid = client_with_knowledge
    resp = client.post(
        f"/project/{pid}/knowledge/entries/add",
        data={"entry_type": "note", "title": "Test Note", "content": "Some content", "tags": "sprint,api"},
    )
    assert resp.status_code == 200
    assert "Test Note" in resp.text


def test_add_insight(client_with_knowledge) -> None:
    client, pid = client_with_knowledge
    resp = client.post(
        f"/project/{pid}/knowledge/entries/add",
        data={"entry_type": "insight", "title": "Key Insight", "content": "Integration risks", "tags": "risk"},
    )
    assert resp.status_code == 200
    assert "Key Insight" in resp.text


def test_search_knowledge(client_with_knowledge) -> None:
    client, pid = client_with_knowledge

    # Add some entries first
    client.post(
        f"/project/{pid}/knowledge/entries/add",
        data={"entry_type": "note", "title": "API Review", "content": "REST endpoints", "tags": ""},
    )

    resp = client.get(f"/project/{pid}/knowledge/search?q=API")
    assert resp.status_code == 200
    assert "API Review" in resp.text


def test_update_action_status(client_with_knowledge) -> None:
    client, pid = client_with_knowledge

    # Add action item
    client.post(
        f"/project/{pid}/knowledge/action-items/add",
        data={"title": "Status Test", "owner": "Bob"},
    )

    # Update status — need to know the ID (1 since it's the first)
    resp = client.post(
        f"/project/{pid}/knowledge/action-items/1/status",
        data={"status": "done"},
    )
    assert resp.status_code == 200


def test_knowledge_page_not_found(client_with_knowledge) -> None:
    client, _ = client_with_knowledge
    resp = client.get("/project/9999/knowledge/")
    assert resp.status_code == 404
