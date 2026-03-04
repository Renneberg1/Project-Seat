"""Tests for the RiskRefinementService — start, continue, apply, and edge cases."""

from __future__ import annotations

import json
import sqlite3
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.database import init_db
from src.models.transcript import (
    ProjectContext,
    SuggestionStatus,
    SuggestionType,
    TranscriptSuggestion,
)
from src.services.risk_refinement import RiskRefinementService


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

RISK_PAYLOAD = {
    "project_key": "RISK",
    "issue_type_id": "10832",
    "summary": "Model accuracy regression",
    "fields": {
        "parent": {"key": "PROG-100"},
        "description": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Background",
                            "marks": [{"type": "strong"}],
                        },
                    ],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "High-res training showed accuracy drop",
                        },
                    ],
                },
                {"type": "rule"},
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Evidence from transcript",
                            "marks": [{"type": "strong"}],
                        },
                    ],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Sarah said accuracy dropped"},
                    ],
                },
            ],
        },
        "priority": {"name": "High"},
        "customfield_11166": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Could delay timeline by 5 days"},
                    ],
                },
            ],
        },
        "customfield_11342": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Run MRMC evaluation"},
                    ],
                },
            ],
        },
        "customfield_13267": 5,
    },
}

DECISION_PAYLOAD = {
    "project_key": "RISK",
    "issue_type_id": "12499",
    "summary": "Postpone UI redesign to Drop 3",
    "fields": {
        "parent": {"key": "PROG-100"},
        "description": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Team decided to postpone the UI redesign"},
                    ],
                },
            ],
        },
        "priority": {"name": "Medium"},
    },
}

SATISFIED_LLM_RESPONSE = {
    "satisfied": True,
    "quality_assessment": "Risk is well-documented.",
    "questions": [],
    "refined_risk": {
        "title": "Refined: Model accuracy regression in CTC pipeline",
        "background": "High-res training accuracy dropped in CTC E2E.",
        "impact_analysis": "Severity: Medium, Probability: High. Could delay by 5 days.",
        "mitigation": "Run MRMC evaluation. Revert if threshold not met.",
        "priority": "High",
        "timeline_impact_days": 5,
        "evidence": "Sarah: 'accuracy dropped'",
    },
}

QUESTIONS_LLM_RESPONSE = {
    "satisfied": False,
    "quality_assessment": "Title is too vague; mitigation lacks specifics.",
    "questions": [
        {
            "question": "What specific accuracy metrics dropped?",
            "field": "background",
            "why_needed": "Quantifying the regression helps assess severity.",
        },
        {
            "question": "Who will run the MRMC evaluation?",
            "field": "mitigation",
            "why_needed": "Mitigation steps should be assignable.",
        },
    ],
    "refined_risk": {
        "title": "Model accuracy regression in CTC pipeline",
        "background": "High-res training showed accuracy drop.",
        "impact_analysis": "Could delay timeline.",
        "mitigation": "Run evaluation.",
        "priority": "High",
        "timeline_impact_days": 5,
        "evidence": "Sarah said accuracy dropped",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project():
    from src.models.project import Project

    return Project(
        id=1,
        jira_goal_key="PROG-100",
        name="Test Project",
        confluence_charter_id="111",
        confluence_xft_id="222",
        status="active",
        phase="planning",
        created_at="2026-01-01",
    )


def _seed_db(db_path: str) -> None:
    """Insert a project and transcript into the test DB."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO projects (id, jira_goal_key, name, status, phase, "
        "confluence_charter_id, confluence_xft_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "PROG-100", "Test Project", "active", "planning", "111", "222"),
    )
    conn.execute(
        "INSERT INTO transcript_cache (id, project_id, filename, raw_text) "
        "VALUES (?, ?, ?, ?)",
        (1, 1, "meeting.vtt", "Thomas: Risk discussion"),
    )
    conn.commit()
    conn.close()


def _insert_suggestion(
    db_path: str,
    suggestion_type: str = "risk",
    payload: dict | None = None,
    title: str = "Model accuracy regression",
    detail: str = "High-res training showed accuracy drop",
    evidence: str = "Sarah said accuracy dropped",
) -> int:
    """Insert a transcript suggestion and return its ID."""
    actual_payload = payload or RISK_PAYLOAD
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        """INSERT INTO transcript_suggestions
           (transcript_id, project_id, suggestion_type, title, detail,
            evidence, proposed_payload, proposed_action, proposed_preview,
            confidence, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            1, 1, suggestion_type, title, detail,
            evidence, json.dumps(actual_payload), "create_jira_issue",
            f"Type: {suggestion_type}\nTitle: {title}",
            0.8, "pending",
        ),
    )
    conn.commit()
    sug_id = cursor.lastrowid
    conn.close()
    return sug_id


def _mock_context() -> ProjectContext:
    """Build a minimal ProjectContext for mocking."""
    return ProjectContext(
        project_name="Test Project",
        jira_goal_key="PROG-100",
        existing_risks=[
            {"key": "RISK-1", "summary": "Existing risk", "status": "Open"},
        ],
        existing_decisions=[
            {"key": "RISK-50", "summary": "Existing decision", "status": "Done"},
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStartRiskRefinement:
    """Tests for RiskRefinementService.start_risk_refinement."""

    @pytest.fixture()
    def db_path(self, tmp_path):
        path = str(tmp_path / "test.db")
        init_db(path)
        _seed_db(path)
        return path

    async def test_start_calls_agent_refine_with_correct_params(self, db_path):
        """start_risk_refinement should extract draft, gather context, and call agent.refine()."""
        sug_id = _insert_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)
        project = _make_project()

        mock_provider = AsyncMock()
        mock_provider.close = AsyncMock()

        mock_agent = AsyncMock()
        mock_agent.refine = AsyncMock(return_value=SATISFIED_LLM_RESPONSE)

        with patch("src.engine.agent.get_provider", return_value=mock_provider), \
             patch("src.engine.agent.RiskRefineAgent", return_value=mock_agent), \
             patch("src.services.transcript.TranscriptService") as MockTS:
            mock_ts_instance = MockTS.return_value
            mock_ts_instance.gather_project_context = AsyncMock(return_value=_mock_context())

            result = await service.start_risk_refinement(sug_id, project)

        # Verify agent.refine was called with correct parameters
        mock_agent.refine.assert_awaited_once()
        call_kwargs = mock_agent.refine.call_args
        assert call_kwargs.kwargs["suggestion_type"] == "risk"
        assert call_kwargs.kwargs["round_number"] == 1
        assert call_kwargs.kwargs["max_rounds"] == RiskRefinementService.MAX_REFINE_ROUNDS
        assert call_kwargs.kwargs["qa_history"] == []
        # Draft should have been extracted from the suggestion payload
        draft = call_kwargs.kwargs["current_draft"]
        assert draft["title"] == "Model accuracy regression"
        assert draft["priority"] == "High"

        # Verify existing_items came from context.existing_risks (since type=risk)
        assert call_kwargs.kwargs["existing_items"] == _mock_context().existing_risks

        # Verify result is the LLM output
        assert result["satisfied"] is True
        assert result == SATISFIED_LLM_RESPONSE

        # Verify provider was closed
        mock_provider.close.assert_awaited_once()

    async def test_start_uses_existing_decisions_for_decision_type(self, db_path):
        """When suggestion_type is decision, existing_items should be existing_decisions."""
        sug_id = _insert_suggestion(
            db_path,
            suggestion_type="decision",
            payload=DECISION_PAYLOAD,
            title="Postpone UI redesign to Drop 3",
            detail="Team decided to postpone",
            evidence="Sarah said to postpone",
        )
        service = RiskRefinementService(db_path=db_path)
        project = _make_project()

        mock_provider = AsyncMock()
        mock_provider.close = AsyncMock()
        mock_agent = AsyncMock()
        mock_agent.refine = AsyncMock(return_value=SATISFIED_LLM_RESPONSE)

        with patch("src.engine.agent.get_provider", return_value=mock_provider), \
             patch("src.engine.agent.RiskRefineAgent", return_value=mock_agent), \
             patch("src.services.transcript.TranscriptService") as MockTS:
            mock_ts_instance = MockTS.return_value
            mock_ts_instance.gather_project_context = AsyncMock(return_value=_mock_context())

            await service.start_risk_refinement(sug_id, project)

        call_kwargs = mock_agent.refine.call_args
        assert call_kwargs.kwargs["suggestion_type"] == "decision"
        assert call_kwargs.kwargs["existing_items"] == _mock_context().existing_decisions

    async def test_start_suggestion_not_found_raises(self, db_path):
        """start_risk_refinement should raise ValueError for non-existent suggestion."""
        service = RiskRefinementService(db_path=db_path)
        project = _make_project()

        with pytest.raises(ValueError, match="Suggestion 999 not found"):
            await service.start_risk_refinement(999, project)

    async def test_start_wrong_suggestion_type_raises(self, db_path):
        """start_risk_refinement should raise ValueError for non-risk/decision types."""
        sug_id = _insert_suggestion(
            db_path,
            suggestion_type="xft_update",
            payload={"summary": "XFT", "fields": {}},
            title="XFT Update",
            detail="Update XFT page",
            evidence="Someone said update XFT",
        )
        service = RiskRefinementService(db_path=db_path)
        project = _make_project()

        with pytest.raises(ValueError, match="Refinement is only available for risk/decision"):
            await service.start_risk_refinement(sug_id, project)

    async def test_start_provider_closed_on_exception(self, db_path):
        """Provider should be closed even if agent.refine() raises."""
        sug_id = _insert_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)
        project = _make_project()

        mock_provider = AsyncMock()
        mock_provider.close = AsyncMock()
        mock_agent = AsyncMock()
        mock_agent.refine = AsyncMock(side_effect=RuntimeError("LLM failure"))

        with patch("src.engine.agent.get_provider", return_value=mock_provider), \
             patch("src.engine.agent.RiskRefineAgent", return_value=mock_agent), \
             patch("src.services.transcript.TranscriptService") as MockTS:
            mock_ts_instance = MockTS.return_value
            mock_ts_instance.gather_project_context = AsyncMock(return_value=_mock_context())

            with pytest.raises(RuntimeError, match="LLM failure"):
                await service.start_risk_refinement(sug_id, project)

        mock_provider.close.assert_awaited_once()

    async def test_start_returns_questions_when_not_satisfied(self, db_path):
        """If the LLM is not satisfied, start should return questions."""
        sug_id = _insert_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)
        project = _make_project()

        mock_provider = AsyncMock()
        mock_provider.close = AsyncMock()
        mock_agent = AsyncMock()
        mock_agent.refine = AsyncMock(return_value=QUESTIONS_LLM_RESPONSE)

        with patch("src.engine.agent.get_provider", return_value=mock_provider), \
             patch("src.engine.agent.RiskRefineAgent", return_value=mock_agent), \
             patch("src.services.transcript.TranscriptService") as MockTS:
            mock_ts_instance = MockTS.return_value
            mock_ts_instance.gather_project_context = AsyncMock(return_value=_mock_context())

            result = await service.start_risk_refinement(sug_id, project)

        assert result["satisfied"] is False
        assert len(result["questions"]) == 2
        assert result["quality_assessment"] == "Title is too vague; mitigation lacks specifics."


class TestContinueRiskRefinement:
    """Tests for RiskRefinementService.continue_risk_refinement."""

    @pytest.fixture()
    def db_path(self, tmp_path):
        path = str(tmp_path / "test.db")
        init_db(path)
        _seed_db(path)
        return path

    async def test_continue_calls_agent_with_qa_history(self, db_path):
        """continue_risk_refinement should forward qa_history and round_number to agent."""
        sug_id = _insert_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)
        project = _make_project()

        draft = {"title": "Updated title", "background": "More details"}
        qa_history = [
            {"question": "How bad is it?", "answer": "Pretty bad, 5% drop"},
        ]

        mock_provider = AsyncMock()
        mock_provider.close = AsyncMock()
        mock_agent = AsyncMock()
        mock_agent.refine = AsyncMock(return_value=SATISFIED_LLM_RESPONSE)

        with patch("src.engine.agent.get_provider", return_value=mock_provider), \
             patch("src.engine.agent.RiskRefineAgent", return_value=mock_agent), \
             patch("src.services.transcript.TranscriptService") as MockTS:
            mock_ts_instance = MockTS.return_value
            mock_ts_instance.gather_project_context = AsyncMock(return_value=_mock_context())

            result = await service.continue_risk_refinement(
                suggestion_id=sug_id,
                project=project,
                risk_draft=draft,
                qa_history=qa_history,
                round_number=2,
            )

        call_kwargs = mock_agent.refine.call_args
        assert call_kwargs.kwargs["current_draft"] == draft
        assert call_kwargs.kwargs["qa_history"] == qa_history
        assert call_kwargs.kwargs["round_number"] == 2
        assert result["satisfied"] is True

    async def test_continue_max_rounds_forces_satisfied(self, db_path):
        """At MAX_REFINE_ROUNDS, should return satisfied without calling the LLM."""
        sug_id = _insert_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)
        project = _make_project()

        draft = {"title": "Final draft", "background": "bg"}

        result = await service.continue_risk_refinement(
            suggestion_id=sug_id,
            project=project,
            risk_draft=draft,
            qa_history=[],
            round_number=5,  # == MAX_REFINE_ROUNDS
        )

        assert result["satisfied"] is True
        assert result["refined_risk"] == draft
        assert "Maximum refinement rounds" in result["quality_assessment"]
        assert result["questions"] == []

    async def test_continue_above_max_rounds_still_forces_satisfied(self, db_path):
        """round_number above MAX_REFINE_ROUNDS should also force satisfaction."""
        sug_id = _insert_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)
        project = _make_project()

        draft = {"title": "Over-round draft", "background": "bg"}

        result = await service.continue_risk_refinement(
            suggestion_id=sug_id,
            project=project,
            risk_draft=draft,
            qa_history=[],
            round_number=10,
        )

        assert result["satisfied"] is True
        assert result["refined_risk"] == draft

    async def test_continue_suggestion_not_found_raises(self, db_path):
        """continue_risk_refinement should raise ValueError for non-existent suggestion."""
        service = RiskRefinementService(db_path=db_path)
        project = _make_project()

        with pytest.raises(ValueError, match="Suggestion 999 not found"):
            await service.continue_risk_refinement(
                suggestion_id=999,
                project=project,
                risk_draft={},
                qa_history=[],
                round_number=2,
            )

    async def test_continue_below_max_rounds_calls_llm(self, db_path):
        """Rounds below MAX should call the agent normally."""
        sug_id = _insert_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)
        project = _make_project()

        mock_provider = AsyncMock()
        mock_provider.close = AsyncMock()
        mock_agent = AsyncMock()
        mock_agent.refine = AsyncMock(return_value=QUESTIONS_LLM_RESPONSE)

        with patch("src.engine.agent.get_provider", return_value=mock_provider), \
             patch("src.engine.agent.RiskRefineAgent", return_value=mock_agent), \
             patch("src.services.transcript.TranscriptService") as MockTS:
            mock_ts_instance = MockTS.return_value
            mock_ts_instance.gather_project_context = AsyncMock(return_value=_mock_context())

            result = await service.continue_risk_refinement(
                suggestion_id=sug_id,
                project=project,
                risk_draft={"title": "X"},
                qa_history=[],
                round_number=4,  # Below MAX_REFINE_ROUNDS (5)
            )

        mock_agent.refine.assert_awaited_once()
        assert result["satisfied"] is False

    async def test_continue_uses_decision_existing_items(self, db_path):
        """For decision type, continue should use existing_decisions from context."""
        sug_id = _insert_suggestion(
            db_path,
            suggestion_type="decision",
            payload=DECISION_PAYLOAD,
            title="Postpone UI redesign",
            detail="Team decided to postpone",
            evidence="Sarah said to postpone",
        )
        service = RiskRefinementService(db_path=db_path)
        project = _make_project()

        mock_provider = AsyncMock()
        mock_provider.close = AsyncMock()
        mock_agent = AsyncMock()
        mock_agent.refine = AsyncMock(return_value=SATISFIED_LLM_RESPONSE)

        with patch("src.engine.agent.get_provider", return_value=mock_provider), \
             patch("src.engine.agent.RiskRefineAgent", return_value=mock_agent), \
             patch("src.services.transcript.TranscriptService") as MockTS:
            mock_ts_instance = MockTS.return_value
            mock_ts_instance.gather_project_context = AsyncMock(return_value=_mock_context())

            await service.continue_risk_refinement(
                suggestion_id=sug_id,
                project=project,
                risk_draft={"title": "Decision draft"},
                qa_history=[],
                round_number=2,
            )

        call_kwargs = mock_agent.refine.call_args
        assert call_kwargs.kwargs["existing_items"] == _mock_context().existing_decisions

    async def test_continue_provider_closed_on_exception(self, db_path):
        """Provider should be closed even if agent.refine() raises mid-continuation."""
        sug_id = _insert_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)
        project = _make_project()

        mock_provider = AsyncMock()
        mock_provider.close = AsyncMock()
        mock_agent = AsyncMock()
        mock_agent.refine = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("src.engine.agent.get_provider", return_value=mock_provider), \
             patch("src.engine.agent.RiskRefineAgent", return_value=mock_agent), \
             patch("src.services.transcript.TranscriptService") as MockTS:
            mock_ts_instance = MockTS.return_value
            mock_ts_instance.gather_project_context = AsyncMock(return_value=_mock_context())

            with pytest.raises(RuntimeError, match="boom"):
                await service.continue_risk_refinement(
                    suggestion_id=sug_id,
                    project=project,
                    risk_draft={"title": "X"},
                    qa_history=[],
                    round_number=3,
                )

        mock_provider.close.assert_awaited_once()


class TestApplyRefinement:
    """Tests for RiskRefinementService.apply_refinement."""

    @pytest.fixture()
    def db_path(self, tmp_path):
        path = str(tmp_path / "test.db")
        init_db(path)
        _seed_db(path)
        return path

    def test_apply_updates_suggestion_fields(self, db_path):
        """apply_refinement should update title, detail, evidence, confidence, and payload."""
        sug_id = _insert_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)

        refined = {
            "title": "Refined Risk Title",
            "background": "Refined background with more detail",
            "impact_analysis": "Severity: High, Probability: Medium",
            "mitigation": "Step 1: Do X. Step 2: Do Y.",
            "priority": "High",
            "timeline_impact_days": 10,
            "evidence": "Sarah: 'accuracy dropped by 5%'",
        }

        result = service.apply_refinement(sug_id, refined)

        assert result is not None
        assert result.title == "Refined Risk Title"
        assert result.detail == "Refined background with more detail"
        assert result.evidence == "Sarah: 'accuracy dropped by 5%'"
        assert result.confidence == 1.0

    def test_apply_rebuilds_payload_summary(self, db_path):
        """Payload summary field should match refined title."""
        sug_id = _insert_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)

        refined = {
            "title": "New Title",
            "background": "bg",
            "impact_analysis": "impact",
            "mitigation": "mitigate",
            "priority": "Critical",
            "timeline_impact_days": 3,
            "evidence": "evidence text",
        }

        result = service.apply_refinement(sug_id, refined)
        payload = json.loads(result.proposed_payload)

        assert payload["summary"] == "New Title"
        assert payload["fields"]["priority"]["name"] == "Critical"

    def test_apply_rebuilds_custom_fields(self, db_path):
        """Impact analysis and mitigation fields should be rebuilt in payload."""
        sug_id = _insert_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)

        refined = {
            "title": "Title",
            "background": "bg",
            "impact_analysis": "New impact analysis",
            "mitigation": "New mitigation plan",
            "priority": "Medium",
            "timeline_impact_days": 7,
            "evidence": "evidence",
        }

        result = service.apply_refinement(sug_id, refined)
        payload = json.loads(result.proposed_payload)

        # customfield_11166 = impact analysis
        assert "customfield_11166" in payload["fields"]
        # customfield_11342 = mitigation
        assert "customfield_11342" in payload["fields"]
        # customfield_13267 = timeline impact
        assert payload["fields"]["customfield_13267"] == 7

    def test_apply_updates_preview(self, db_path):
        """Proposed preview should reflect the refined content."""
        sug_id = _insert_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)

        refined = {
            "title": "Preview Test Risk",
            "background": "bg",
            "priority": "Low",
            "evidence": "ev",
        }

        result = service.apply_refinement(sug_id, refined)

        assert "Preview Test Risk" in result.proposed_preview
        assert "risk" in result.proposed_preview.lower()

    def test_apply_nonexistent_suggestion_returns_none(self, db_path):
        """Applying refinement to a non-existent suggestion should return None."""
        service = RiskRefinementService(db_path=db_path)
        result = service.apply_refinement(999, {"title": "X"})
        assert result is None

    def test_apply_with_project_context_uses_transcript_service_builder(self, db_path):
        """When context is provided, apply should use TranscriptService._build_jira_payload."""
        sug_id = _insert_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)
        context = _mock_context()

        refined = {
            "title": "Risk With Context",
            "background": "bg",
            "impact_analysis": "impact",
            "mitigation": "mitigate",
            "priority": "High",
            "timeline_impact_days": 2,
            "evidence": "ev",
        }

        mock_payload = {
            "project_key": "RISK",
            "summary": "Risk With Context",
            "fields": {"priority": {"name": "High"}},
        }

        with patch("src.services.transcript.TranscriptService") as MockTS:
            mock_ts_instance = MockTS.return_value
            mock_ts_instance._build_jira_payload = MagicMock(return_value=mock_payload)

            result = service.apply_refinement(sug_id, refined, context=context)

        mock_ts_instance._build_jira_payload.assert_called_once()
        assert result is not None
        assert result.title == "Risk With Context"

    def test_apply_decision_builds_decision_description(self, db_path):
        """For decision suggestions, apply should use build_adf_decision_description."""
        sug_id = _insert_suggestion(
            db_path,
            suggestion_type="decision",
            payload=DECISION_PAYLOAD,
            title="Postpone UI redesign",
            detail="Team decided to postpone",
            evidence="Sarah said to postpone",
        )
        service = RiskRefinementService(db_path=db_path)

        refined = {
            "title": "Postpone UI redesign to Drop 3",
            "background": "Team agreed this is lower priority",
            "impact_analysis": "",
            "mitigation": "",
            "priority": "Medium",
            "timeline_impact_days": 0,
            "evidence": "Meeting notes",
        }

        result = service.apply_refinement(sug_id, refined)

        assert result is not None
        assert result.title == "Postpone UI redesign to Drop 3"
        payload = json.loads(result.proposed_payload)
        # Description should have been rebuilt as ADF
        assert "description" in payload["fields"]
        assert payload["fields"]["description"]["type"] == "doc"

    def test_apply_preserves_original_payload_structure(self, db_path):
        """Fields not touched by refinement (parent, issue_type_id) should be preserved."""
        sug_id = _insert_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)

        refined = {
            "title": "Updated Title",
            "background": "bg",
            "impact_analysis": "impact",
            "mitigation": "mitigation",
            "priority": "High",
            "timeline_impact_days": 5,
            "evidence": "evidence",
        }

        result = service.apply_refinement(sug_id, refined)
        payload = json.loads(result.proposed_payload)

        # Original structural fields should be preserved
        assert payload["project_key"] == "RISK"
        assert payload["issue_type_id"] == "10832"
        assert payload["fields"]["parent"]["key"] == "PROG-100"


class TestGetSuggestion:
    """Tests for RiskRefinementService.get_suggestion."""

    @pytest.fixture()
    def db_path(self, tmp_path):
        path = str(tmp_path / "test.db")
        init_db(path)
        _seed_db(path)
        return path

    def test_get_existing_suggestion(self, db_path):
        sug_id = _insert_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)

        result = service.get_suggestion(sug_id)

        assert result is not None
        assert result.id == sug_id
        assert result.title == "Model accuracy regression"
        assert result.suggestion_type == SuggestionType.RISK

    def test_get_nonexistent_returns_none(self, db_path):
        service = RiskRefinementService(db_path=db_path)
        result = service.get_suggestion(999)
        assert result is None


class TestExtractRiskDraft:
    """Tests for the private _extract_risk_draft method."""

    @pytest.fixture()
    def db_path(self, tmp_path):
        path = str(tmp_path / "test.db")
        init_db(path)
        _seed_db(path)
        return path

    def test_extracts_all_fields(self, db_path):
        sug_id = _insert_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)
        sug = service.get_suggestion(sug_id)

        draft = service._extract_risk_draft(sug)

        assert draft["title"] == "Model accuracy regression"
        assert "accuracy drop" in draft["background"]
        assert "delay timeline" in draft["impact_analysis"]
        assert "MRMC" in draft["mitigation"]
        assert draft["priority"] == "High"
        assert draft["timeline_impact_days"] == "5"
        assert "Sarah" in draft["evidence"]

    def test_falls_back_to_detail_when_description_empty(self, db_path):
        """When the payload has no ADF description text, should fall back to sug.detail."""
        payload_no_desc = {
            "project_key": "RISK",
            "summary": "Empty desc risk",
            "fields": {
                "description": {"type": "doc", "version": 1, "content": []},
                "priority": {"name": "Low"},
            },
        }
        sug_id = _insert_suggestion(
            db_path,
            payload=payload_no_desc,
            title="Empty desc risk",
            detail="Fallback detail text",
        )
        service = RiskRefinementService(db_path=db_path)
        sug = service.get_suggestion(sug_id)

        draft = service._extract_risk_draft(sug)

        assert draft["background"] == "Fallback detail text"

    def test_handles_missing_custom_fields(self, db_path):
        """When custom fields are absent, should return empty strings / defaults."""
        payload_minimal = {
            "project_key": "RISK",
            "summary": "Minimal risk",
            "fields": {
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Some background"}],
                        },
                    ],
                },
                "priority": {"name": "Medium"},
            },
        }
        sug_id = _insert_suggestion(
            db_path,
            payload=payload_minimal,
            title="Minimal risk",
        )
        service = RiskRefinementService(db_path=db_path)
        sug = service.get_suggestion(sug_id)

        draft = service._extract_risk_draft(sug)

        assert draft["impact_analysis"] == ""
        assert draft["mitigation"] == ""
        assert draft["priority"] == "Medium"
        assert draft["timeline_impact_days"] == "0"

    def test_handles_non_dict_priority(self, db_path):
        """When priority is not a dict, should default to 'Medium'."""
        payload_bad_priority = {
            "project_key": "RISK",
            "summary": "Bad priority",
            "fields": {
                "description": {"type": "doc", "version": 1, "content": []},
                "priority": "not a dict",
            },
        }
        sug_id = _insert_suggestion(
            db_path,
            payload=payload_bad_priority,
            title="Bad priority risk",
            detail="detail",
        )
        service = RiskRefinementService(db_path=db_path)
        sug = service.get_suggestion(sug_id)

        draft = service._extract_risk_draft(sug)

        assert draft["priority"] == "Medium"
