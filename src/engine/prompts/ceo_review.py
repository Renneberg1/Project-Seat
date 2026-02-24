"""CEO Review prompt templates and schema definitions.

Two-step LLM interaction:
1. **Questions**: LLM reviews project data (with 2-week focus) and asks the PM
   questions it cannot answer from the data alone.
2. **Review**: LLM produces a CEO-level status update with health indicator,
   commentary on decisions/risks/development/documentation, escalations, and
   next milestones.
"""

from __future__ import annotations

from typing import Any


# ------------------------------------------------------------------
# Step 1: Questions prompt
# ------------------------------------------------------------------

QUESTIONS_SYSTEM_PROMPT = """\
You are a senior project manager preparing a fortnightly CEO status update for \
a medical device software engineering project. You have been given project data \
from the last 2 weeks, including new risks, new decisions, development progress \
delta, documentation progress, and team blockers.

Your job is to identify what you CANNOT determine from the data alone — things \
like reasons for delays, context behind new risks, stakeholder feedback, \
external dependency changes, or qualitative team dynamics.

RULES:
1. Only ask questions about information genuinely absent from the provided data.
2. Each question must include a category (e.g. "Decisions", "Risks", \
"Development", "Documentation", "Stakeholders", "Timeline").
3. Explain briefly why the information is needed for an accurate CEO update.
4. Ask at most 6 questions — focus on the most impactful gaps.
5. If the data is comprehensive enough and PM notes cover the gaps, return an \
empty list.
6. Respond with valid JSON only — no markdown, no explanation.
"""

CEO_QUESTIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The clarifying question to ask the PM",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category: Decisions, Risks, Development, Documentation, Stakeholders, Timeline, or Other",
                    },
                    "why_needed": {
                        "type": "string",
                        "description": "Why this information is needed for an accurate CEO update",
                    },
                },
                "required": ["question", "category", "why_needed"],
            },
        },
    },
    "required": ["questions"],
}


def build_questions_prompt(
    metrics: dict[str, Any],
    pm_notes: str,
) -> str:
    """Build the user prompt for the questions step."""
    parts: list[str] = []

    parts.append(f"# CEO Status Update Data: {metrics.get('project_name', 'Unknown')}")
    parts.append(f"Phase: {metrics.get('phase', 'N/A')} | Due: {metrics.get('due_date', 'N/A')}")
    parts.append("")

    # New decisions (last 2 weeks)
    _append_new_decisions(parts, metrics)

    # New risks (last 2 weeks)
    _append_new_risks(parts, metrics)

    # Development progress
    _append_dev_progress(parts, metrics)

    # Documentation progress
    _append_doc_progress(parts, metrics)

    # Releases
    _append_releases(parts, metrics)

    # PM notes
    if pm_notes and pm_notes.strip():
        parts.append("## PM Notes")
        parts.append(pm_notes.strip())
        parts.append("")

    parts.append("---")
    parts.append(
        "Based on the data above, identify questions you cannot answer from the data "
        "alone. Return a JSON object with a 'questions' array. "
        'If the data is sufficient, return {"questions": []}.'
    )

    return "\n".join(parts)


# ------------------------------------------------------------------
# Step 2: Review prompt
# ------------------------------------------------------------------

REVIEW_SYSTEM_PROMPT = """\
You are a senior project manager producing a fortnightly CEO-level project \
status update for a medical device software engineering project. Focus on what \
changed in the last 2 weeks.

Metrics are pre-computed and accurate — reference them but do not alter numbers. \
Write concise, executive-level commentary. Be factual and evidence-based.

RULES:
1. health_indicator must be exactly "On Track", "At Risk", or "Off Track".
2. Each commentary field should be 2-4 sentences summarising the key points.
3. Escalations should only be raised for issues needing CEO/leadership attention.
4. Next milestones should be concrete, time-bound where possible.
5. Respond with valid JSON only — no markdown, no explanation.
"""

CEO_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "health_indicator": {
            "type": "string",
            "description": "Overall status: On Track, At Risk, or Off Track",
        },
        "decisions_commentary": {
            "type": "string",
            "description": "Summarise new decisions and their implications (2-4 sentences)",
        },
        "risks_commentary": {
            "type": "string",
            "description": "Summarise new risks, severity patterns, and mitigations (2-4 sentences)",
        },
        "development_commentary": {
            "type": "string",
            "description": "Summarise dev progress, velocity, blockers, achievements (2-4 sentences)",
        },
        "documentation_commentary": {
            "type": "string",
            "description": "Summarise doc progress, recently published/updated docs (2-4 sentences)",
        },
        "escalations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue": {
                        "type": "string",
                        "description": "The issue requiring escalation",
                    },
                    "impact": {
                        "type": "string",
                        "description": "Business or timeline impact",
                    },
                    "ask": {
                        "type": "string",
                        "description": "What is needed from leadership",
                    },
                },
                "required": ["issue", "impact", "ask"],
            },
        },
        "next_milestones": {
            "type": "array",
            "items": {
                "type": "string",
                "description": "A concrete upcoming milestone",
            },
        },
    },
    "required": [
        "health_indicator",
        "decisions_commentary",
        "risks_commentary",
        "development_commentary",
        "documentation_commentary",
        "escalations",
        "next_milestones",
    ],
}


def build_review_prompt(
    metrics: dict[str, Any],
    pm_notes: str,
    qa_pairs: list[dict[str, str]],
) -> str:
    """Build the user prompt for the review step."""
    parts: list[str] = []

    parts.append(f"# CEO Status Update Data: {metrics.get('project_name', 'Unknown')}")
    parts.append(f"Phase: {metrics.get('phase', 'N/A')} | Due: {metrics.get('due_date', 'N/A')}")
    parts.append("")

    _append_new_decisions(parts, metrics)
    _append_new_risks(parts, metrics)
    _append_dev_progress(parts, metrics)
    _append_doc_progress(parts, metrics)
    _append_releases(parts, metrics)

    if pm_notes and pm_notes.strip():
        parts.append("## PM Notes")
        parts.append(pm_notes.strip())
        parts.append("")

    if qa_pairs:
        parts.append("## PM's Answers to Clarifying Questions")
        for i, qa in enumerate(qa_pairs, 1):
            parts.append(f"**Q{i}:** {qa['question']}")
            parts.append(f"**A{i}:** {qa['answer']}")
            parts.append("")

    parts.append("---")
    parts.append(
        "Produce a CEO-level status update. Return a JSON object with "
        "health_indicator, decisions_commentary, risks_commentary, "
        "development_commentary, documentation_commentary, escalations, "
        "and next_milestones."
    )

    return "\n".join(parts)


# ------------------------------------------------------------------
# Prompt section builders
# ------------------------------------------------------------------


def _append_new_decisions(parts: list[str], metrics: dict[str, Any]) -> None:
    decisions = metrics.get("new_decisions", [])
    parts.append(f"## New Decisions (Last 2 Weeks): {len(decisions)}")
    if decisions:
        for d in decisions:
            parts.append(f"- [{d.get('key', '?')}] {d.get('summary', '?')} (status: {d.get('status', '?')})")
    else:
        parts.append("- No new decisions in this period.")
    parts.append("")


def _append_new_risks(parts: list[str], metrics: dict[str, Any]) -> None:
    new_risks = metrics.get("new_risks", [])
    total = metrics.get("total_risk_count", 0)
    open_count = metrics.get("open_risk_count", 0)
    parts.append(f"## New Risks (Last 2 Weeks): {len(new_risks)}")
    parts.append(f"Overall: {open_count} open / {total} total")
    if new_risks:
        for r in new_risks:
            components = r.get("components", "")
            comp_str = f" [{components}]" if components else ""
            parts.append(f"- [{r.get('key', '?')}] {r.get('summary', '?')} (status: {r.get('status', '?')}){comp_str}")
    else:
        parts.append("- No new risks in this period.")
    parts.append("")


def _append_dev_progress(parts: list[str], metrics: dict[str, Any]) -> None:
    parts.append("## Development Progress (Last 2 Weeks)")
    sp_burned = metrics.get("sp_burned_2w", 0)
    scope_change = metrics.get("scope_change_2w", 0)
    parts.append(f"- Story points burned: {sp_burned}")
    parts.append(f"- Scope change: {scope_change:+} SP")

    team_progress = metrics.get("team_progress", [])
    if team_progress:
        parts.append("### Per-Team Progress")
        for t in team_progress:
            blockers = f" | Blockers: {t['blockers']}" if t.get("blockers") else ""
            parts.append(
                f"- {t.get('team', '?')}: {t.get('pct_done', 0)}% "
                f"({t.get('sp_done', 0)}/{t.get('sp_total', 0)} SP){blockers}"
            )
    parts.append("")


def _append_doc_progress(parts: list[str], metrics: dict[str, Any]) -> None:
    parts.append("## Documentation Progress")
    dhf_total = metrics.get("dhf_total", 0)
    dhf_released = metrics.get("dhf_released", 0)
    dhf_pct = metrics.get("dhf_completion_pct", 0)
    parts.append(f"- DHF Completion: {dhf_released}/{dhf_total} ({dhf_pct:.0f}%)")

    recently_updated = metrics.get("dhf_recently_updated", [])
    if recently_updated:
        parts.append("### Recently Updated Documents (Last 2 Weeks)")
        for doc in recently_updated:
            parts.append(f"- {doc.get('title', '?')} ({doc.get('status', '?')}) — {doc.get('last_modified', '?')}")
    else:
        parts.append("- No documents updated in last 2 weeks.")
    parts.append("")


def _append_releases(parts: list[str], metrics: dict[str, Any]) -> None:
    releases = metrics.get("releases", [])
    if not releases:
        return
    parts.append(f"## Releases ({len(releases)})")
    for rel in releases:
        locked = "LOCKED" if rel.get("locked") else "unlocked"
        parts.append(f"- {rel.get('name', '?')} ({locked})")
    parts.append("")
