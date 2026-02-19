"""Application settings loaded from environment variables."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Path to the field-name-to-id mapping shipped in the repo
_FIELD_MAP_PATH = Path(__file__).resolve().parent.parent / "samples" / "jira" / "field-name-to-id.json"


def _load_field_map() -> dict[str, str]:
    """Load the Jira field-name -> custom-field-id mapping from the sample file."""
    if _FIELD_MAP_PATH.exists():
        with open(_FIELD_MAP_PATH) as f:
            return json.load(f)
    return {}


@dataclass(frozen=True)
class AtlassianSettings:
    domain: str = os.getenv("ATLASSIAN_DOMAIN", "")
    email: str = os.getenv("ATLASSIAN_EMAIL", "")
    api_token: str = os.getenv("ATLASSIAN_API_TOKEN", "")

    @property
    def jira_base_url(self) -> str:
        return f"https://{self.domain}.atlassian.net/rest/api/3"

    @property
    def confluence_base_url(self) -> str:
        return f"https://{self.domain}.atlassian.net/wiki/rest/api"


@dataclass(frozen=True)
class LLMSettings:
    provider: str = os.getenv("LLM_PROVIDER", "gemini")
    api_key: str = os.getenv("LLM_API_KEY", "")
    model: str = os.getenv("LLM_MODEL", "gemini-2.5-flash")
    base_url: str = os.getenv("LLM_BASE_URL", "http://localhost:11434")


@dataclass(frozen=True)
class EQMSSettings:
    draft_space_id: str = os.getenv("EQMS_DRAFT_SPACE_ID", "")
    released_space_id: str = os.getenv("EQMS_RELEASED_SPACE_ID", "")


@dataclass(frozen=True)
class Settings:
    atlassian: AtlassianSettings = field(default_factory=AtlassianSettings)
    llm: LLMSettings = field(default_factory=LLMSettings)
    eqms: EQMSSettings = field(default_factory=EQMSSettings)
    db_path: str = os.getenv("DB_PATH", "seat.db")
    jira_field_map: dict[str, str] = field(default_factory=_load_field_map)

    def field_id(self, name: str) -> str:
        """Resolve a human-readable Jira field name to its custom field ID.

        Returns the original name unchanged if no mapping exists.
        """
        return self.jira_field_map.get(name, name)


# Singleton used throughout the application
settings = Settings()
