"""Transcript analysis prompt templates and schema definitions."""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """\
<role>You are a project management analyst for a medical device software engineering team. \
Your job is to analyze meeting transcripts and extract actionable items.</role>

<context>You work in a regulated medical device environment where:
- Risks are tracked in Jira (RISK project, Risk issue type). A risk is anything that \
could impact the project timeline, quality, regulatory compliance, or patient safety.
- Decisions are tracked in Jira (RISK project, Project Issue type). A decision is any \
significant choice made by the team that should be documented for traceability.
- XFT updates are meeting notes that should be appended to the project's \
Cross-Functional Team (XFT) Confluence page.
- Charter updates are changes to project scope, timeline, or objectives that should \
update the project Charter page.</context>

<rules>
1. Do NOT create duplicate suggestions. Carefully compare every potential risk or decision \
against the existing items provided in context — match by MEANING, not just title. Two items \
about the same underlying issue are duplicates even if worded differently. \
If the transcript discusses an existing risk/decision and adds new information (updated impact, \
new mitigation steps, status change, additional context), use type "update_existing" instead \
of creating a new item. Set existing_key to the Jira key of the matched item.
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
11. Action items: tasks explicitly assigned to people during the meeting. Include \
who is responsible (owner_name) and any mentioned deadline (due_date_hint).
12. Notes: important observations, status updates, factual statements worth preserving.
13. Insights: analytical observations, lessons learned, strategic points.
14. Prioritize: risks and decisions first (regulatory), then action items, then notes/insights.
15. If the transcript references specific Jira tickets, Confluence pages, documents, or \
technical details that you do not have in the provided context, add them to context_requests. \
Each request should specify what to look up and why it would improve your analysis. \
Only request information that is genuinely needed — do not request speculatively.
</rules>
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
                        "enum": ["risk", "decision", "update_existing", "xft_update", "charter_update", "action_item", "note", "insight"],
                        "description": "Use 'update_existing' when the transcript discusses a risk/decision that already exists in the system and provides new information to add to it.",
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
                    "existing_key": {
                        "type": "string",
                        "description": "For update_existing: the Jira key of the existing risk/decision being updated (e.g. 'RISK-174'). Empty string for all other types.",
                    },
                },
                "required": [
                    "type", "title", "background", "impact_analysis",
                    "mitigation", "evidence", "priority",
                    "timeline_impact_days", "confidence",
                    "confluence_section_title", "confluence_content",
                    "owner_name", "due_date_hint", "tags", "existing_key",
                ],
            },
        },
    },
    "required": ["meeting_summary", "suggestions"],
}

from src.engine.prompts import add_context_requests
add_context_requests(TRANSCRIPT_ANALYSIS_SCHEMA)


def build_user_prompt(transcript_text: str, project_context: dict[str, Any]) -> str:
    """Assemble the user prompt with transcript + project context.

    Args:
        transcript_text: Raw transcript text (speaker: text lines).
        project_context: Dict with project_name, jira_goal_key,
            existing_risks, existing_decisions, charter_content, xft_content.
    """
    parts: list[str] = []

    # Project context
    parts.append(f"<project_context>")
    parts.append(f"Project: {project_context.get('project_name', 'Unknown')}")
    parts.append(f"Jira Goal: {project_context.get('jira_goal_key', 'Unknown')}")
    parts.append("</project_context>")
    parts.append("")

    # Existing risks (with descriptions for semantic matching)
    risks = project_context.get("existing_risks", [])
    parts.append("<existing_risks>")
    if risks:
        for r in risks:
            parts.append(f"<risk key=\"{r.get('key', '?')}\" status=\"{r.get('status', '')}\">")
            parts.append(f"  Summary: {r.get('summary', '')}")
            if r.get("components"):
                parts.append(f"  Components: {r['components']}")
            if r.get("description"):
                parts.append(f"  Description: {r['description']}")
            if r.get("impact_analysis"):
                parts.append(f"  Impact: {r['impact_analysis']}")
            if r.get("mitigation"):
                parts.append(f"  Mitigation: {r['mitigation']}")
            parts.append("</risk>")
    else:
        parts.append("None")
    parts.append("</existing_risks>")
    parts.append("")

    # Existing decisions (with descriptions for semantic matching)
    decisions = project_context.get("existing_decisions", [])
    parts.append("<existing_decisions>")
    if decisions:
        for d in decisions:
            parts.append(f"<decision key=\"{d.get('key', '?')}\" status=\"{d.get('status', '')}\">")
            parts.append(f"  Summary: {d.get('summary', '')}")
            if d.get("components"):
                parts.append(f"  Components: {d['components']}")
            if d.get("description"):
                parts.append(f"  Description: {d['description']}")
            parts.append("</decision>")
    else:
        parts.append("None")
    parts.append("</existing_decisions>")
    parts.append("")

    # Charter content (last 3000 chars)
    charter = project_context.get("charter_content")
    if charter:
        truncated = charter[-3000:] if len(charter) > 3000 else charter
        parts.append("<charter_content>")
        parts.append(truncated)
        parts.append("</charter_content>")
        parts.append("")

    # XFT content (last 3000 chars)
    xft = project_context.get("xft_content")
    if xft:
        truncated = xft[-3000:] if len(xft) > 3000 else xft
        parts.append("<xft_content>")
        parts.append(truncated)
        parts.append("</xft_content>")
        parts.append("")

    # Open action items (for continuity)
    action_items = project_context.get("open_action_items", [])
    if action_items:
        parts.append("<open_action_items>")
        for a in action_items:
            owner = a.get("owner", "unassigned")
            parts.append(f"- {a.get('title', '?')} (owner: {owner}, status: {a.get('status', '?')})")
        parts.append("</open_action_items>")
        parts.append("")

    # Knowledge entries (notes/insights from prior meetings)
    knowledge = project_context.get("knowledge_entries", [])
    if knowledge:
        parts.append("<prior_knowledge>")
        for k in knowledge:
            tags = f" [{k.get('tags', '')}]" if k.get("tags") else ""
            parts.append(f"- [{k.get('type', '?')}] {k.get('title', '?')}{tags}")
        parts.append("</prior_knowledge>")
        parts.append("")

    # Transcript (truncate to ~20K chars keeping start/end + speaker changes)
    parts.append("<transcript>")
    if len(transcript_text) > 20000:
        # Keep first 10K, last 5K, and note the truncation
        parts.append(transcript_text[:10000])
        parts.append("\n... [TRANSCRIPT TRUNCATED — middle section omitted] ...\n")
        parts.append(transcript_text[-5000:])
    else:
        parts.append(transcript_text)
    parts.append("</transcript>")

    parts.append("")
    parts.append(
        "<instructions>Analyze this transcript and extract all actionable items. "
        "Do not duplicate existing risks or decisions listed above. "
        "Follow all rules in the system prompt.</instructions>"
    )

    return "\n".join(parts)


# ------------------------------------------------------------------
# Refinement system prompt (second pass with additional context)
# ------------------------------------------------------------------

REFINEMENT_SYSTEM_PROMPT = """\
<role>You are a project management analyst for a medical device software engineering team. \
You previously analyzed a meeting transcript and requested additional context. \
That context has now been fetched. Your job is to refine your analysis.</role>

<rules>
1. Review the additional context provided and update your suggestions accordingly.
2. You may add, modify, or remove suggestions based on the new information.
3. Additional context may reveal that a risk you identified already exists — remove duplicates.
4. Additional context may add detail to your impact analysis or mitigation steps — enrich them.
5. All other rules from the original analysis still apply.
6. Return an empty context_requests array — no further lookups are needed.
</rules>
"""


def build_refinement_prompt(
    original_prompt: str,
    first_pass_result: dict[str, Any],
    fetched_context: list[dict[str, str]],
) -> str:
    """Build the second-pass prompt with the original analysis + fetched context.

    Args:
        original_prompt: The full user prompt from the first pass.
        first_pass_result: The parsed JSON result from the first pass.
        fetched_context: List of {type, query, result} dicts with fetched data.
    """
    parts: list[str] = []

    parts.append("<original_analysis>")
    parts.append(original_prompt)
    parts.append("</original_analysis>")
    parts.append("")

    parts.append("<first_pass_summary>")
    parts.append(f"Meeting summary: {first_pass_result.get('meeting_summary', '')}")
    parts.append(f"Suggestions: {len(first_pass_result.get('suggestions', []))}")
    for s in first_pass_result.get("suggestions", []):
        parts.append(f"- [{s.get('type', '?')}] {s.get('title', '?')} (confidence: {s.get('confidence', 0)})")
    parts.append("</first_pass_summary>")
    parts.append("")

    parts.append("<additional_context>")
    for item in fetched_context:
        parts.append(f"<lookup type=\"{item.get('type', '?')}\" query=\"{item.get('query', '?')}\">")
        parts.append(item.get("result", "No results found."))
        parts.append("</lookup>")
    parts.append("</additional_context>")
    parts.append("")

    parts.append(
        "<instructions>Refine your analysis using the additional context above. "
        "Update suggestions where the new information changes your assessment. "
        "Return the complete refined result with all suggestions.</instructions>"
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
