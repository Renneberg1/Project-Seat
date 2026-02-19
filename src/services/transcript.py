"""Transcript service — parsing, storage, LLM analysis, and suggestion management."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from io import BytesIO
from typing import Any

from src.config import Settings, settings as default_settings
from src.connectors.base import ConnectorError
from src.database import get_db
from src.models.transcript import (
    ParsedTranscript,
    ProjectContext,
    SuggestionStatus,
    SuggestionType,
    TranscriptRecord,
    TranscriptSegment,
    TranscriptSuggestion,
)

logger = logging.getLogger(__name__)


class TranscriptParser:
    """Parse meeting transcripts from various file formats."""

    def parse(self, filename: str, content: bytes) -> ParsedTranscript:
        """Route to the appropriate parser based on file extension."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext == "vtt":
            return self._parse_vtt(filename, content)
        elif ext == "txt":
            return self._parse_txt(filename, content)
        elif ext == "docx":
            return self._parse_docx(filename, content)
        else:
            raise ValueError(f"Unsupported file format: .{ext}. Use .vtt, .txt, or .docx")

    def _parse_vtt(self, filename: str, content: bytes) -> ParsedTranscript:
        """Parse WebVTT with <v Name> speaker tags and timestamp blocks."""
        text = content.decode("utf-8-sig", errors="replace")
        segments: list[TranscriptSegment] = []
        speakers: set[str] = set()

        # Split into blocks separated by blank lines
        blocks = re.split(r"\n\s*\n", text)
        timestamp_re = re.compile(
            r"(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})"
        )
        speaker_re = re.compile(r"<v\s+([^>]+)>(.+?)(?:</v>|$)", re.DOTALL)

        for block in blocks:
            lines = block.strip().split("\n")
            if not lines:
                continue

            ts_start = ts_end = None
            speech_lines: list[str] = []

            for line in lines:
                ts_match = timestamp_re.search(line)
                if ts_match:
                    ts_start, ts_end = ts_match.group(1), ts_match.group(2)
                    continue
                # Skip WEBVTT header and sequence numbers
                if line.strip().startswith("WEBVTT") or line.strip().isdigit():
                    continue
                if line.strip():
                    speech_lines.append(line.strip())

            if not speech_lines:
                continue

            full_text = " ".join(speech_lines)

            # Try to extract speaker from <v Name> tags
            speaker_match = speaker_re.search(full_text)
            if speaker_match:
                speaker = speaker_match.group(1).strip()
                spoken = speaker_re.sub(r"\2", full_text).strip()
            else:
                speaker = "Unknown"
                spoken = full_text

            speakers.add(speaker)
            segments.append(TranscriptSegment(
                speaker=speaker,
                text=spoken,
                timestamp_start=ts_start,
                timestamp_end=ts_end,
            ))

        raw = "\n".join(f"{s.speaker}: {s.text}" for s in segments)
        duration = None
        if segments and segments[-1].timestamp_end:
            duration = segments[-1].timestamp_end

        return ParsedTranscript(
            filename=filename,
            segments=segments,
            raw_text=raw,
            speaker_list=sorted(speakers),
            duration_hint=duration,
        )

    def _parse_txt(self, filename: str, content: bytes) -> ParsedTranscript:
        """Parse plain text with 'Name: text' speaker prefixes."""
        text = content.decode("utf-8-sig", errors="replace")
        segments: list[TranscriptSegment] = []
        speakers: set[str] = set()

        speaker_line_re = re.compile(r"^([A-Za-z][A-Za-z .'-]{0,40}):\s+(.+)$")

        current_speaker = "Unknown"
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            match = speaker_line_re.match(line)
            if match:
                current_speaker = match.group(1).strip()
                spoken = match.group(2).strip()
            else:
                spoken = line

            speakers.add(current_speaker)
            segments.append(TranscriptSegment(speaker=current_speaker, text=spoken))

        raw = "\n".join(f"{s.speaker}: {s.text}" for s in segments)
        return ParsedTranscript(
            filename=filename,
            segments=segments,
            raw_text=raw,
            speaker_list=sorted(speakers),
        )

    def _parse_docx(self, filename: str, content: bytes) -> ParsedTranscript:
        """Extract paragraph text via python-docx."""
        try:
            from docx import Document
        except ImportError:
            raise ImportError(
                "python-docx is required for .docx parsing. "
                "Install with: uv add python-docx"
            )

        doc = Document(BytesIO(content))
        segments: list[TranscriptSegment] = []
        speakers: set[str] = set()

        speaker_line_re = re.compile(r"^([A-Za-z][A-Za-z .'-]{0,40}):\s+(.+)$")
        current_speaker = "Unknown"

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            match = speaker_line_re.match(text)
            if match:
                current_speaker = match.group(1).strip()
                spoken = match.group(2).strip()
            else:
                spoken = text

            speakers.add(current_speaker)
            segments.append(TranscriptSegment(speaker=current_speaker, text=spoken))

        raw = "\n".join(f"{s.speaker}: {s.text}" for s in segments)
        return ParsedTranscript(
            filename=filename,
            segments=segments,
            raw_text=raw,
            speaker_list=sorted(speakers),
        )


class TranscriptService:
    """Manage transcript storage and analysis."""

    def __init__(
        self,
        db_path: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or default_settings
        self._db_path = db_path or self._settings.db_path

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
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO transcript_cache
                   (project_id, filename, raw_text, processed_json)
                   VALUES (?, ?, ?, ?)""",
                (project_id, parsed.filename, parsed.raw_text, processed),
            )
            conn.commit()
            return cursor.lastrowid

    def list_transcripts(self, project_id: int) -> list[TranscriptRecord]:
        """List all transcripts for a project, newest first."""
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM transcript_cache WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [TranscriptRecord.from_row(r) for r in rows]

    def get_transcript(self, transcript_id: int) -> TranscriptRecord | None:
        """Fetch a single transcript by ID."""
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM transcript_cache WHERE id = ?",
                (transcript_id,),
            ).fetchone()
        return TranscriptRecord.from_row(row) if row else None

    def delete_transcript(self, transcript_id: int) -> None:
        """Delete a transcript and its suggestions."""
        with get_db(self._db_path) as conn:
            conn.execute(
                "DELETE FROM transcript_suggestions WHERE transcript_id = ?",
                (transcript_id,),
            )
            conn.execute(
                "DELETE FROM transcript_cache WHERE id = ?",
                (transcript_id,),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Project context gathering
    # ------------------------------------------------------------------

    async def gather_project_context(self, project: Any) -> ProjectContext:
        """Fetch existing risks, decisions, and Confluence page content in parallel."""
        from src.connectors.jira import JiraConnector
        from src.connectors.confluence import ConfluenceConnector

        jira = JiraConnector(settings=self._settings)
        confluence = ConfluenceConnector(settings=self._settings)

        async def _fetch_risks() -> list[dict[str, str]]:
            try:
                raw = await jira.search(
                    f'project = RISK AND issuetype = Risk AND fixVersion = "{project.name}"',
                    fields=["summary", "status"],
                )
                return [
                    {
                        "key": r.get("key", ""),
                        "summary": r.get("fields", {}).get("summary", ""),
                        "status": r.get("fields", {}).get("status", {}).get("name", ""),
                    }
                    for r in raw
                ]
            except ConnectorError:
                return []

        async def _fetch_decisions() -> list[dict[str, str]]:
            try:
                raw = await jira.search(
                    f'project = RISK AND issuetype = "Project Issue" AND fixVersion = "{project.name}"',
                    fields=["summary", "status"],
                )
                return [
                    {
                        "key": r.get("key", ""),
                        "summary": r.get("fields", {}).get("summary", ""),
                        "status": r.get("fields", {}).get("status", {}).get("name", ""),
                    }
                    for r in raw
                ]
            except ConnectorError:
                return []

        async def _fetch_page_body(page_id: str | None) -> str | None:
            if not page_id:
                return None
            try:
                data = await confluence.get_page(page_id, expand=["body.storage"])
                return data.get("body", {}).get("storage", {}).get("value", "")
            except ConnectorError:
                return None

        try:
            risks, decisions, charter, xft = await asyncio.gather(
                _fetch_risks(),
                _fetch_decisions(),
                _fetch_page_body(project.confluence_charter_id),
                _fetch_page_body(project.confluence_xft_id),
            )
        finally:
            await jira.close()
            await confluence.close()

        # Try to extract component/label from Goal ticket labels
        default_label = None
        default_component = None
        try:
            goal = await JiraConnector(settings=self._settings).get_issue(
                project.jira_goal_key, fields=["labels", "components"]
            )
            labels = goal.get("fields", {}).get("labels", [])
            if labels:
                default_label = labels[0]
            components = goal.get("fields", {}).get("components", [])
            if components:
                default_component = components[0].get("name")
        except (ConnectorError, Exception):
            pass

        return ProjectContext(
            project_name=project.name,
            jira_goal_key=project.jira_goal_key,
            existing_risks=risks,
            existing_decisions=decisions,
            charter_content=charter,
            xft_content=xft,
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
        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE transcript_cache SET meeting_summary = ? WHERE id = ?",
                (summary, transcript_id),
            )
            conn.commit()

        # Clear old suggestions for re-analysis
        with get_db(self._db_path) as conn:
            conn.execute(
                "DELETE FROM transcript_suggestions WHERE transcript_id = ?",
                (transcript_id,),
            )
            conn.commit()

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
            preview = self._build_preview(raw_sug, stype)

            with get_db(self._db_path) as conn:
                cursor = conn.execute(
                    """INSERT INTO transcript_suggestions
                       (transcript_id, project_id, suggestion_type, title, detail,
                        evidence, proposed_payload, proposed_action, proposed_preview,
                        confidence, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        transcript_id,
                        project.id,
                        stype.value,
                        raw_sug.get("title", "Untitled"),
                        detail,
                        raw_sug.get("evidence", ""),
                        json.dumps(payload),
                        action,
                        preview,
                        raw_sug.get("confidence", 0.5),
                        SuggestionStatus.PENDING.value,
                    ),
                )
                conn.commit()
                sug_id = cursor.lastrowid

            sug = self._get_suggestion(sug_id)
            if sug:
                suggestions.append(sug)

        return suggestions

    # ------------------------------------------------------------------
    # Suggestion CRUD
    # ------------------------------------------------------------------

    def list_suggestions(self, transcript_id: int) -> list[TranscriptSuggestion]:
        """List all suggestions for a transcript."""
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM transcript_suggestions WHERE transcript_id = ? ORDER BY id",
                (transcript_id,),
            ).fetchall()
        return [TranscriptSuggestion.from_row(r) for r in rows]

    def _get_suggestion(self, suggestion_id: int) -> TranscriptSuggestion | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM transcript_suggestions WHERE id = ?",
                (suggestion_id,),
            ).fetchone()
        return TranscriptSuggestion.from_row(row) if row else None

    def get_suggestion(self, suggestion_id: int) -> TranscriptSuggestion | None:
        return self._get_suggestion(suggestion_id)

    def get_transcript_summary(self, project_id: int) -> dict[str, Any]:
        """Return a summary of transcript activity for the dashboard."""
        with get_db(self._db_path) as conn:
            transcript_count = conn.execute(
                "SELECT COUNT(*) FROM transcript_cache WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
            suggestion_count = conn.execute(
                "SELECT COUNT(*) FROM transcript_suggestions WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
            pending_count = conn.execute(
                "SELECT COUNT(*) FROM transcript_suggestions WHERE project_id = ? AND status = ?",
                (project_id, SuggestionStatus.PENDING.value),
            ).fetchone()[0]
        return {
            "transcript_count": transcript_count,
            "suggestion_count": suggestion_count,
            "pending_count": pending_count,
        }

    # ------------------------------------------------------------------
    # Accept / Reject
    # ------------------------------------------------------------------

    def accept_suggestion(
        self, suggestion_id: int, project: Any
    ) -> TranscriptSuggestion | None:
        """Accept a suggestion and queue it in the approval engine.

        Refreshes payload fields from current project data so that fixes
        to goal key or Confluence page IDs take effect without re-analysis.
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

        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE transcript_suggestions SET status = ?, approval_item_id = ? WHERE id = ?",
                (SuggestionStatus.QUEUED.value, item_id, suggestion_id),
            )
            conn.commit()

        return self._get_suggestion(suggestion_id)

    def reject_suggestion(self, suggestion_id: int) -> TranscriptSuggestion | None:
        """Reject a suggestion."""
        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE transcript_suggestions SET status = ? WHERE id = ?",
                (SuggestionStatus.REJECTED.value, suggestion_id),
            )
            conn.commit()
        return self._get_suggestion(suggestion_id)

    def accept_all_suggestions(
        self, transcript_id: int, project: Any
    ) -> list[int]:
        """Accept all pending suggestions for a transcript. Returns approval item IDs."""
        suggestions = self.list_suggestions(transcript_id)
        item_ids: list[int] = []
        for sug in suggestions:
            if sug.status == SuggestionStatus.PENDING:
                result = self.accept_suggestion(sug.id, project)
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
        today = date.today().isoformat()
        append_html = (
            f"<h2>{section_title} — {today}</h2>"
            f"<p>{content}</p>"
        )

        return {
            "page_id": page_id,
            "title": None,  # Will be resolved at execution time
            "append_mode": True,
            "append_content": append_html,
        }

    def _build_preview(self, suggestion: dict[str, Any], stype: SuggestionType) -> str:
        """Build a human-readable preview string for a suggestion."""
        lines: list[str] = []
        lines.append(f"Type: {stype.value}")
        lines.append(f"Title: {suggestion.get('title', 'Untitled')}")
        if suggestion.get("priority"):
            lines.append(f"Priority: {suggestion['priority']}")
        if suggestion.get("confidence"):
            lines.append(f"Confidence: {suggestion['confidence']:.0%}")
        if suggestion.get("background"):
            lines.append(f"Background: {suggestion['background'][:200]}")
        if suggestion.get("evidence"):
            lines.append(f"Evidence: {suggestion['evidence'][:200]}")
        return "\n".join(lines)
