"""Health review prompt templates and schema definitions.

Two-step LLM interaction:
1. **Questions**: LLM reviews all project data and asks the PM questions it
   cannot answer from the data alone (e.g. team morale, budget, external deps).
2. **Review**: LLM produces a structured health review with rating, concerns,
   positives, and next actions.
"""

from __future__ import annotations

from typing import Any

from src.engine.prompts import CONTEXT_REQUESTS_RULE, add_context_requests


# ------------------------------------------------------------------
# Step 1: Questions prompt
# ------------------------------------------------------------------

QUESTIONS_SYSTEM_PROMPT = """\
<role>You are a senior project manager reviewing health data for a medical device \
software engineering project. You have been given comprehensive project data \
including Jira metrics, risk register, decision log, document status, team \
progress, and more.</role>

<context>Your job is to identify what you CANNOT determine from the data alone — things \
like team morale, budget status, stakeholder sentiment, external dependency \
risks, regulatory timeline pressures, or organisational changes.</context>

<rules>
1. Only ask questions about information genuinely absent from the provided data.
2. Each question must include a category (e.g. "Team", "Budget", "Stakeholders", \
"External Dependencies", "Regulatory", "Timeline").
3. Explain briefly why the information is needed for an accurate health assessment.
4. Ask at most 6 questions — focus on the most impactful gaps.
5. If the data is comprehensive enough for a full review, return an empty list.
6. """ + CONTEXT_REQUESTS_RULE + """
</rules>
"""

HEALTH_QUESTIONS_SCHEMA: dict[str, Any] = {
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
                        "description": "Category: Team, Budget, Stakeholders, External Dependencies, Regulatory, Timeline, or Other",
                    },
                    "why_needed": {
                        "type": "string",
                        "description": "Why this information is needed for an accurate health assessment",
                    },
                },
                "required": ["question", "category", "why_needed"],
            },
        },
    },
    "required": ["questions"],
}
add_context_requests(HEALTH_QUESTIONS_SCHEMA)


def build_questions_prompt(project_context: dict[str, Any]) -> str:
    """Build the user prompt for the questions step.

    Args:
        project_context: Dict assembled by HealthReviewService.gather_all_context().
    """
    parts: list[str] = []

    parts.append(f"<project_name>{project_context.get('project_name', 'Unknown')}</project_name>")
    parts.append("")

    # Goal / summary
    goal = project_context.get("goal")
    if goal:
        parts.append("<goal_ticket>")
        parts.append(f"Key: {goal.get('key', 'N/A')}")
        parts.append(f"Summary: {goal.get('summary', 'N/A')}")
        parts.append(f"Status: {goal.get('status', 'N/A')}")
        parts.append(f"Due date: {goal.get('due_date', 'N/A')}")
        parts.append("</goal_ticket>")
        parts.append("")

    # Risk register
    _append_risk_summary(parts, project_context)
    _append_decision_summary(parts, project_context)
    _append_initiative_summary(parts, project_context)
    _append_team_progress(parts, project_context)
    _append_burnup_data(parts, project_context)
    _append_dhf_summary(parts, project_context)
    _append_pi_summary(parts, project_context)
    _append_release_summary(parts, project_context)
    _append_charter_xft(parts, project_context)
    _append_meeting_summaries(parts, project_context)
    _append_action_items(parts, project_context)
    _append_knowledge_entries(parts, project_context)
    _append_past_health_reviews(parts, project_context)

    parts.append(
        "<instructions>Based on the data above, identify questions you cannot answer from the data "
        "alone. If the data is sufficient, return an empty questions list.</instructions>"
    )

    return "\n".join(parts)


# ------------------------------------------------------------------
# Step 2: Review prompt
# ------------------------------------------------------------------

REVIEW_SYSTEM_PROMPT = """\
<role>You are a senior project manager producing a structured health review for a \
medical device software engineering project. You have been given comprehensive \
project data and the PM's answers to your clarifying questions.</role>

<context>Produce an honest, evidence-based assessment. Cite specific data points when \
identifying concerns. Be constructive — every concern should come with a \
recommendation.</context>

<rules>
1. health_rating must be exactly "Green", "Amber", or "Red".
2. Top concerns should be ranked by severity (High first). Include at most 5.
3. Positive observations should highlight things going well. Include at most 5.
4. Suggested next actions should be concrete and actionable.
5. """ + CONTEXT_REQUESTS_RULE + """
</rules>
"""

HEALTH_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "health_rating": {
            "type": "string",
            "description": "Overall health rating: Green, Amber, or Red",
        },
        "health_rationale": {
            "type": "string",
            "description": "One-line rationale for the health rating",
        },
        "top_concerns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "area": {
                        "type": "string",
                        "description": "Area of concern (e.g. Risk Management, Timeline, Resources)",
                    },
                    "severity": {
                        "type": "string",
                        "description": "High, Medium, or Low",
                    },
                    "evidence": {
                        "type": "string",
                        "description": "Specific data points supporting this concern",
                    },
                    "recommendation": {
                        "type": "string",
                        "description": "Concrete recommendation to address this concern",
                    },
                },
                "required": ["area", "severity", "evidence", "recommendation"],
            },
        },
        "positive_observations": {
            "type": "array",
            "items": {
                "type": "string",
                "description": "A positive observation about the project",
            },
        },
        "questions_for_pm": {
            "type": "array",
            "items": {
                "type": "string",
                "description": "A question the PM should investigate",
            },
        },
        "suggested_next_actions": {
            "type": "array",
            "items": {
                "type": "string",
                "description": "A concrete, actionable next step",
            },
        },
    },
    "required": [
        "health_rating",
        "health_rationale",
        "top_concerns",
        "positive_observations",
        "questions_for_pm",
        "suggested_next_actions",
    ],
}
add_context_requests(HEALTH_REVIEW_SCHEMA)


def build_review_prompt(
    project_context: dict[str, Any],
    qa_pairs: list[dict[str, str]],
) -> str:
    """Build the user prompt for the review step.

    Args:
        project_context: Dict assembled by HealthReviewService.gather_all_context().
        qa_pairs: List of {question, answer} dicts from the Q&A step.
    """
    parts: list[str] = []

    parts.append(f"<project_name>{project_context.get('project_name', 'Unknown')}</project_name>")
    parts.append("")

    goal = project_context.get("goal")
    if goal:
        parts.append("<goal_ticket>")
        parts.append(f"Key: {goal.get('key', 'N/A')}")
        parts.append(f"Summary: {goal.get('summary', 'N/A')}")
        parts.append(f"Status: {goal.get('status', 'N/A')}")
        parts.append(f"Due date: {goal.get('due_date', 'N/A')}")
        parts.append("</goal_ticket>")
        parts.append("")

    _append_risk_summary(parts, project_context)
    _append_decision_summary(parts, project_context)
    _append_initiative_summary(parts, project_context)
    _append_team_progress(parts, project_context)
    _append_burnup_data(parts, project_context)
    _append_dhf_summary(parts, project_context)
    _append_pi_summary(parts, project_context)
    _append_release_summary(parts, project_context)
    _append_charter_xft(parts, project_context)
    _append_meeting_summaries(parts, project_context)

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
        "<instructions>Produce a structured health review with health_rating, "
        "health_rationale, top_concerns, positive_observations, "
        "questions_for_pm, and suggested_next_actions.</instructions>"
    )

    return "\n".join(parts)


# ------------------------------------------------------------------
# Prompt section builders (shared by both steps)
# ------------------------------------------------------------------


def _append_risk_summary(parts: list[str], ctx: dict[str, Any]) -> None:
    risk_count = ctx.get("risk_count", 0)
    open_risk_count = ctx.get("open_risk_count", 0)
    parts.append("<risk_register>")
    parts.append(f"Total risks: {risk_count}")
    parts.append(f"Open risks: {open_risk_count}")
    risk_points = ctx.get("risk_points")
    risk_threshold = ctx.get("risk_threshold")
    risk_level = ctx.get("risk_level")
    if risk_points is not None:
        parts.append(f"Risk points: {risk_points}")
    if risk_threshold is not None:
        parts.append(f"Risk threshold: {risk_threshold}")
    if risk_level:
        parts.append(f"Risk level: {risk_level}")
    risks = ctx.get("risks", [])
    if risks:
        parts.append("Open risk details:")
        for r in risks[:15]:
            parts.append(f"  - [{r.get('key', '?')}] {r.get('summary', '?')} (status: {r.get('status', '?')})")
    parts.append("</risk_register>")
    parts.append("")


def _append_decision_summary(parts: list[str], ctx: dict[str, Any]) -> None:
    decision_count = ctx.get("decision_count", 0)
    parts.append("<decision_log>")
    parts.append(f"Total decisions: {decision_count}")
    decisions = ctx.get("decisions", [])
    if decisions:
        for d in decisions[:10]:
            parts.append(f"  - [{d.get('key', '?')}] {d.get('summary', '?')} (status: {d.get('status', '?')})")
    parts.append("</decision_log>")
    parts.append("")


def _append_initiative_summary(parts: list[str], ctx: dict[str, Any]) -> None:
    initiatives = ctx.get("initiatives", [])
    parts.append("<initiatives>")
    if not initiatives:
        parts.append("No initiative data available")
    else:
        parts.append(f"Total: {len(initiatives)}")
        for init in initiatives:
            parts.append(
                f"- {init.get('key', '?')} {init.get('summary', '?')}: "
                f"{init.get('done_epic_count', 0)}/{init.get('epic_count', 0)} epics done, "
                f"{init.get('done_task_count', 0)}/{init.get('task_count', 0)} tasks done"
            )
    parts.append("</initiatives>")
    parts.append("")


def _append_team_progress(parts: list[str], ctx: dict[str, Any]) -> None:
    reports = ctx.get("team_reports", [])
    parts.append("<team_progress>")
    if not reports:
        parts.append("No team progress data available")
    else:
        parts.append(f"Teams: {len(reports)}")
        for r in reports:
            line = (
                f"- {r.get('team_key', '?')} ({r.get('version_name', '?')}): "
                f"{r.get('done_count', 0)}/{r.get('total_issues', 0)} issues done "
                f"({r.get('pct_done_issues', 0)}%), "
                f"{r.get('sp_done', 0)}/{r.get('sp_total', 0)} SP done"
            )
            if r.get("blocker_count", 0):
                line += f" | Blockers: {r['blocker_count']}"
            parts.append(line)
    parts.append("</team_progress>")
    parts.append("")


def _append_burnup_data(parts: list[str], ctx: dict[str, Any]) -> None:
    snapshots = ctx.get("burnup_snapshots", [])
    if not snapshots:
        return
    parts.append("<burnup_velocity>")
    first = snapshots[0]
    last = snapshots[-1]
    parts.append(f"Snapshots: {len(snapshots)} (last 90 days)")
    parts.append(f"First ({first.get('date', '?')}): scope={first.get('sp_total', 0)} SP, done={first.get('sp_done', 0)} SP")
    parts.append(f"Latest ({last.get('date', '?')}): scope={last.get('sp_total', 0)} SP, done={last.get('sp_done', 0)} SP")
    if len(snapshots) >= 2:
        scope_delta = last.get("sp_total", 0) - first.get("sp_total", 0)
        done_delta = last.get("sp_done", 0) - first.get("sp_done", 0)
        parts.append(f"Scope change: {scope_delta:+} SP")
        parts.append(f"Done change: {done_delta:+} SP")
    parts.append("</burnup_velocity>")
    parts.append("")


def _append_dhf_summary(parts: list[str], ctx: dict[str, Any]) -> None:
    dhf = ctx.get("dhf_summary")
    parts.append("<dhf_documents>")
    if not dhf:
        parts.append("No DHF data available")
    else:
        parts.append(f"Total: {dhf.get('total_count', 0)}")
        parts.append(f"Released: {dhf.get('released_count', 0)}")
        parts.append(f"Draft updates: {dhf.get('draft_update_count', 0)}")
        parts.append(f"In draft only: {dhf.get('in_draft_count', 0)}")
        total = dhf.get("total_count", 0)
        if total > 0:
            pct = round(100 * dhf.get("released_count", 0) / total)
            parts.append(f"Release readiness: {pct}%")
    parts.append("</dhf_documents>")
    parts.append("")


def _append_pi_summary(parts: list[str], ctx: dict[str, Any]) -> None:
    pi = ctx.get("pi_summary")
    if not pi:
        return
    parts.append("<product_ideas>")
    parts.append(f"Total: {pi.get('total_count', 0)}")
    parts.append(f"Open: {pi.get('open_count', 0)}")
    parts.append(f"Done: {pi.get('done_count', 0)}")
    parts.append(f"Must-have: {pi.get('must_have_count', 0)}")
    parts.append(f"Features: {pi.get('feature_count', 0)}, Minor features: {pi.get('minor_feature_count', 0)}")
    parts.append(f"Defects: {pi.get('defect_count', 0)}")
    parts.append("</product_ideas>")
    parts.append("")


def _append_release_summary(parts: list[str], ctx: dict[str, Any]) -> None:
    releases = ctx.get("releases", [])
    if not releases:
        return
    parts.append("<releases>")
    for rel in releases:
        locked = "LOCKED" if rel.get("locked") else "unlocked"
        parts.append(f"- {rel.get('name', '?')} ({locked})")
    parts.append("</releases>")
    parts.append("")


def _append_charter_xft(parts: list[str], ctx: dict[str, Any]) -> None:
    charter = ctx.get("charter_content")
    if charter:
        truncated = charter[:3000]
        parts.append("<charter_content>")
        parts.append(truncated)
        parts.append("</charter_content>")
        parts.append("")
    xft = ctx.get("xft_content")
    if xft:
        truncated = xft[:3000]
        parts.append("<xft_notes>")
        parts.append(truncated)
        parts.append("</xft_notes>")
        parts.append("")


def _append_meeting_summaries(parts: list[str], ctx: dict[str, Any]) -> None:
    summaries = ctx.get("meeting_summaries", [])
    if not summaries:
        return
    parts.append("<recent_meetings>")
    for ms in summaries[:5]:
        parts.append(f"<meeting title=\"{ms.get('filename', 'Meeting')}\" date=\"{ms.get('created_at', '?')}\">")
        parts.append(ms.get("summary", "No summary")[:500])
        parts.append("</meeting>")
    parts.append("</recent_meetings>")
    parts.append("")


def _append_action_items(parts: list[str], ctx: dict[str, Any]) -> None:
    items = ctx.get("open_action_items", [])
    if not items:
        return
    parts.append("<open_action_items>")
    for a in items:
        owner = a.get("owner", "unassigned")
        parts.append(f"- {a.get('title', '?')} (owner: {owner}, status: {a.get('status', '?')})")
    parts.append("</open_action_items>")
    parts.append("")


def _append_knowledge_entries(parts: list[str], ctx: dict[str, Any]) -> None:
    entries = ctx.get("knowledge_entries", [])
    if not entries:
        return
    parts.append("<knowledge_base>")
    for e in entries:
        parts.append(f"- [{e.get('type', '?')}] {e.get('title', '?')}")
    parts.append("</knowledge_base>")
    parts.append("")


def _append_past_health_reviews(parts: list[str], ctx: dict[str, Any]) -> None:
    reviews = ctx.get("past_health_reviews", [])
    if not reviews:
        return
    parts.append("<previous_health_review>")
    for r in reviews:
        parts.append(f"Rating: {r.get('health_rating', 'N/A')}")
        parts.append(f"Rationale: {r.get('health_rationale', 'N/A')}")
        parts.append(f"Date: {r.get('created_at', 'N/A')}")
    parts.append("</previous_health_review>")
    parts.append("")
