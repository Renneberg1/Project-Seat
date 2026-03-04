"""Risk/decision refinement service — iterative Q&A improvement loop."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.config import Settings, settings as default_settings
from src.jira_constants import FIELD_IMPACT_ANALYSIS, FIELD_MITIGATION_CONTROL, FIELD_TIMELINE_IMPACT
from src.models.transcript import (
    ProjectContext,
    SuggestionType,
    TranscriptSuggestion,
)
from src.services._transcript_helpers import build_preview, extract_adf_text, get_suggestion

logger = logging.getLogger(__name__)


class RiskRefinementService:
    """Iteratively refine transcript-extracted risks/decisions via LLM Q&A."""

    MAX_REFINE_ROUNDS = 5

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
    # Public API
    # ------------------------------------------------------------------

    async def start_risk_refinement(
        self, suggestion_id: int, project: Any
    ) -> dict[str, Any]:
        """Start iterative refinement for a risk/decision suggestion.

        Extracts the current draft from the suggestion payload, gathers
        dedup context, and runs round 1 of the refine agent.

        Returns the LLM result dict (satisfied, quality_assessment, questions, refined_risk).
        """
        from src.engine.agent import RiskRefineAgent, get_provider
        from src.services.transcript import TranscriptService

        sug = get_suggestion(self._db_path, suggestion_id)
        if sug is None:
            raise ValueError(f"Suggestion {suggestion_id} not found")
        if sug.suggestion_type not in (SuggestionType.RISK, SuggestionType.DECISION):
            raise ValueError("Refinement is only available for risk/decision suggestions")

        logger.info("Starting risk refinement for suggestion id=%s (type=%s)", suggestion_id, sug.suggestion_type.value)
        current_draft = self._extract_risk_draft(sug)

        transcript_svc = TranscriptService(db_path=self._db_path, settings=self._settings)
        context = await transcript_svc.gather_project_context(project)

        existing_items = (
            context.existing_risks
            if sug.suggestion_type == SuggestionType.RISK
            else context.existing_decisions
        )

        provider = get_provider(self._settings.llm)
        agent = RiskRefineAgent(provider)
        try:
            result = await agent.refine(
                suggestion_type=sug.suggestion_type.value,
                current_draft=current_draft,
                existing_items=existing_items,
                qa_history=[],
                round_number=1,
                max_rounds=self.MAX_REFINE_ROUNDS,
            )
        finally:
            await provider.close()

        return result

    async def continue_risk_refinement(
        self,
        suggestion_id: int,
        project: Any,
        risk_draft: dict[str, str],
        qa_history: list[dict[str, str]],
        round_number: int,
    ) -> dict[str, Any]:
        """Continue refinement with accumulated Q&A state.

        If round_number >= MAX_REFINE_ROUNDS, forces satisfaction with
        current draft (no LLM call).
        """
        from src.engine.agent import RiskRefineAgent, get_provider
        from src.services.transcript import TranscriptService

        sug = get_suggestion(self._db_path, suggestion_id)
        if sug is None:
            raise ValueError(f"Suggestion {suggestion_id} not found")

        logger.info("Continuing refinement for suggestion id=%s, round=%d/%d", suggestion_id, round_number, self.MAX_REFINE_ROUNDS)
        if round_number >= self.MAX_REFINE_ROUNDS:
            logger.info("Max refinement rounds reached for suggestion id=%s, finalising", suggestion_id)
            return {
                "satisfied": True,
                "quality_assessment": "Maximum refinement rounds reached. Finalising with current draft.",
                "questions": [],
                "refined_risk": risk_draft,
            }

        transcript_svc = TranscriptService(db_path=self._db_path, settings=self._settings)
        context = await transcript_svc.gather_project_context(project)
        existing_items = (
            context.existing_risks
            if sug.suggestion_type == SuggestionType.RISK
            else context.existing_decisions
        )

        provider = get_provider(self._settings.llm)
        agent = RiskRefineAgent(provider)
        try:
            result = await agent.refine(
                suggestion_type=sug.suggestion_type.value,
                current_draft=risk_draft,
                existing_items=existing_items,
                qa_history=qa_history,
                round_number=round_number,
                max_rounds=self.MAX_REFINE_ROUNDS,
            )
        finally:
            await provider.close()

        return result

    def apply_refinement(
        self,
        suggestion_id: int,
        refined_risk: dict[str, Any],
        context: ProjectContext | None = None,
    ) -> TranscriptSuggestion | None:
        """Apply a refined draft back to the suggestion row.

        Rebuilds the Jira payload from the refined fields and updates
        the suggestion in the DB.
        """
        from src.services.transcript import TranscriptService

        sug = get_suggestion(self._db_path, suggestion_id)
        if sug is None:
            return None

        # Rebuild payload using the transcript service's builder
        raw_sug = {
            "type": sug.suggestion_type.value,
            "title": refined_risk.get("title", sug.title),
            "background": refined_risk.get("background", ""),
            "impact_analysis": refined_risk.get("impact_analysis", ""),
            "mitigation": refined_risk.get("mitigation", ""),
            "priority": refined_risk.get("priority", "Medium"),
            "timeline_impact_days": refined_risk.get("timeline_impact_days", 0),
            "evidence": refined_risk.get("evidence", ""),
            "confidence": 1.0,
        }

        if context:
            transcript_svc = TranscriptService(db_path=self._db_path, settings=self._settings)
            payload = transcript_svc._build_jira_payload(raw_sug, context)
        else:
            # Rebuild from existing payload, updating summary + fields
            payload = json.loads(sug.proposed_payload)
            from src.engine.prompts.transcript import (
                build_adf_description,
                build_adf_decision_description,
                build_adf_field,
            )

            is_decision = sug.suggestion_type == SuggestionType.DECISION
            background = raw_sug["background"]
            evidence = raw_sug["evidence"]

            if is_decision:
                description = build_adf_decision_description(
                    background=background,
                    decision_text=raw_sug["title"],
                    evidence=evidence,
                )
            else:
                description = build_adf_description(
                    background=background,
                    evidence=evidence,
                )

            payload["summary"] = raw_sug["title"]
            fields = payload.setdefault("fields", {})
            fields["description"] = description
            fields["priority"] = {"name": raw_sug["priority"]}

            impact = raw_sug.get("impact_analysis", "")
            if impact:
                fields[FIELD_IMPACT_ANALYSIS] = build_adf_field(impact)
            mitigation = raw_sug.get("mitigation", "")
            if mitigation:
                fields[FIELD_MITIGATION_CONTROL] = build_adf_field(mitigation)
            timeline_days = raw_sug.get("timeline_impact_days")
            if timeline_days:
                fields[FIELD_TIMELINE_IMPACT] = timeline_days

        preview = build_preview(raw_sug, sug.suggestion_type)

        self._repo.update_suggestion_content(
            suggestion_id,
            title=raw_sug["title"],
            detail=raw_sug["background"],
            evidence=raw_sug["evidence"],
            proposed_payload=json.dumps(payload),
            proposed_preview=preview,
            confidence=1.0,
        )

        return get_suggestion(self._db_path, suggestion_id)

    def get_suggestion(self, suggestion_id: int) -> TranscriptSuggestion | None:
        """Public accessor for suggestion lookup."""
        return get_suggestion(self._db_path, suggestion_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_risk_draft(self, sug: TranscriptSuggestion) -> dict[str, str]:
        """Parse a suggestion's payload back into plain-text draft fields."""
        payload = json.loads(sug.proposed_payload)
        fields = payload.get("fields", {})

        # Extract description text
        description_adf = fields.get("description")
        background = extract_adf_text(description_adf) if description_adf else ""
        if not background:
            background = sug.detail or ""

        # Extract custom fields
        impact_analysis = extract_adf_text(fields.get(FIELD_IMPACT_ANALYSIS))
        mitigation = extract_adf_text(fields.get(FIELD_MITIGATION_CONTROL))

        priority_obj = fields.get("priority", {})
        priority = priority_obj.get("name", "Medium") if isinstance(priority_obj, dict) else "Medium"

        timeline_days = fields.get(FIELD_TIMELINE_IMPACT, 0)

        return {
            "title": sug.title,
            "background": background,
            "impact_analysis": impact_analysis,
            "mitigation": mitigation,
            "priority": priority,
            "timeline_impact_days": str(timeline_days or 0),
            "evidence": sug.evidence or "",
        }
