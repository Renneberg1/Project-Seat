"""LLM prompt templates and schema definitions."""

from typing import Any

# ------------------------------------------------------------------
# Shared context_requests schema fragment
# ------------------------------------------------------------------

CONTEXT_REQUESTS_FIELD: dict[str, Any] = {
    "type": "array",
    "description": (
        "Requests for additional context that would improve the analysis. "
        "Empty array if no additional context is needed."
    ),
    "items": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": [
                    "jira_issue",
                    "jira_search",
                    "confluence_search",
                    "confluence_text_search",
                ],
                "description": (
                    "Type of lookup: "
                    "jira_issue (fetch a specific ticket by key), "
                    "jira_search (text search across Jira), "
                    "confluence_search (search Confluence pages by TITLE — use when you "
                    "know the page's approximate name), "
                    "confluence_text_search (full-text search across page titles AND "
                    "body content — use to discover pages when you don't know the title, "
                    "e.g. 'team retrospective', 'stakeholder list', 'vendor status')"
                ),
            },
            "query": {
                "type": "string",
                "description": (
                    "The Jira issue key (e.g. RISK-200) for jira_issue, "
                    "or search text for jira_search / confluence_search / "
                    "confluence_text_search"
                ),
            },
            "reason": {
                "type": "string",
                "description": "Why this additional context would improve the analysis",
            },
        },
        "required": ["type", "query", "reason"],
    },
}

CONTEXT_REQUESTS_RULE = (
    "If the provided data references specific Jira tickets, Confluence pages, or documents "
    "that you do not have details for — OR if relevant supporting material (architecture "
    "docs, retrospectives, stakeholder lists, vendor status, regulatory plans, escalation "
    "logs, etc.) likely exists in Confluence or Jira but is not in the provided context — "
    "add a context_request. Use confluence_search for known page titles, "
    "confluence_text_search for topic/content discovery, jira_issue for a specific ticket "
    "key, and jira_search for text search across tickets. Only request information that is "
    "genuinely needed; each request should say what to look up and why."
)


def add_context_requests(schema: dict[str, Any]) -> dict[str, Any]:
    """Add the context_requests field to a JSON schema and make it required.

    Returns the modified schema (also mutates in-place).
    """
    schema["properties"]["context_requests"] = CONTEXT_REQUESTS_FIELD
    required = schema.get("required", [])
    if "context_requests" not in required:
        required.append("context_requests")
    schema["required"] = required
    return schema
