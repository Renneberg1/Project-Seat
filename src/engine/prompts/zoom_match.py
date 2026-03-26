"""Zoom meeting-to-project classification prompt and schema."""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """\
<role>You classify Zoom meetings into medical device software engineering projects.</role>

<context>You will receive a meeting topic, host email, a short transcript excerpt, and a list of \
active projects with their names, team project keys, and aliases.</context>

<rules>
1. Return a confidence score 0.0-1.0 for each potential match.
2. Only include matches where you have clear evidence the meeting is about that project.
3. A meeting can match multiple projects (e.g., cross-project sync).
4. General meetings (all-hands, socials, 1:1s unrelated to a project) should return empty matches.
5. Look for project names, team keys (AIM, CTCV, YAM, etc.), product names, or specific \
feature/initiative references that link to a project.
6. Version numbers, drop numbers, and release numbers matter: "Drop 3" is NOT the same as \
"Drop 2", "Release 1.5" is NOT "Release 1.4". If the meeting references a specific version/drop \
that does not match any active project, return empty matches — do NOT match to the closest version.
</rules>
"""

ZOOM_MATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "number",
                        "description": "The ID of the matched project",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "0.0-1.0 confidence that this meeting relates to this project",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Brief explanation of why this meeting matches this project",
                    },
                },
                "required": ["project_id", "confidence", "reasoning"],
            },
        },
    },
    "required": ["matches"],
}


def build_match_prompt(
    topic: str,
    host_email: str,
    transcript_excerpt: str,
    active_projects: list[dict[str, Any]],
) -> str:
    """Build the user prompt for meeting classification."""
    parts: list[str] = []

    parts.append("<meeting>")
    parts.append(f"Topic: {topic}")
    parts.append(f"Host: {host_email}")
    parts.append("</meeting>")
    parts.append("")

    parts.append("<active_projects>")
    for p in active_projects:
        line = f"- ID={p['id']}: {p['name']}"
        if p.get("team_keys"):
            line += f" (teams: {', '.join(p['team_keys'])})"
        if p.get("aliases"):
            line += f" (aliases: {', '.join(p['aliases'])})"
        parts.append(line)
    parts.append("</active_projects>")
    parts.append("")

    if transcript_excerpt:
        parts.append("<transcript_excerpt>")
        parts.append(transcript_excerpt[:2000])
        parts.append("</transcript_excerpt>")
        parts.append("")

    parts.append(
        "<instructions>Classify this meeting. Only include projects with confidence >= 0.7.</instructions>"
    )

    return "\n".join(parts)
