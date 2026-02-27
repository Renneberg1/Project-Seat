"""Closure Report prompt templates and schema definitions.

Two-step LLM interaction:
1. **Questions**: LLM reviews full project lifecycle data and asks the PM
   questions about lessons learned, delivery assessment, success criteria,
   and stakeholder satisfaction.
2. **Report**: LLM produces narrative sections (delivery outcome, success
   criteria assessments, lessons learned) while deterministic data tables
   (timeline, scope, risks, issues) are pre-computed.
"""

from __future__ import annotations

from typing import Any


# ------------------------------------------------------------------
# Step 1: Questions prompt
# ------------------------------------------------------------------

QUESTIONS_SYSTEM_PROMPT = """\
You are a senior project manager preparing a formal project closure report \
for a medical device software engineering project. You have been given the \
full project lifecycle data including risks, decisions, Charter scope, \
team progress, documentation status, and releases.

Your job is to identify what you CANNOT determine from the data alone — \
things like lessons learned, delivery assessment quality, success criteria \
outcomes, stakeholder satisfaction, vendor performance, reasons for \
timeline deviations, and team retrospective insights.

RULES:
1. Only ask questions about information genuinely absent from the provided data.
2. Each question must include a category (e.g. "Lessons Learned", "Delivery", \
"Success Criteria", "Stakeholders", "Timeline", "Team", "Vendor", "Testing").
3. Explain briefly why the information is needed for a complete closure report.
4. Ask at most 8 questions — focus on the most impactful gaps.
5. If the data is comprehensive enough and PM notes cover the gaps, return an \
empty list.
6. Respond with valid JSON only — no markdown, no explanation.
"""

CLOSURE_QUESTIONS_SCHEMA: dict[str, Any] = {
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
                        "description": "Category: Lessons Learned, Delivery, Success Criteria, Stakeholders, Timeline, Team, Vendor, Testing, or Other",
                    },
                    "why_needed": {
                        "type": "string",
                        "description": "Why this information is needed for a complete closure report",
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

    parts.append(f"# Project Closure Report Data: {metrics.get('project_name', 'Unknown')}")
    parts.append(f"Phase: {metrics.get('phase', 'N/A')} | PM: {metrics.get('pm', 'N/A')} | Sponsor: {metrics.get('sponsor', 'N/A')}")
    parts.append("")

    _append_timeline(parts, metrics)
    _append_scope(parts, metrics)
    _append_risks(parts, metrics)
    _append_decisions(parts, metrics)
    _append_dev_progress(parts, metrics)
    _append_doc_progress(parts, metrics)
    _append_releases(parts, metrics)

    if pm_notes and pm_notes.strip():
        parts.append("## PM Notes")
        parts.append(pm_notes.strip())
        parts.append("")

    parts.append("---")
    parts.append(
        "Based on the data above, identify questions you cannot answer from the data "
        "alone for a comprehensive project closure report. Return a JSON object with a "
        "'questions' array. Focus on lessons learned, success criteria, delivery "
        'assessment, and stakeholder satisfaction. If the data is sufficient, return {"questions": []}.'
    )

    return "\n".join(parts)


# ------------------------------------------------------------------
# Step 2: Report prompt
# ------------------------------------------------------------------

REPORT_SYSTEM_PROMPT = """\
You are a senior project manager producing a formal project closure report \
for a medical device software engineering project. The report will be \
published to Confluence as a permanent record.

Deterministic data tables (timeline, scope, risks, issues) are pre-computed \
and accurate — you must NOT invent or alter any numbers. Your job is to \
produce narrative sections only:
1. **final_delivery_outcome**: 3-5 sentences covering what was delivered vs planned.
2. **success_criteria_assessments**: For each success criterion, assess actual \
performance against expected outcomes.
3. **lessons_learned**: Categorised lessons with descriptions, triggers, \
recommendations, and suggested owners.

RULES:
1. final_delivery_outcome must be 3-5 sentences. Be factual, not promotional.
2. Each success criterion assessment must have: criterion, expected_outcome, \
measurement_method, actual_performance, status (exactly "Met", "Partially Met", \
or "Not Met"), and comments.
3. Lessons learned categories must be one of: Planning, Team, Technical, \
Implementation, Commercial, Testing, Change Management, Vendor, Documentation.
4. Each lesson must have description, effect_triggers, recommendations, and owner.
5. Include at least 3 and at most 10 lessons learned.
6. Respond with valid JSON only — no markdown, no explanation.
"""

CLOSURE_REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "final_delivery_outcome": {
            "type": "string",
            "description": "3-5 sentences covering what was delivered vs planned",
        },
        "success_criteria_assessments": {
            "type": "array",
            "description": "Assessment of each success criterion",
            "items": {
                "type": "object",
                "properties": {
                    "criterion": {
                        "type": "string",
                        "description": "The success criterion being assessed",
                    },
                    "expected_outcome": {
                        "type": "string",
                        "description": "What was expected",
                    },
                    "measurement_method": {
                        "type": "string",
                        "description": "How the criterion was measured",
                    },
                    "actual_performance": {
                        "type": "string",
                        "description": "What was actually achieved",
                    },
                    "status": {
                        "type": "string",
                        "description": "Exactly: Met, Partially Met, or Not Met",
                    },
                    "comments": {
                        "type": "string",
                        "description": "Additional context or explanation",
                    },
                },
                "required": [
                    "criterion", "expected_outcome", "measurement_method",
                    "actual_performance", "status", "comments",
                ],
            },
        },
        "lessons_learned": {
            "type": "array",
            "description": "Categorised lessons from the project",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "One of: Planning, Team, Technical, Implementation, Commercial, Testing, Change Management, Vendor, Documentation",
                    },
                    "description": {
                        "type": "string",
                        "description": "What was learned",
                    },
                    "effect_triggers": {
                        "type": "string",
                        "description": "What caused or triggered this lesson",
                    },
                    "recommendations": {
                        "type": "string",
                        "description": "What should be done differently next time",
                    },
                    "owner": {
                        "type": "string",
                        "description": "Suggested owner for the recommendation (role, not person)",
                    },
                },
                "required": [
                    "category", "description", "effect_triggers",
                    "recommendations", "owner",
                ],
            },
        },
    },
    "required": [
        "final_delivery_outcome",
        "success_criteria_assessments",
        "lessons_learned",
    ],
}


def build_report_prompt(
    metrics: dict[str, Any],
    pm_notes: str,
    qa_pairs: list[dict[str, str]],
) -> str:
    """Build the user prompt for the report step."""
    parts: list[str] = []

    parts.append(f"# Project Closure Report Data: {metrics.get('project_name', 'Unknown')}")
    parts.append(f"Phase: {metrics.get('phase', 'N/A')} | PM: {metrics.get('pm', 'N/A')} | Sponsor: {metrics.get('sponsor', 'N/A')}")
    parts.append("")

    _append_timeline(parts, metrics)
    _append_scope(parts, metrics)
    _append_risks(parts, metrics)
    _append_decisions(parts, metrics)
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
        "Produce a project closure report. Return a JSON object with "
        "final_delivery_outcome (3-5 sentences), success_criteria_assessments "
        "(array of criterion evaluations), and lessons_learned (3-10 categorised "
        "lessons). Do NOT invent numbers — use the pre-computed data as-is."
    )

    return "\n".join(parts)


# ------------------------------------------------------------------
# Prompt section builders
# ------------------------------------------------------------------


def _append_timeline(parts: list[str], metrics: dict[str, Any]) -> None:
    parts.append("## Project Timeline")
    timeline = metrics.get("timeline", {})
    if timeline:
        parts.append(f"- Planned start: {timeline.get('planned_start', 'N/A')}")
        parts.append(f"- Planned end: {timeline.get('planned_end', 'N/A')}")
        parts.append(f"- Actual end: {timeline.get('actual_end', 'N/A')}")
        parts.append(f"- Deviation: {timeline.get('deviation', 'N/A')}")
    else:
        parts.append("- Timeline data not available.")
    parts.append("")


def _append_scope(parts: list[str], metrics: dict[str, Any]) -> None:
    delivered = metrics.get("scope_delivered", [])
    not_delivered = metrics.get("scope_not_delivered", [])
    parts.append(f"## Scope Delivered ({len(delivered)} items)")
    if delivered:
        for item in delivered:
            parts.append(f"- {item.get('key', '?')}: {item.get('summary', '?')} [{item.get('status', '?')}]")
    else:
        parts.append("- No scope items found.")
    parts.append("")

    parts.append(f"## Scope Not Delivered ({len(not_delivered)} items)")
    if not_delivered:
        for item in not_delivered:
            parts.append(f"- {item.get('key', '?')}: {item.get('summary', '?')} [{item.get('status', '?')}]")
    else:
        parts.append("- All scope items were delivered.")
    parts.append("")


def _append_risks(parts: list[str], metrics: dict[str, Any]) -> None:
    all_risks = metrics.get("all_risks", [])
    open_count = sum(1 for r in all_risks if r.get("status_category") != "Done")
    parts.append(f"## Risks ({len(all_risks)} total, {open_count} still open)")
    if all_risks:
        for r in all_risks[:20]:
            parts.append(
                f"- [{r.get('key', '?')}] {r.get('summary', '?')} "
                f"(priority: {r.get('priority', '?')}, status: {r.get('status', '?')})"
            )
        if len(all_risks) > 20:
            parts.append(f"- ... and {len(all_risks) - 20} more risks")
    else:
        parts.append("- No risks found.")
    parts.append("")


def _append_decisions(parts: list[str], metrics: dict[str, Any]) -> None:
    all_decisions = metrics.get("all_decisions", [])
    parts.append(f"## Decisions ({len(all_decisions)} total)")
    if all_decisions:
        for d in all_decisions[:20]:
            parts.append(
                f"- [{d.get('key', '?')}] {d.get('summary', '?')} "
                f"(status: {d.get('status', '?')})"
            )
        if len(all_decisions) > 20:
            parts.append(f"- ... and {len(all_decisions) - 20} more decisions")
    else:
        parts.append("- No decisions found.")
    parts.append("")


def _append_dev_progress(parts: list[str], metrics: dict[str, Any]) -> None:
    parts.append("## Development Progress (Final)")
    team_progress = metrics.get("team_progress", [])
    if team_progress:
        for t in team_progress:
            blockers = f" | Blockers: {t['blockers']}" if t.get("blockers") else ""
            parts.append(
                f"- {t.get('team', '?')}: {t.get('pct_done', 0)}% "
                f"({t.get('sp_done', 0)}/{t.get('sp_total', 0)} SP){blockers}"
            )
    else:
        parts.append("- No team progress data available.")
    parts.append("")


def _append_doc_progress(parts: list[str], metrics: dict[str, Any]) -> None:
    parts.append("## Documentation Status (Final)")
    dhf_total = metrics.get("dhf_total", 0)
    dhf_released = metrics.get("dhf_released", 0)
    dhf_pct = metrics.get("dhf_completion_pct", 0)
    parts.append(f"- DHF Completion: {dhf_released}/{dhf_total} ({dhf_pct:.0f}%)")
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
