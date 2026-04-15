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

from src.engine.prompts import CONTEXT_REQUESTS_RULE, add_context_requests


# ------------------------------------------------------------------
# Step 1: Questions prompt
# ------------------------------------------------------------------

QUESTIONS_SYSTEM_PROMPT = """\
<role>You are a senior project manager preparing a fortnightly CEO status update for \
a medical device software engineering project.</role>

<context>You have been given project data from the last 2 weeks, including new risks, \
new decisions, development progress delta, documentation progress, and team blockers. \
Your job is to identify what you CANNOT determine from the data alone — things \
like reasons for delays, context behind new risks, stakeholder feedback, \
external dependency changes, or qualitative team dynamics.</context>

<rules>
1. **Proactive discovery first** — before asking the PM anything, consider what \
relevant supporting material probably exists in Confluence or Jira. Issue \
context_requests (prefer confluence_text_search for content discovery). Useful \
searches for a CEO update include:
   - steering-committee / governance / sponsor-update pages
   - escalation log / decisions-register pages
   - release-readiness / go-live / launch-plan pages
   - market update / competitor / customer-feedback pages
   - specific Jira tickets referenced in new risks/decisions (use jira_issue for \
the ticket key)
   - any prior cross-project dependency pages that may have changed
   Prefer context_requests over asking the user.
2. Only ask the PM for information you cannot possibly find via search (e.g. \
qualitative reads on team or sponsor sentiment, unrecorded verbal commitments, \
their own read of why a risk emerged).
3. Each question must include a category (e.g. "Decisions", "Risks", \
"Development", "Documentation", "Stakeholders", "Timeline").
4. Explain briefly why the information is needed for an accurate CEO update.
5. Ask at most 6 questions — focus on the most impactful gaps.
6. If the data + your context_requests + PM notes cover the gaps, return an \
empty questions list.
7. """ + CONTEXT_REQUESTS_RULE + """
</rules>
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
add_context_requests(CEO_QUESTIONS_SCHEMA)


def build_questions_prompt(
    metrics: dict[str, Any],
    pm_notes: str,
) -> str:
    """Build the user prompt for the questions step."""
    parts: list[str] = []

    parts.append(f"<project_context>")
    parts.append(f"Project: {metrics.get('project_name', 'Unknown')}")
    parts.append(f"Phase: {metrics.get('phase', 'N/A')}")
    parts.append(f"Due: {metrics.get('due_date', 'N/A')}")
    parts.append(f"</project_context>")
    parts.append("")
    parts.append(f"<time_window>Last 2 weeks</time_window>")
    parts.append("")

    _append_new_decisions(parts, metrics)
    _append_new_risks(parts, metrics)
    _append_dev_progress(parts, metrics)
    _append_doc_progress(parts, metrics)
    _append_releases(parts, metrics)
    _append_past_ceo_review(parts, metrics)
    _append_action_items(parts, metrics)
    _append_knowledge_entries(parts, metrics)

    if pm_notes and pm_notes.strip():
        parts.append("<pm_notes>")
        parts.append(pm_notes.strip())
        parts.append("</pm_notes>")
        parts.append("")

    parts.append(
        "<instructions>Based on the data above, identify questions you cannot answer from the data "
        "alone. If the data is sufficient, return an empty questions list.</instructions>"
    )

    return "\n".join(parts)


# ------------------------------------------------------------------
# Step 2: Review prompt
# ------------------------------------------------------------------

REVIEW_SYSTEM_PROMPT = """\
<role>You are a senior project manager producing a fortnightly CEO-level project \
status update for a medical device software engineering project.</role>

<context>Focus on what changed in the last 2 weeks. Metrics are pre-computed and \
accurate — reference them but do not alter numbers. Be extremely concise. The \
entire update must fit in ~10 lines when rendered.</context>

<rules>
1. health_indicator must be exactly "On Track", "At Risk", or "Off Track".
2. summary is 1-2 sentences covering the most important change or theme.
3. Each bullet should be ONE short sentence — no more.
4. Include at most 6 bullets total across all areas. Omit areas with nothing \
noteworthy. Combine related points. Less is more.
5. If a topic needs more than one sentence to explain (e.g. a major scope change, \
a new critical risk, or an important decision), do NOT try to squeeze it into the \
update. Instead, add it to deep_dive_topics so the PM can raise it separately in \
a dedicated forum.
6. Escalations should only be raised for issues needing CEO/leadership attention.
7. Next milestones: at most 2, concrete, time-bound where possible.
8. **People references — ALWAYS use @FirstName LastName syntax** whenever you write \
a person's name in your output. This applies both when (a) preserving names already \
mentioned in the PM notes or context (e.g. keep "@Alice Smith" intact — do not drop \
the prefix), and (b) introducing a new person the PM referenced in plain prose \
(e.g. notes say "John Smith raised this" → write "@John Smith", not "John Smith"). \
The `@` prefix is what triggers Confluence to render an interactive user mention; \
plain-text names will publish as dead text with no link.
9. """ + CONTEXT_REQUESTS_RULE + """
</rules>
"""

CEO_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "health_indicator": {
            "type": "string",
            "description": "Overall status: On Track, At Risk, or Off Track",
        },
        "summary": {
            "type": "string",
            "description": "1-2 sentence headline summarising the most important theme or change",
        },
        "bullets": {
            "type": "array",
            "description": "Short update bullets (max 6). Each is one sentence covering any area: dev, docs, risks, decisions, etc.",
            "items": {
                "type": "string",
                "description": "One concise bullet point (single sentence)",
            },
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
            "description": "At most 2 concrete upcoming milestones",
            "items": {
                "type": "string",
                "description": "A concrete upcoming milestone",
            },
        },
        "deep_dive_topics": {
            "type": "array",
            "description": "Topics too complex for a one-liner that the PM should raise separately (e.g. major scope changes, critical new risks, significant decisions)",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Brief title of the topic",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why this needs a separate discussion rather than a bullet",
                    },
                },
                "required": ["topic", "reason"],
            },
        },
    },
    "required": [
        "health_indicator",
        "summary",
        "bullets",
        "escalations",
        "next_milestones",
        "deep_dive_topics",
    ],
}
add_context_requests(CEO_REVIEW_SCHEMA)


def build_review_prompt(
    metrics: dict[str, Any],
    pm_notes: str,
    qa_pairs: list[dict[str, str]],
) -> str:
    """Build the user prompt for the review step."""
    parts: list[str] = []

    parts.append(f"<project_context>")
    parts.append(f"Project: {metrics.get('project_name', 'Unknown')}")
    parts.append(f"Phase: {metrics.get('phase', 'N/A')}")
    parts.append(f"Due: {metrics.get('due_date', 'N/A')}")
    parts.append(f"</project_context>")
    parts.append("")
    parts.append(f"<time_window>Last 2 weeks</time_window>")
    parts.append("")

    _append_new_decisions(parts, metrics)
    _append_new_risks(parts, metrics)
    _append_dev_progress(parts, metrics)
    _append_doc_progress(parts, metrics)
    _append_releases(parts, metrics)
    _append_past_ceo_review(parts, metrics)
    _append_action_items(parts, metrics)
    _append_knowledge_entries(parts, metrics)

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
        "<instructions>Produce a concise CEO-level status update (~10 lines max). "
        "At most 6 one-sentence bullets, max 2 milestones. Move anything too complex "
        "for a single bullet into deep_dive_topics.</instructions>"
    )

    return "\n".join(parts)


# ------------------------------------------------------------------
# Prompt section builders
# ------------------------------------------------------------------


def _append_new_decisions(parts: list[str], metrics: dict[str, Any]) -> None:
    decisions = metrics.get("new_decisions", [])
    parts.append(f"<new_decisions count=\"{len(decisions)}\">")
    if decisions:
        for d in decisions:
            parts.append(f"- [{d.get('key', '?')}] {d.get('summary', '?')} (status: {d.get('status', '?')})")
    else:
        parts.append("No new decisions in this period.")
    parts.append("</new_decisions>")
    parts.append("")


def _append_new_risks(parts: list[str], metrics: dict[str, Any]) -> None:
    new_risks = metrics.get("new_risks", [])
    total = metrics.get("total_risk_count", 0)
    open_count = metrics.get("open_risk_count", 0)
    parts.append(f"<new_risks count=\"{len(new_risks)}\" open=\"{open_count}\" total=\"{total}\">")
    if new_risks:
        for r in new_risks:
            components = r.get("components", "")
            comp_str = f" [{components}]" if components else ""
            parts.append(f"- [{r.get('key', '?')}] {r.get('summary', '?')} (status: {r.get('status', '?')}){comp_str}")
    else:
        parts.append("No new risks in this period.")
    parts.append("</new_risks>")
    parts.append("")


def _append_dev_progress(parts: list[str], metrics: dict[str, Any]) -> None:
    sp_burned = metrics.get("sp_burned_2w", 0)
    scope_change = metrics.get("scope_change_2w", 0)
    parts.append("<development_progress>")
    parts.append(f"Story points burned: {sp_burned}")
    parts.append(f"Scope change: {scope_change:+} SP")

    team_progress = metrics.get("team_progress", [])
    if team_progress:
        parts.append("Per-team:")
        for t in team_progress:
            blockers = f" | Blockers: {t['blockers']}" if t.get("blockers") else ""
            parts.append(
                f"- {t.get('team', '?')}: {t.get('pct_done', 0)}% "
                f"({t.get('sp_done', 0)}/{t.get('sp_total', 0)} SP){blockers}"
            )
    parts.append("</development_progress>")
    parts.append("")


def _append_doc_progress(parts: list[str], metrics: dict[str, Any]) -> None:
    dhf_total = metrics.get("dhf_total", 0)
    dhf_released = metrics.get("dhf_released", 0)
    dhf_pct = metrics.get("dhf_completion_pct", 0)
    parts.append("<documentation_progress>")
    parts.append(f"DHF Completion: {dhf_released}/{dhf_total} ({dhf_pct:.0f}%)")

    recently_updated = metrics.get("dhf_recently_updated", [])
    if recently_updated:
        parts.append("Recently updated (last 2 weeks):")
        for doc in recently_updated:
            parts.append(f"- {doc.get('title', '?')} ({doc.get('status', '?')}) — {doc.get('last_modified', '?')}")
    else:
        parts.append("No documents updated in last 2 weeks.")
    parts.append("</documentation_progress>")
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


def _append_past_ceo_review(parts: list[str], metrics: dict[str, Any]) -> None:
    """Format prior CEO reviews with full narrative so the LLM has continuity.

    This lets the LLM write deltas like "Previously reported At Risk due to X;
    that has since been resolved, and the current concern is Y."
    """
    reviews = metrics.get("past_ceo_reviews", [])
    if not reviews:
        return
    parts.append("<previous_ceo_review>")
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
            parts.append("Escalations raised:")
            for esc in escalations:
                parts.append(
                    f"  - {esc.get('issue', '?')} — impact: {esc.get('impact', '?')} "
                    f"— ask: {esc.get('ask', '?')}"
                )

        milestones = r.get("next_milestones") or []
        if milestones:
            parts.append("Next milestones called out previously:")
            for m in milestones:
                parts.append(f"  - {m}")

        deep_dives = r.get("deep_dive_topics") or []
        if deep_dives:
            parts.append("Deep-dive topics flagged:")
            for d in deep_dives:
                parts.append(f"  - {d.get('topic', '?')}: {d.get('reason', '?')}")
    parts.append("</previous_ceo_review>")
    parts.append("")


def _append_action_items(parts: list[str], metrics: dict[str, Any]) -> None:
    items = metrics.get("open_action_items", [])
    if not items:
        return
    parts.append("<open_action_items>")
    for a in items:
        owner = a.get("owner", "unassigned")
        parts.append(f"- {a.get('title', '?')} (owner: {owner}, status: {a.get('status', '?')})")
    parts.append("</open_action_items>")
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
