"""Transcript analysis prompt templates and schema definitions."""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """\
You are a project management analyst for a medical device software engineering team. \
Your job is to analyze meeting transcripts and extract actionable items.

You work in a regulated medical device environment where:
- **Risks** are tracked in Jira (RISK project, Risk issue type). A risk is anything that \
could impact the project timeline, quality, regulatory compliance, or patient safety.
- **Decisions** are tracked in Jira (RISK project, Project Issue type). A decision is any \
significant choice made by the team that should be documented for traceability.
- **XFT updates** are meeting notes that should be appended to the project's \
Cross-Functional Team (XFT) Confluence page.
- **Charter updates** are changes to project scope, timeline, or objectives that should \
update the project Charter page.

CRITICAL RULES:
1. Do NOT create duplicate suggestions — check the existing risks and decisions provided \
in the context. If a risk/decision already exists, skip it.
2. Every suggestion MUST have direct evidence from the transcript (a quote or paraphrase).
3. Assign confidence 0.0-1.0 based on how clearly the transcript supports the suggestion.
4. For risks: include impact analysis and mitigation/control steps.
5. For decisions: include the decision context, the actual decision made, and any follow-up actions.
6. Always generate an xft_update suggestion with meeting notes if there's substantive discussion.
7. Only suggest charter_update if there are clear scope/timeline/objective changes discussed.
8. Keep titles concise (under 80 characters) — they become Jira summaries.
9. For xft_update and charter_update suggestions: the confluence_content text will be \
published directly to a Confluence page visible to the entire project team and stakeholders. \
Write with clarity, professional tone, and good structure. Use separate paragraphs \
(separated by newlines) for distinct points. Avoid casual language, abbreviations, or \
incomplete sentences. Content should read as polished documentation, not rough meeting notes.
10. If a speaker's full name can be determined from the transcript, reference them with \
@FirstName LastName syntax in evidence, background, and confluence_content fields.
11. Respond with valid JSON only — no markdown, no explanation.
12. **Action items**: tasks explicitly assigned to people during the meeting. Include \
who is responsible (owner_name) and any mentioned deadline (due_date_hint).
13. **Notes**: important observations, status updates, factual statements worth preserving.
14. **Insights**: analytical observations, lessons learned, strategic points.
15. Prioritize: risks and decisions first (regulatory), then action items, then notes/insights.
"""

# JSON schema for structured LLM output
TRANSCRIPT_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "meeting_summary": {
            "type": "string",
            "description": "2-3 sentence summary of the meeting",
        },
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["risk", "decision", "xft_update", "charter_update", "action_item", "note", "insight"],
                    },
                    "title": {
                        "type": "string",
                        "description": "Short summary title (becomes Jira summary for risk/decision)",
                    },
                    "background": {
                        "type": "string",
                        "description": "Context/background for description field",
                    },
                    "impact_analysis": {
                        "type": "string",
                        "description": "Impact analysis text (for risks/decisions)",
                    },
                    "mitigation": {
                        "type": "string",
                        "description": "Mitigation/control steps (for risks/decisions)",
                    },
                    "evidence": {
                        "type": "string",
                        "description": "Direct quote or close paraphrase from transcript",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["High", "Medium", "Low"],
                    },
                    "timeline_impact_days": {
                        "type": "number",
                        "description": "Estimated days of timeline impact (0 if unknown)",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "0.0-1.0 confidence score",
                    },
                    "confluence_section_title": {
                        "type": "string",
                        "description": "For xft/charter: section heading. Empty string if not applicable.",
                    },
                    "confluence_content": {
                        "type": "string",
                        "description": "For xft/charter: content to publish on the Confluence page. Write clearly and professionally — this will be published as-is to a document visible to the project team. Use separate paragraphs (newlines) for distinct points. Empty string if not applicable.",
                    },
                    "owner_name": {
                        "type": "string",
                        "description": "For action_item: person responsible. Empty string if unknown or not applicable.",
                    },
                    "due_date_hint": {
                        "type": "string",
                        "description": "For action_item: mentioned deadline (YYYY-MM-DD if possible). Empty string if none mentioned or not applicable.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "For note/insight: relevant topic tags. Empty array if not applicable.",
                    },
                },
                "required": [
                    "type", "title", "background", "impact_analysis",
                    "mitigation", "evidence", "priority",
                    "timeline_impact_days", "confidence",
                    "confluence_section_title", "confluence_content",
                    "owner_name", "due_date_hint", "tags",
                ],
            },
        },
    },
    "required": ["meeting_summary", "suggestions"],
}


def build_user_prompt(transcript_text: str, project_context: dict[str, Any]) -> str:
    """Assemble the user prompt with transcript + project context.

    Args:
        transcript_text: Raw transcript text (speaker: text lines).
        project_context: Dict with project_name, jira_goal_key,
            existing_risks, existing_decisions, charter_content, xft_content.
    """
    parts: list[str] = []

    # Project context
    parts.append(f"## Project: {project_context.get('project_name', 'Unknown')}")
    parts.append(f"Jira Goal: {project_context.get('jira_goal_key', 'Unknown')}")
    parts.append("")

    # Existing risks
    risks = project_context.get("existing_risks", [])
    if risks:
        parts.append("## Existing Risks (do NOT duplicate)")
        for r in risks:
            parts.append(f"- [{r.get('key', '?')}] {r.get('summary', '')} ({r.get('status', '')})")
        parts.append("")
    else:
        parts.append("## Existing Risks: None")
        parts.append("")

    # Existing decisions
    decisions = project_context.get("existing_decisions", [])
    if decisions:
        parts.append("## Existing Decisions (do NOT duplicate)")
        for d in decisions:
            parts.append(f"- [{d.get('key', '?')}] {d.get('summary', '')} ({d.get('status', '')})")
        parts.append("")
    else:
        parts.append("## Existing Decisions: None")
        parts.append("")

    # Charter content (last 3000 chars)
    charter = project_context.get("charter_content")
    if charter:
        truncated = charter[-3000:] if len(charter) > 3000 else charter
        parts.append("## Current Charter Page (excerpt)")
        parts.append(truncated)
        parts.append("")

    # XFT content (last 3000 chars)
    xft = project_context.get("xft_content")
    if xft:
        truncated = xft[-3000:] if len(xft) > 3000 else xft
        parts.append("## Current XFT Page (excerpt)")
        parts.append(truncated)
        parts.append("")

    # Transcript (truncate to ~20K chars keeping start/end + speaker changes)
    parts.append("## Meeting Transcript")
    parts.append("---")
    if len(transcript_text) > 20000:
        # Keep first 10K, last 5K, and note the truncation
        parts.append(transcript_text[:10000])
        parts.append("\n... [TRANSCRIPT TRUNCATED — middle section omitted] ...\n")
        parts.append(transcript_text[-5000:])
    else:
        parts.append(transcript_text)
    parts.append("---")

    parts.append("")
    parts.append(
        "Analyze this transcript and return a JSON object with meeting_summary "
        "and suggestions array. Follow all rules in the system prompt."
    )

    return "\n".join(parts)


# ------------------------------------------------------------------
# ADF helpers — convert plain text to Jira Atlassian Document Format
# ------------------------------------------------------------------

def build_adf_field(text: str) -> dict[str, Any]:
    """Wrap plain text in an ADF document structure (single paragraph)."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def build_adf_description(background: str, evidence: str) -> dict[str, Any]:
    """Build a structured ADF description with Background + Evidence sections."""
    content: list[dict[str, Any]] = [
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Background", "marks": [{"type": "strong"}]}
            ],
        },
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": background}],
        },
        {"type": "rule"},
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "Evidence from transcript",
                    "marks": [{"type": "strong"}],
                }
            ],
        },
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": evidence}],
        },
    ]

    return {"type": "doc", "version": 1, "content": content}


def build_adf_decision_description(
    background: str, decision_text: str, evidence: str
) -> dict[str, Any]:
    """Build ADF description for a decision with Background + Decision + Evidence."""
    content: list[dict[str, Any]] = [
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Background", "marks": [{"type": "strong"}]}
            ],
        },
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": background}],
        },
        {"type": "rule"},
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Decision", "marks": [{"type": "strong"}]}
            ],
        },
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": decision_text}],
        },
        {"type": "rule"},
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "Evidence from transcript",
                    "marks": [{"type": "strong"}],
                }
            ],
        },
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": evidence}],
        },
    ]

    return {"type": "doc", "version": 1, "content": content}
