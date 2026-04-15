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

from src.engine.prompts import CONTEXT_REQUESTS_RULE, add_context_requests


# ------------------------------------------------------------------
# Step 1: Questions prompt
# ------------------------------------------------------------------

QUESTIONS_SYSTEM_PROMPT = """\
<role>You are a senior project manager preparing a formal project closure report \
for a medical device software engineering project.</role>

<context>You have been given the full project lifecycle data including risks, decisions, \
Charter scope, team progress, documentation status, and releases. Your job is to \
identify what you CANNOT determine from the data alone — things like lessons learned, \
delivery assessment quality, success criteria outcomes, stakeholder satisfaction, \
vendor performance, reasons for timeline deviations, and team retrospective insights.</context>

<rules>
1. **Proactive discovery first** — before asking the PM anything, consider what \
closure-relevant supporting material likely exists in Confluence or Jira. Issue \
context_requests (prefer confluence_text_search for content discovery). Useful \
searches for a closure report include:
   - retrospective / lessons-learned / post-mortem / retro pages
   - launch / go-live / release-readiness review pages
   - post-release support / incidents / known-issues pages
   - vendor performance / third-party delivery pages
   - test-summary / validation / qualification / UAT pages
   - stakeholder satisfaction / customer-feedback / sponsor-sign-off pages
   - specific Jira tickets referenced by risks/decisions you need more detail on
   Prefer context_requests over asking the user. Remember past Health and CEO \
Reviews are already provided — use them for health-trend narrative.
2. Only ask the PM for information that cannot be found via search (e.g. their \
retrospective take on what worked/didn't, qualitative judgement on sponsor \
satisfaction, unrecorded verbal commitments).
3. Each question must include a category (e.g. "Lessons Learned", "Delivery", \
"Success Criteria", "Stakeholders", "Timeline", "Team", "Vendor", "Testing").
4. Explain briefly why the information is needed for a complete closure report.
5. Ask at most 8 questions — focus on the most impactful gaps.
6. If the data + your context_requests + PM notes cover the gaps, return an \
empty questions list.
7. """ + CONTEXT_REQUESTS_RULE + """
</rules>
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
add_context_requests(CLOSURE_QUESTIONS_SCHEMA)


def build_questions_prompt(
    metrics: dict[str, Any],
    pm_notes: str,
) -> str:
    """Build the user prompt for the questions step."""
    parts: list[str] = []

    parts.append("<project_context>")
    parts.append(f"Project: {metrics.get('project_name', 'Unknown')}")
    parts.append(f"Phase: {metrics.get('phase', 'N/A')}")
    parts.append(f"PM: {metrics.get('pm', 'N/A')}")
    parts.append(f"Sponsor: {metrics.get('sponsor', 'N/A')}")
    parts.append("</project_context>")
    parts.append("")

    _append_timeline(parts, metrics)
    _append_charter_sections(parts, metrics)
    _append_scope(parts, metrics)
    _append_risks(parts, metrics)
    _append_decisions(parts, metrics)
    _append_dev_progress(parts, metrics)
    _append_doc_progress(parts, metrics)
    _append_releases(parts, metrics)
    _append_action_items(parts, metrics)
    _append_knowledge_entries(parts, metrics)
    _append_meeting_summaries(parts, metrics)
    _append_past_health_reviews(parts, metrics)
    _append_past_ceo_reviews(parts, metrics)

    if pm_notes and pm_notes.strip():
        parts.append("<pm_notes>")
        parts.append(pm_notes.strip())
        parts.append("</pm_notes>")
        parts.append("")

    parts.append(
        "<instructions>Based on the data above, identify questions you cannot answer from the data "
        "alone for a comprehensive project closure report. Focus on lessons learned, success criteria, "
        "delivery assessment, and stakeholder satisfaction. If the data is sufficient, return an "
        "empty questions list.</instructions>"
    )

    return "\n".join(parts)


# ------------------------------------------------------------------
# Step 2: Report prompt
# ------------------------------------------------------------------

REPORT_SYSTEM_PROMPT = """\
<role>You are a senior project manager producing a formal project closure report \
for a medical device software engineering project. The report will be \
published to Confluence as a permanent record.</role>

<context>Deterministic data tables (timeline, scope, risks, issues) are pre-computed \
and accurate — you must NOT invent or alter any numbers. Your job is to \
produce narrative sections only:
1. final_delivery_outcome: 3-5 sentences covering what was delivered vs planned.
2. success_criteria_assessments: For each success criterion, assess actual \
performance against expected outcomes.
3. lessons_learned: Categorised lessons with descriptions, triggers, \
recommendations, and suggested owners.</context>

<rules>
1. final_delivery_outcome must be 3-5 sentences. Be factual, not promotional.
2. Each success criterion assessment must have: criterion, expected_outcome, \
measurement_method, actual_performance, status (exactly "Met", "Partially Met", \
or "Not Met"), and comments.
3. Lessons learned categories must be one of: Planning, Team, Technical, \
Implementation, Commercial, Testing, Change Management, Vendor, Documentation.
4. Each lesson must have description, effect_triggers, recommendations, and owner.
5. Include at least 3 and at most 10 lessons learned.
6. """ + CONTEXT_REQUESTS_RULE + """
</rules>
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
add_context_requests(CLOSURE_REPORT_SCHEMA)


def build_report_prompt(
    metrics: dict[str, Any],
    pm_notes: str,
    qa_pairs: list[dict[str, str]],
) -> str:
    """Build the user prompt for the report step."""
    parts: list[str] = []

    parts.append("<project_context>")
    parts.append(f"Project: {metrics.get('project_name', 'Unknown')}")
    parts.append(f"Phase: {metrics.get('phase', 'N/A')}")
    parts.append(f"PM: {metrics.get('pm', 'N/A')}")
    parts.append(f"Sponsor: {metrics.get('sponsor', 'N/A')}")
    parts.append("</project_context>")
    parts.append("")

    _append_timeline(parts, metrics)
    _append_charter_sections(parts, metrics)
    _append_scope(parts, metrics)
    _append_risks(parts, metrics)
    _append_decisions(parts, metrics)
    _append_dev_progress(parts, metrics)
    _append_doc_progress(parts, metrics)
    _append_releases(parts, metrics)
    _append_action_items(parts, metrics)
    _append_knowledge_entries(parts, metrics)
    _append_meeting_summaries(parts, metrics)
    _append_past_health_reviews(parts, metrics)
    _append_past_ceo_reviews(parts, metrics)

    if pm_notes and pm_notes.strip():
        parts.append("<pm_notes>")
        parts.append(pm_notes.strip())
        parts.append("</pm_notes>")
        parts.append("")

    if qa_pairs:
        parts.append("<pm_answers>")
        for i, qa in enumerate(qa_pairs, 1):
            parts.append(f"<qa_pair>")
            parts.append(f"Q{i}: {qa['question']}")
            parts.append(f"A{i}: {qa['answer']}")
            parts.append(f"</qa_pair>")
        parts.append("</pm_answers>")
        parts.append("")

    parts.append(
        "<instructions>Produce a project closure report with final_delivery_outcome "
        "(3-5 sentences), success_criteria_assessments (array of criterion evaluations), "
        "and lessons_learned (3-10 categorised lessons). Do NOT invent numbers — use "
        "the pre-computed data as-is.</instructions>"
    )

    return "\n".join(parts)


# ------------------------------------------------------------------
# Prompt section builders
# ------------------------------------------------------------------


def _append_timeline(parts: list[str], metrics: dict[str, Any]) -> None:
    timeline = metrics.get("timeline", {})
    parts.append("<project_timeline>")
    if timeline:
        parts.append(f"Planned start: {timeline.get('planned_start', 'N/A')}")
        parts.append(f"Planned end: {timeline.get('planned_end', 'N/A')}")
        parts.append(f"Actual end: {timeline.get('actual_end', 'N/A')}")
        parts.append(f"Deviation: {timeline.get('deviation', 'N/A')}")
    else:
        parts.append("Timeline data not available.")
    parts.append("</project_timeline>")
    parts.append("")


def _append_scope(parts: list[str], metrics: dict[str, Any]) -> None:
    delivered = metrics.get("scope_delivered", [])
    not_delivered = metrics.get("scope_not_delivered", [])
    parts.append(f"<scope_delivered count=\"{len(delivered)}\">")
    if delivered:
        for item in delivered:
            parts.append(f"- {item.get('key', '?')}: {item.get('summary', '?')} [{item.get('status', '?')}]")
    else:
        parts.append("No scope items found.")
    parts.append("</scope_delivered>")
    parts.append("")

    parts.append(f"<scope_not_delivered count=\"{len(not_delivered)}\">")
    if not_delivered:
        for item in not_delivered:
            parts.append(f"- {item.get('key', '?')}: {item.get('summary', '?')} [{item.get('status', '?')}]")
    else:
        parts.append("All scope items were delivered.")
    parts.append("</scope_not_delivered>")
    parts.append("")


def _append_risks(parts: list[str], metrics: dict[str, Any]) -> None:
    all_risks = metrics.get("all_risks", [])
    open_count = sum(1 for r in all_risks if r.get("status_category") != "Done")
    parts.append(f"<risks total=\"{len(all_risks)}\" open=\"{open_count}\">")
    if all_risks:
        for r in all_risks[:20]:
            parts.append(
                f"- [{r.get('key', '?')}] {r.get('summary', '?')} "
                f"(priority: {r.get('priority', '?')}, status: {r.get('status', '?')})"
            )
        if len(all_risks) > 20:
            parts.append(f"... and {len(all_risks) - 20} more risks")
    else:
        parts.append("No risks found.")
    parts.append("</risks>")
    parts.append("")


def _append_decisions(parts: list[str], metrics: dict[str, Any]) -> None:
    all_decisions = metrics.get("all_decisions", [])
    parts.append(f"<decisions total=\"{len(all_decisions)}\">")
    if all_decisions:
        for d in all_decisions[:20]:
            parts.append(
                f"- [{d.get('key', '?')}] {d.get('summary', '?')} "
                f"(status: {d.get('status', '?')})"
            )
        if len(all_decisions) > 20:
            parts.append(f"... and {len(all_decisions) - 20} more decisions")
    else:
        parts.append("No decisions found.")
    parts.append("</decisions>")
    parts.append("")


def _append_dev_progress(parts: list[str], metrics: dict[str, Any]) -> None:
    team_progress = metrics.get("team_progress", [])
    parts.append("<development_progress>")
    if team_progress:
        for t in team_progress:
            blockers = f" | Blockers: {t['blockers']}" if t.get("blockers") else ""
            parts.append(
                f"- {t.get('team', '?')}: {t.get('pct_done', 0)}% "
                f"({t.get('sp_done', 0)}/{t.get('sp_total', 0)} SP){blockers}"
            )
    else:
        parts.append("No team progress data available.")
    parts.append("</development_progress>")
    parts.append("")


def _append_doc_progress(parts: list[str], metrics: dict[str, Any]) -> None:
    dhf_total = metrics.get("dhf_total", 0)
    dhf_released = metrics.get("dhf_released", 0)
    dhf_pct = metrics.get("dhf_completion_pct", 0)
    parts.append("<documentation_status>")
    parts.append(f"DHF Completion: {dhf_released}/{dhf_total} ({dhf_pct:.0f}%)")
    parts.append("</documentation_status>")
    parts.append("")


def _append_releases(parts: list[str], metrics: dict[str, Any]) -> None:
    releases = metrics.get("releases", [])
    if not releases:
        return
    parts.append("<releases>")
    for rel in releases:
        locked = "LOCKED" if rel.get("locked") else "unlocked"
        parts.append(f"- {rel.get('name', '?')} ({locked})")
    parts.append("</releases>")
    parts.append("")


def _append_action_items(parts: list[str], metrics: dict[str, Any]) -> None:
    items = metrics.get("action_items", [])
    if not items:
        return
    parts.append("<action_items>")
    for a in items:
        owner = a.get("owner", "unassigned")
        parts.append(f"- {a.get('title', '?')} (owner: {owner}, status: {a.get('status', '?')})")
    parts.append("</action_items>")
    parts.append("")


def _append_knowledge_entries(parts: list[str], metrics: dict[str, Any]) -> None:
    entries = metrics.get("knowledge_entries", [])
    if not entries:
        return
    parts.append("<knowledge_base>")
    for e in entries:
        parts.append(f"- [{e.get('type', '?')}] {e.get('title', '?')}")
    parts.append("</knowledge_base>")
    parts.append("")


def _append_meeting_summaries(parts: list[str], metrics: dict[str, Any]) -> None:
    summaries = metrics.get("meeting_summaries", [])
    if not summaries:
        return
    parts.append("<meeting_history>")
    for ms in summaries:
        parts.append(f"- {ms.get('filename', '?')}: {ms.get('summary', 'No summary')}")
    parts.append("</meeting_history>")
    parts.append("")


def _append_charter_sections(parts: list[str], metrics: dict[str, Any]) -> None:
    """Expose the Charter as structured sections so the LLM can read success
    criteria, scope, objectives, etc. without parsing XHTML.
    """
    sections = metrics.get("charter_sections") or {}
    if not sections:
        return
    # Emphasise fields most relevant to closure: Success Criteria, Scope, Objectives.
    priority = [
        "Success Criteria", "Project Scope — In Scope", "Project Scope — Out of Scope",
        "Commercial Objective", "Commercial Driver",
        "OKR alignment", "Stakeholders",
    ]
    parts.append("<charter_sections>")
    seen: set[str] = set()
    for name in priority:
        if name in sections:
            parts.append(f"<section name=\"{name}\">")
            parts.append(sections[name])
            parts.append("</section>")
            seen.add(name)
    # Include any remaining sections (in case names vary by template)
    for name, content in sections.items():
        if name in seen:
            continue
        parts.append(f"<section name=\"{name}\">")
        parts.append(content)
        parts.append("</section>")
    parts.append("</charter_sections>")
    parts.append("")


def _append_past_health_reviews(parts: list[str], metrics: dict[str, Any]) -> None:
    """Full-narrative past Health Reviews so the closure can describe the
    health-trend over the project lifecycle (Green → Amber → resolved, etc.)."""
    reviews = metrics.get("past_health_reviews") or []
    if not reviews:
        return
    parts.append("<past_health_reviews>")
    for r in reviews:
        parts.append(f"Date: {r.get('created_at', 'N/A')}")
        parts.append(f"Rating: {r.get('health_rating', 'N/A')}")
        parts.append(f"Rationale: {r.get('health_rationale', 'N/A')}")
        concerns = r.get("top_concerns") or []
        if concerns:
            parts.append("Concerns:")
            for c in concerns:
                parts.append(
                    f"  - [{c.get('severity', '?')}] {c.get('area', '?')}: "
                    f"{c.get('evidence', '?')}"
                )
        positives = r.get("positive_observations") or []
        if positives:
            parts.append("Positives:")
            for p in positives:
                parts.append(f"  - {p}")
        parts.append("---")
    parts.append("</past_health_reviews>")
    parts.append("")


def _append_past_ceo_reviews(parts: list[str], metrics: dict[str, Any]) -> None:
    """Full-narrative past CEO Reviews so the closure can reference what
    leadership was told at each checkpoint."""
    reviews = metrics.get("past_ceo_reviews") or []
    if not reviews:
        return
    parts.append("<past_ceo_reviews>")
    for r in reviews:
        parts.append(f"Date: {r.get('created_at', 'N/A')}")
        parts.append(f"Status: {r.get('health_indicator', 'N/A')}")
        parts.append(f"Headline: {r.get('summary', 'N/A')}")
        bullets = r.get("bullets") or []
        if bullets:
            parts.append("Bullets:")
            for b in bullets:
                parts.append(f"  - {b}")
        escalations = r.get("escalations") or []
        if escalations:
            parts.append("Escalations:")
            for esc in escalations:
                parts.append(
                    f"  - {esc.get('issue', '?')} — {esc.get('impact', '?')}"
                )
        parts.append("---")
    parts.append("</past_ceo_reviews>")
    parts.append("")
