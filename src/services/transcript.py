"""Transcript service — storage, LLM analysis, and suggestion management."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.config import Settings, settings as default_settings
from src.connectors.jira import JiraConnector
from src.engine.mentions import resolve_adf_doc_mentions, resolve_confluence_mentions
from src.models.transcript import (
    ParsedTranscript,
    ProjectContext,
    SuggestionStatus,
    SuggestionType,
    TranscriptRecord,
    TranscriptSuggestion,
)
from src.services._transcript_helpers import build_preview, extract_adf_text, get_suggestion as _get_suggestion_by_id
from src.services.transcript_parser import TranscriptParser  # noqa: F401 — re-export

logger = logging.getLogger(__name__)


class TranscriptService:
    """Manage transcript storage and analysis."""

    def __init__(
        self,
        db_path: str | None = None,
        settings: Settings | None = None,
        transcript_repo: "TranscriptRepository | None" = None,
    ) -> None:
        self._settings = settings or default_settings
        self._db_path = db_path or self._settings.db_path

        from src.repositories.transcript_repo import TranscriptRepository
        self._repo = transcript_repo or TranscriptRepository(self._db_path)

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def store_transcript(self, project_id: int, parsed: ParsedTranscript) -> int:
        """Save a parsed transcript to transcript_cache. Returns the record ID."""
        processed = json.dumps({
            "segments": [
                {
                    "speaker": s.speaker,
                    "text": s.text,
                    "timestamp_start": s.timestamp_start,
                    "timestamp_end": s.timestamp_end,
                }
                for s in parsed.segments
            ],
            "speaker_list": parsed.speaker_list,
            "duration_hint": parsed.duration_hint,
        })
        return self._repo.insert_transcript(project_id, parsed.filename, parsed.raw_text, processed)

    def list_transcripts(self, project_id: int) -> list[TranscriptRecord]:
        """List all transcripts for a project, newest first."""
        return self._repo.list_transcripts(project_id)

    def get_transcript(self, transcript_id: int) -> TranscriptRecord | None:
        """Fetch a single transcript by ID."""
        return self._repo.get_transcript(transcript_id)

    def delete_transcript(self, transcript_id: int) -> None:
        """Delete a transcript and its suggestions."""
        self._repo.delete_transcript(transcript_id)

    # ------------------------------------------------------------------
    # Project context gathering
    # ------------------------------------------------------------------

    async def gather_project_context(self, project: Any) -> ProjectContext:
        """Fetch existing risks, decisions, and Confluence page content in parallel."""
        from src.services.project_context import ProjectContextService

        ctx_service = ProjectContextService(
            db_path=self._db_path, settings=self._settings,
        )
        data = await ctx_service.gather(
            project,
            risks=True, decisions=True,
            charter=True, xft=True,
            goal_metadata=True,
        )

        default_label = data.goal_labels[0] if data.goal_labels else None
        default_component = data.goal_components[0] if data.goal_components else None

        return ProjectContext(
            project_name=project.name,
            jira_goal_key=project.jira_goal_key,
            existing_risks=data.existing_risks,
            existing_decisions=data.existing_decisions,
            charter_content=data.charter_content,
            xft_content=data.xft_content,
            default_component=default_component,
            default_label=default_label,
        )

    # ------------------------------------------------------------------
    # LLM Analysis
    # ------------------------------------------------------------------

    async def analyze_transcript(
        self, transcript_id: int, project: Any
    ) -> list[TranscriptSuggestion]:
        """Run LLM analysis on a transcript and store suggestions."""
        from src.engine.agent import TranscriptAgent, get_provider

        record = self.get_transcript(transcript_id)
        if record is None:
            raise ValueError(f"Transcript {transcript_id} not found")

        context = await self.gather_project_context(project)

        provider = get_provider(self._settings.llm)
        agent = TranscriptAgent(provider)
        try:
            result = await agent.analyze_transcript(
                transcript_text=record.raw_text,
                project_context={
                    "project_name": context.project_name,
                    "jira_goal_key": context.jira_goal_key,
                    "existing_risks": context.existing_risks,
                    "existing_decisions": context.existing_decisions,
                    "charter_content": context.charter_content,
                    "xft_content": context.xft_content,
                },
            )
        finally:
            await provider.close()

        # Store meeting summary
        summary = result.get("meeting_summary", "")
        self._repo.update_meeting_summary(transcript_id, summary)

        # Clear old suggestions for re-analysis
        self._repo.delete_suggestions(transcript_id)

        # Store new suggestions
        suggestions: list[TranscriptSuggestion] = []
        for raw_sug in result.get("suggestions", []):
            sug_type = raw_sug.get("type", "risk")
            try:
                stype = SuggestionType(sug_type)
            except ValueError:
                continue

            if stype in (SuggestionType.RISK, SuggestionType.DECISION):
                payload = self._build_jira_payload(raw_sug, context)
                action = "create_jira_issue"
            elif stype in (SuggestionType.XFT_UPDATE, SuggestionType.CHARTER_UPDATE):
                payload = self._build_confluence_payload(raw_sug, context, project)
                action = "update_confluence_page"
            else:
                continue

            detail = raw_sug.get("background", "") or raw_sug.get("confluence_content", "")
            preview = build_preview(raw_sug, stype)

            sug_id = self._repo.insert_suggestion(
                transcript_id=transcript_id,
                project_id=project.id,
                suggestion_type=stype.value,
                title=raw_sug.get("title", "Untitled"),
                detail=detail,
                evidence=raw_sug.get("evidence", ""),
                proposed_payload=json.dumps(payload),
                proposed_action=action,
                proposed_preview=preview,
                confidence=raw_sug.get("confidence", 0.5),
                status=SuggestionStatus.PENDING.value,
            )

            sug = self._get_suggestion(sug_id)
            if sug:
                suggestions.append(sug)

        return suggestions

    # ------------------------------------------------------------------
    # Suggestion CRUD
    # ------------------------------------------------------------------

    def list_suggestions(self, transcript_id: int) -> list[TranscriptSuggestion]:
        """List all suggestions for a transcript."""
        return self._repo.list_suggestions(transcript_id)

    def _get_suggestion(self, suggestion_id: int) -> TranscriptSuggestion | None:
        return self._repo.get_suggestion(suggestion_id)

    def get_suggestion(self, suggestion_id: int) -> TranscriptSuggestion | None:
        return self._get_suggestion(suggestion_id)

    def get_transcript_summary(self, project_id: int) -> dict[str, Any]:
        """Return a summary of transcript activity for the dashboard."""
        return self._repo.get_transcript_summary(project_id)

    # ------------------------------------------------------------------
    # Accept / Reject
    # ------------------------------------------------------------------

    async def accept_suggestion(
        self, suggestion_id: int, project: Any
    ) -> TranscriptSuggestion | None:
        """Accept a suggestion and queue it in the approval engine.

        Refreshes payload fields from current project data so that fixes
        to goal key or Confluence page IDs take effect without re-analysis.
        Resolves @mentions in payloads to native Atlassian markup.
        """
        from src.engine.approval import ApprovalEngine
        from src.models.approval import ApprovalAction

        sug = self._get_suggestion(suggestion_id)
        if sug is None or sug.status != SuggestionStatus.PENDING:
            return sug

        payload = json.loads(sug.proposed_payload)

        # Patch payload with current project data
        if sug.proposed_action == "create_jira_issue":
            if not project.jira_goal_key or project.jira_goal_key == "pending":
                raise ValueError(
                    f"Cannot accept: project Goal key is '{project.jira_goal_key}'. "
                    "Complete the project spin-up first."
                )
            payload.setdefault("fields", {})["parent"] = {"key": project.jira_goal_key}
            payload["fields"]["fixVersions"] = [{"name": project.name}]

            # Resolve @mentions in ADF fields
            jira = JiraConnector()
            try:
                fields = payload.get("fields", {})
                if fields.get("description"):
                    fields["description"] = await resolve_adf_doc_mentions(
                        fields["description"], jira
                    )
                if fields.get("customfield_11166"):
                    fields["customfield_11166"] = await resolve_adf_doc_mentions(
                        fields["customfield_11166"], jira
                    )
                if fields.get("customfield_11342"):
                    fields["customfield_11342"] = await resolve_adf_doc_mentions(
                        fields["customfield_11342"], jira
                    )
            finally:
                await jira.close()

        elif sug.proposed_action == "update_confluence_page":
            # Determine correct page ID from suggestion type
            if sug.suggestion_type == SuggestionType.XFT_UPDATE:
                page_id = project.confluence_xft_id
            else:
                page_id = project.confluence_charter_id
            if not page_id:
                raise ValueError(
                    "Cannot accept: project has no Confluence page configured. "
                    "Set Charter/XFT page IDs first."
                )
            payload["page_id"] = page_id

            # Resolve @mentions in Confluence append content
            append_content = payload.get("append_content", "")
            if append_content:
                jira = JiraConnector()
                try:
                    payload["append_content"] = await resolve_confluence_mentions(
                        append_content, jira
                    )
                finally:
                    await jira.close()

        action_map = {
            "create_jira_issue": ApprovalAction.CREATE_JIRA_ISSUE,
            "update_confluence_page": ApprovalAction.UPDATE_CONFLUENCE_PAGE,
        }
        action = action_map.get(sug.proposed_action)
        if action is None:
            return sug

        engine = ApprovalEngine(db_path=self._db_path)
        item_id = engine.propose(
            action_type=action,
            payload=payload,
            preview=sug.proposed_preview,
            context=f"From transcript suggestion #{sug.id}: {sug.title}",
            project_id=sug.project_id,
        )

        self._repo.update_suggestion_status(suggestion_id, SuggestionStatus.QUEUED.value, item_id)

        return self._get_suggestion(suggestion_id)

    def reject_suggestion(self, suggestion_id: int) -> TranscriptSuggestion | None:
        """Reject a suggestion."""
        self._repo.update_suggestion_status(suggestion_id, SuggestionStatus.REJECTED.value)
        return self._get_suggestion(suggestion_id)

    async def accept_all_suggestions(
        self, transcript_id: int, project: Any
    ) -> list[int]:
        """Accept all pending suggestions for a transcript. Returns approval item IDs."""
        suggestions = self.list_suggestions(transcript_id)
        item_ids: list[int] = []
        for sug in suggestions:
            if sug.status == SuggestionStatus.PENDING:
                result = await self.accept_suggestion(sug.id, project)
                if result and result.approval_item_id:
                    item_ids.append(result.approval_item_id)
        return item_ids

    # ------------------------------------------------------------------
    # Payload builders
    # ------------------------------------------------------------------

    def _build_jira_payload(
        self, suggestion: dict[str, Any], context: ProjectContext
    ) -> dict[str, Any]:
        """Convert an LLM suggestion into a full Jira CREATE_JIRA_ISSUE payload."""
        from src.engine.prompts.transcript import (
            build_adf_description,
            build_adf_decision_description,
            build_adf_field,
        )

        sug_type = suggestion.get("type", "risk")
        is_decision = sug_type == "decision"

        issue_type_id = "12499" if is_decision else "10832"

        background = suggestion.get("background", "")
        evidence = suggestion.get("evidence", "")

        if is_decision:
            description = build_adf_decision_description(
                background=background,
                decision_text=suggestion.get("title", ""),
                evidence=evidence,
            )
        else:
            description = build_adf_description(
                background=background,
                evidence=evidence,
            )

        fields: dict[str, Any] = {
            "parent": {"key": context.jira_goal_key},
            "description": description,
            "priority": {"name": suggestion.get("priority", "Medium")},
        }

        if context.default_component:
            fields["components"] = [{"name": context.default_component}]
        if context.default_label:
            fields["labels"] = [context.default_label]

        fields["fixVersions"] = [{"name": context.project_name}]

        # Impact Analysis (customfield_11166)
        impact = suggestion.get("impact_analysis", "")
        if impact:
            fields["customfield_11166"] = build_adf_field(impact)

        # Mitigation/Control (customfield_11342)
        mitigation = suggestion.get("mitigation", "")
        if mitigation:
            fields["customfield_11342"] = build_adf_field(mitigation)

        # Timeline Impact (customfield_13267)
        timeline_days = suggestion.get("timeline_impact_days")
        if timeline_days:
            fields["customfield_13267"] = timeline_days

        return {
            "project_key": "RISK",
            "issue_type_id": issue_type_id,
            "summary": suggestion.get("title", "Untitled"),
            "fields": fields,
        }

    def _build_confluence_payload(
        self,
        suggestion: dict[str, Any],
        context: ProjectContext,
        project: Any,
    ) -> dict[str, Any]:
        """Convert an LLM suggestion into an UPDATE_CONFLUENCE_PAGE payload."""
        sug_type = suggestion.get("type", "xft_update")
        is_xft = sug_type == "xft_update"

        page_id = project.confluence_xft_id if is_xft else project.confluence_charter_id

        section_title = suggestion.get("confluence_section_title", "Meeting Notes")
        content = suggestion.get("confluence_content", suggestion.get("background", ""))

        # Build storage-format HTML for the new section
        from datetime import date
        from html import escape as _html_escape
        today = date.today().isoformat()
        escaped = _html_escape(content, quote=True)
        # Wrap each paragraph (newline-separated) in its own <p> tag
        paragraphs = [line.strip() for line in escaped.split("\n") if line.strip()]
        body_html = "".join(f"<p>{p}</p>" for p in paragraphs) if paragraphs else f"<p>{escaped}</p>"
        append_html = f"<h2>{section_title} — {today}</h2>{body_html}"

        return {
            "page_id": page_id,
            "title": None,  # Will be resolved at execution time
            "append_mode": True,
            "append_content": append_html,
        }
