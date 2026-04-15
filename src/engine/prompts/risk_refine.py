"""Risk/decision refinement prompt templates and schema definitions.

Supports iterative Q&A refinement of transcript-extracted risks and decisions,
evaluating quality against medical device risk management standards.
"""

from __future__ import annotations

from typing import Any

from src.engine.prompts import CONTEXT_REQUESTS_RULE, add_context_requests

SYSTEM_PROMPT = """\
<role>You are a senior risk management specialist for a medical device software engineering \
programme. Your job is to iteratively refine risk and decision records so they meet \
the quality standards required by ISO 14971 and IEC 62304 traceability expectations.</role>

<quality_criteria>
1. Clear title — concise, specific, actionable (under 80 chars). \
States what could go wrong (risks) or what was decided (decisions).
2. Detailed background — sufficient context for someone unfamiliar with the \
meeting to understand the situation. Includes relevant technical details, \
affected components/systems, and stakeholders involved.
3. Specific impact analysis — describes severity (patient safety, regulatory, \
timeline, cost) and probability. Quantifies where possible.
4. Concrete mitigation steps — actionable, assignable steps to reduce the risk. \
Not vague platitudes like "monitor the situation".
5. Justified priority — High/Medium/Low with reasoning tied to impact and probability.
6. Timeline impact — realistic estimate of schedule impact in days. \
0 only when genuinely no schedule effect.
7. Transcript evidence — direct quote or close paraphrase anchoring the item \
to what was actually discussed.
</quality_criteria>

<rules>
When evaluating, be strict: a risk that says "this could be a problem" without \
specifics is NOT satisfactory. Each field should stand on its own as professional \
documentation that a regulatory auditor would find adequate.

When refining, preserve the user's intent and any information from previous answers. \
Build incrementally — don't discard good content from earlier rounds.

""" + CONTEXT_REQUESTS_RULE + """
</rules>
"""

RISK_REFINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "satisfied": {
            "type": "boolean",
            "description": (
                "true if the current draft meets all quality criteria and "
                "no further refinement is needed"
            ),
        },
        "quality_assessment": {
            "type": "string",
            "description": (
                "Brief (2-3 sentence) assessment of the current draft quality. "
                "Mention what is good and what still needs work."
            ),
        },
        "questions": {
            "type": "array",
            "description": (
                "Targeted questions to fill gaps in the draft. "
                "Empty array when satisfied is true."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The clarifying question to ask the user",
                    },
                    "field": {
                        "type": "string",
                        "description": (
                            "Which field this question helps improve: "
                            "title, background, impact_analysis, mitigation, "
                            "priority, timeline_impact_days, evidence"
                        ),
                    },
                    "why_needed": {
                        "type": "string",
                        "description": "Brief explanation of why this information matters",
                    },
                },
                "required": ["question", "field", "why_needed"],
            },
        },
        "refined_risk": {
            "type": "object",
            "description": (
                "The best version of the risk/decision so far, "
                "incorporating all available information."
            ),
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Concise title (under 80 chars)",
                },
                "background": {
                    "type": "string",
                    "description": "Detailed background/context",
                },
                "impact_analysis": {
                    "type": "string",
                    "description": "Specific impact analysis with severity and probability",
                },
                "mitigation": {
                    "type": "string",
                    "description": "Concrete mitigation/control steps",
                },
                "priority": {
                    "type": "string",
                    "enum": ["High", "Medium", "Low"],
                    "description": "Justified priority level",
                },
                "timeline_impact_days": {
                    "type": "number",
                    "description": "Estimated days of schedule impact (0 if none)",
                },
                "evidence": {
                    "type": "string",
                    "description": "Direct quote or close paraphrase from transcript",
                },
            },
            "required": [
                "title", "background", "impact_analysis", "mitigation",
                "priority", "timeline_impact_days", "evidence",
            ],
        },
    },
    "required": ["satisfied", "quality_assessment", "questions", "refined_risk"],
}
add_context_requests(RISK_REFINE_SCHEMA)


def build_refine_prompt(
    *,
    suggestion_type: str,
    current_draft: dict[str, str],
    existing_items: list[dict[str, str]],
    qa_history: list[dict[str, str]],
    round_number: int,
    max_rounds: int,
    project_context: dict[str, str] | None = None,
) -> str:
    """Assemble the user prompt for a refinement round.

    Args:
        suggestion_type: "risk" or "decision".
        current_draft: Current field values (title, background, etc.).
        existing_items: Existing risks/decisions for deduplication context.
        qa_history: List of {question, answer} dicts from prior rounds.
        round_number: Current round (1-based).
        max_rounds: Maximum allowed rounds.
        project_context: Optional project state summary for richer context.
    """
    parts: list[str] = []

    item_label = "Decision" if suggestion_type == "decision" else "Risk"
    parts.append(f"<refinement_round>Round {round_number} of {max_rounds}</refinement_round>")
    parts.append("")

    # Project context (helps the LLM understand the broader project state)
    if project_context:
        parts.append("<project_context>")
        for key in ["project_name", "goal", "charter_excerpt", "recent_meetings"]:
            val = project_context.get(key)
            if val:
                parts.append(val)
        parts.append("</project_context>")
        parts.append("")

    # Current draft
    parts.append(f"<current_draft type=\"{item_label.lower()}\">")
    for field_name in [
        "title", "background", "impact_analysis", "mitigation",
        "priority", "timeline_impact_days", "evidence",
    ]:
        value = current_draft.get(field_name, "")
        label = field_name.replace("_", " ").title()
        parts.append(f"{label}: {value}")
    parts.append("</current_draft>")
    parts.append("")

    # Existing items for dedup (with descriptions for semantic matching)
    if existing_items:
        parts.append(f"<existing_{item_label.lower()}s>")
        for item in existing_items:
            parts.append(f"<{item_label.lower()} key=\"{item.get('key', '?')}\" status=\"{item.get('status', '')}\">")
            parts.append(f"  Summary: {item.get('summary', '')}")
            if item.get("description"):
                parts.append(f"  Description: {item['description'][:200]}")
            if item.get("impact_analysis"):
                parts.append(f"  Impact: {item['impact_analysis'][:200]}")
            parts.append(f"</{item_label.lower()}>")
        parts.append(f"</existing_{item_label.lower()}s>")
        parts.append("")

    # Q&A history
    if qa_history:
        parts.append("<qa_history>")
        for i, qa in enumerate(qa_history, 1):
            parts.append(f"<qa_pair>")
            parts.append(f"Q{i}: {qa.get('question', '')}")
            parts.append(f"A{i}: {qa.get('answer', '')}")
            parts.append(f"</qa_pair>")
        parts.append("</qa_history>")
        parts.append("")

    # Final round instruction
    if round_number >= max_rounds:
        parts.append(
            "<final_round>This is the final round. You MUST set satisfied=true and "
            "return the best possible refined_risk with all available information. "
            "Do not ask further questions.</final_round>"
        )
        parts.append("")

    parts.append(
        f"<instructions>Evaluate this {item_label.lower()} draft against the quality criteria. "
        "If it meets all criteria, set satisfied=true and return the final version. "
        "If not, ask targeted questions (max 3-4) to fill the most important gaps, "
        "and return an improved refined_risk incorporating any information you can "
        "already infer or improve.</instructions>"
    )

    return "\n".join(parts)
