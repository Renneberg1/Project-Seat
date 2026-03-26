"""Charter update prompt templates and schema definitions.

Two-step LLM interaction:
1. **Questions**: LLM identifies gaps/ambiguities in the user's description
   relative to the Charter sections.
2. **Edits**: LLM proposes precise section replacements given the user's
   description plus their answers to clarifying questions.
"""

from __future__ import annotations

from typing import Any

from src.engine.prompts import CONTEXT_REQUESTS_RULE, add_context_requests


# ------------------------------------------------------------------
# Step 1: Questions prompt
# ------------------------------------------------------------------

QUESTIONS_SYSTEM_PROMPT = """\
<role>You are a project management analyst for a medical device software engineering team. \
You are helping the user update their Project Charter — a structured document with \
sections like Project Name, Date, Project Manager, Executive Sponsor, Status, \
OKR alignment, Commercial Objective, Project Scope (In Scope / Out of Scope), \
Commercial Driver, Success Criteria, and Stakeholders.</role>

<context>The user has provided free-form text describing changes they want to make. Your job \
is to identify any gaps or ambiguities in their description that would prevent you \
from writing precise, complete section updates.</context>

<rules>
1. Only ask questions about information that is genuinely missing or unclear.
2. Each question must reference a specific Charter section.
3. If the user's input is already clear and complete for the sections it touches, \
return an empty questions list.
4. Ask at most 5 questions — focus on the most important gaps.
5. Do NOT ask about sections the user clearly did not intend to change.
6. """ + CONTEXT_REQUESTS_RULE + """
</rules>
"""

CHARTER_QUESTIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The clarifying question to ask the user",
                    },
                    "section_name": {
                        "type": "string",
                        "description": "Which Charter section this question relates to",
                    },
                    "why_needed": {
                        "type": "string",
                        "description": "Brief explanation of why this information is needed",
                    },
                },
                "required": ["question", "section_name", "why_needed"],
            },
        },
    },
    "required": ["questions"],
}
add_context_requests(CHARTER_QUESTIONS_SCHEMA)


def build_questions_prompt(
    current_sections: list[dict[str, str]],
    user_input: str,
    project_context: dict[str, str] | None = None,
) -> str:
    """Build the user prompt for the questions step.

    Args:
        current_sections: List of {name, content} dicts from extract_sections().
        user_input: The user's free-form description of desired changes.
        project_context: Optional dict with project_name, jira_goal_key, etc.
    """
    parts: list[str] = []

    if project_context:
        parts.append(f"<project_context>")
        parts.append(f"Project: {project_context.get('project_name', 'Unknown')}")
        project_state = project_context.get("project_state")
        if project_state:
            parts.append(project_state)
        parts.append(f"</project_context>")
        parts.append("")

    parts.append("<current_charter_sections>")
    for section in current_sections:
        parts.append(f"<section name=\"{section['name']}\">")
        parts.append(section["content"])
        parts.append("</section>")
    parts.append("</current_charter_sections>")
    parts.append("")

    parts.append("<requested_changes>")
    parts.append(user_input)
    parts.append("</requested_changes>")
    parts.append("")

    parts.append(
        "<instructions>Identify any gaps or ambiguities in the user's description. "
        "If the input is already clear and complete, return an empty questions list.</instructions>"
    )

    return "\n".join(parts)


# ------------------------------------------------------------------
# Step 2: Edits prompt
# ------------------------------------------------------------------

EDITS_SYSTEM_PROMPT = """\
<role>You are a project management analyst for a medical device software engineering team. \
You are proposing precise edits to a Project Charter based on the user's description \
and their answers to clarifying questions.</role>

<context>The Charter has structured sections (e.g. Project Name, Commercial Objective, \
Project Scope — In Scope, Project Scope — Out of Scope, Success Criteria, \
Stakeholders, etc.). You must propose replacement text for specific sections.</context>

<rules>
1. Only propose edits for sections that need to change based on the user's input.
2. The proposed_text should be the COMPLETE new content for that section — it will \
replace the existing content entirely.
3. Preserve any existing information in the section that the user did not ask to change. \
Merge the new information with the existing content.
4. Keep the writing style professional and consistent with existing Charter content.
5. Assign a confidence score (0.0-1.0) based on how certain you are the edit is correct.
6. Include a brief rationale explaining why this edit is appropriate.
7. The proposed text will be published directly to a Confluence Charter page visible to \
stakeholders, leadership, and the project team. Write with clarity, precision, and a \
professional tone appropriate for a formal project document. Structure content into clear \
paragraphs (separated by newlines). Avoid jargon unless it is standard medical device or \
project management terminology.
8. If the user's input references people with @Name syntax (e.g. @Alice Smith), \
preserve the @ prefix in your proposed text.
9. """ + CONTEXT_REQUESTS_RULE + """
</rules>
"""

CHARTER_EDITS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Brief summary of all proposed changes (1-2 sentences)",
        },
        "section_edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section_name": {
                        "type": "string",
                        "description": "Exact section name from the Charter (e.g. 'Commercial Objective', 'Project Scope — In Scope')",
                    },
                    "proposed_text": {
                        "type": "string",
                        "description": "Complete replacement text for this section. This will be published directly to a Confluence Charter page — write clearly, professionally, and with good paragraph structure (use newlines between paragraphs).",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Brief explanation of why this edit is proposed",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "0.0-1.0 confidence score",
                    },
                },
                "required": ["section_name", "proposed_text", "rationale", "confidence"],
            },
        },
    },
    "required": ["summary", "section_edits"],
}
add_context_requests(CHARTER_EDITS_SCHEMA)


def build_edits_prompt(
    current_sections: list[dict[str, str]],
    user_input: str,
    qa_pairs: list[dict[str, str]],
    project_context: dict[str, str] | None = None,
) -> str:
    """Build the user prompt for the edits step.

    Args:
        current_sections: List of {name, content} dicts from extract_sections().
        user_input: The user's original free-form description.
        qa_pairs: List of {question, answer} dicts from the Q&A step.
        project_context: Optional dict with project_name, jira_goal_key, etc.
    """
    parts: list[str] = []

    if project_context:
        parts.append(f"<project_context>")
        parts.append(f"Project: {project_context.get('project_name', 'Unknown')}")
        project_state = project_context.get("project_state")
        if project_state:
            parts.append(project_state)
        parts.append(f"</project_context>")
        parts.append("")

    parts.append("<current_charter_sections>")
    for section in current_sections:
        parts.append(f"<section name=\"{section['name']}\">")
        parts.append(section["content"])
        parts.append("</section>")
    parts.append("</current_charter_sections>")
    parts.append("")

    parts.append("<requested_changes>")
    parts.append(user_input)
    parts.append("</requested_changes>")
    parts.append("")

    if qa_pairs:
        parts.append("<clarifying_qa>")
        for i, qa in enumerate(qa_pairs, 1):
            parts.append(f"<qa_pair>")
            parts.append(f"Q{i}: {qa['question']}")
            parts.append(f"A{i}: {qa['answer']}")
            parts.append(f"</qa_pair>")
        parts.append("</clarifying_qa>")
        parts.append("")

    parts.append(
        "<instructions>Based on the user's description and Q&A answers above, propose precise "
        "section edits. Each edit must use the exact section name from the Charter.</instructions>"
    )

    return "\n".join(parts)
