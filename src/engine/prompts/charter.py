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
1. Before asking any question, carefully read the <project_context> block. It already \
contains the Goal (with description), product ideas/features list, release/version, \
risks, decisions, initiatives, team progress, and XFT page content. Do NOT ask about \
anything that is already answered there (e.g. do not ask "what features?" when the \
features list is provided; do not ask about the project date when the Goal due date \
is given).
2. If you need data that isn't in <project_context> (e.g. stakeholder list on another \
Confluence page, a specific Jira ticket's details), issue a context_request instead of \
asking the user.
3. Only ask questions about information that is genuinely missing or unclear after \
considering the provided context AND any context_requests you would issue.
4. Each question must reference a specific Charter section.
5. If the user's input is already clear and complete for the sections it touches, \
return an empty questions list.
6. Ask at most 5 questions — focus on the most important gaps.
7. Do NOT ask about sections the user clearly did not intend to change.
8. """ + CONTEXT_REQUESTS_RULE + """
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
        "<instructions>\n"
        "Step A — Proactive discovery: before deciding what to ask, consider what "
        "additional Confluence/Jira content would help you update the Charter. Useful "
        "searches often include:\n"
        "  • confluence_search for the parent Program page (governance, stakeholders)\n"
        "  • confluence_search for '<project name> stakeholders' or '<project name> scope'\n"
        "  • confluence_search for related architecture, PRD, or strategy docs\n"
        "  • jira_issue for the Goal ticket if you need its full description\n"
        "  • jira_search for related Epics/Initiatives under this Goal\n"
        "If any such lookup would genuinely reduce the need to bother the user, add it "
        "to context_requests. Prefer context_requests over questions.\n"
        "\n"
        "Step B — Identify any gaps or ambiguities in the user's description that are "
        "not already answered by <project_context> and will not be answered by your "
        "context_requests. Ask only those as questions. If the input is clear and "
        "complete after context, return an empty questions list.\n"
        "</instructions>"
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
8. **People references — ALWAYS use @FirstName LastName syntax** whenever you write \
a person's name in proposed_text. This applies both when (a) preserving a name that \
already appears in the current section (e.g. you see "@Alicia Miller" — keep it as \
"@Alicia Miller"), and (b) introducing a new person the user mentioned in plain \
prose (e.g. user says "Add John Smith as PM" — write "@John Smith", not "John \
Smith"). The `@` prefix is what triggers Confluence to render an interactive user \
mention; plain-text names will publish as dead text with no link.
9. If the current section content already contains user mentions in the form \
"@FirstName LastName" (resolved from Confluence storage format), those are real \
Atlassian accounts — never drop or paraphrase them away unless the user explicitly \
asks you to remove or replace that person.
10. **Page references — use [page: Exact Title] syntax** when referring to another \
Confluence page (e.g. a stakeholder roster, architecture doc, program page). Use \
the exact page title you have seen in <project_context> or a successful \
confluence_search result. These placeholders are auto-converted to real Confluence \
page links on publish. Do NOT invent titles — if you are not sure a page exists, \
issue a confluence_search first or just refer to it in prose without the [page:...] \
syntax.
11. """ + CONTEXT_REQUESTS_RULE + """
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
        "<instructions>\n"
        "Before proposing edits, if you still need factual data that is not in "
        "<project_context> or the Q&A (e.g. a stakeholder list on another Confluence "
        "page, details of a referenced Jira ticket), issue context_requests — they "
        "will be resolved and the analysis re-run with the extra data. Prefer searching "
        "over guessing.\n"
        "\n"
        "Then, based on the user's description, Q&A answers, and all available "
        "context, propose precise section edits. Each edit must use the exact section "
        "name from the Charter.\n"
        "</instructions>"
    )

    return "\n".join(parts)
