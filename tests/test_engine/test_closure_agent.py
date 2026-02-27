"""Tests for the ClosureAgent ask_questions and generate_report methods."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.engine.agent import ClosureAgent


class TestClosureAgent:
    """Test the ClosureAgent two-step LLM interaction."""

    @pytest.mark.asyncio
    async def test_ask_questions(self):
        mock_provider = AsyncMock()
        mock_provider.generate.return_value = json.dumps({
            "questions": [
                {
                    "question": "What were the main lessons from vendor management?",
                    "category": "Vendor",
                    "why_needed": "No vendor feedback in data",
                }
            ]
        })

        agent = ClosureAgent(mock_provider)
        result = await agent.ask_questions(
            metrics={"project_name": "Test", "all_risks": [], "all_decisions": []},
            pm_notes="Project completed on time",
        )

        assert "questions" in result
        assert len(result["questions"]) == 1
        assert result["questions"][0]["category"] == "Vendor"

    @pytest.mark.asyncio
    async def test_ask_questions_empty(self):
        mock_provider = AsyncMock()
        mock_provider.generate.return_value = json.dumps({"questions": []})

        agent = ClosureAgent(mock_provider)
        result = await agent.ask_questions(
            metrics={"project_name": "Test"},
            pm_notes="Comprehensive notes covering everything",
        )

        assert result["questions"] == []

    @pytest.mark.asyncio
    async def test_generate_report(self):
        mock_provider = AsyncMock()
        mock_provider.generate.return_value = json.dumps({
            "final_delivery_outcome": "The project delivered all planned features on schedule.",
            "success_criteria_assessments": [
                {
                    "criterion": "Regulatory submission",
                    "expected_outcome": "Submit by Q1 2026",
                    "measurement_method": "Submission date",
                    "actual_performance": "Submitted Feb 2026",
                    "status": "Met",
                    "comments": "On time",
                }
            ],
            "lessons_learned": [
                {
                    "category": "Planning",
                    "description": "Early scope definition was critical",
                    "effect_triggers": "Scope creep in early sprints",
                    "recommendations": "Lock scope before sprint 3",
                    "owner": "PM",
                },
                {
                    "category": "Technical",
                    "description": "CI/CD pipeline saved weeks",
                    "effect_triggers": "Manual deployment pain",
                    "recommendations": "Invest in CI/CD from day 1",
                    "owner": "Tech Lead",
                },
                {
                    "category": "Team",
                    "description": "Cross-team standups improved alignment",
                    "effect_triggers": "Siloed teams in phase 1",
                    "recommendations": "Start XFT standups from kickoff",
                    "owner": "Scrum Master",
                },
            ],
        })

        agent = ClosureAgent(mock_provider)
        result = await agent.generate_report(
            metrics={"project_name": "Test"},
            pm_notes="",
            qa_pairs=[],
        )

        assert "final_delivery_outcome" in result
        assert "success_criteria_assessments" in result
        assert len(result["success_criteria_assessments"]) == 1
        assert result["success_criteria_assessments"][0]["status"] == "Met"
        assert "lessons_learned" in result
        assert len(result["lessons_learned"]) == 3
        assert result["lessons_learned"][0]["category"] == "Planning"

    @pytest.mark.asyncio
    async def test_generate_report_with_qa(self):
        mock_provider = AsyncMock()
        mock_provider.generate.return_value = json.dumps({
            "final_delivery_outcome": "Project delivered with vendor delays.",
            "success_criteria_assessments": [],
            "lessons_learned": [
                {
                    "category": "Vendor",
                    "description": "Vendor delays impacted timeline",
                    "effect_triggers": "Late vendor deliverables",
                    "recommendations": "Include vendor SLAs in contracts",
                    "owner": "Procurement",
                },
            ],
        })

        agent = ClosureAgent(mock_provider)
        result = await agent.generate_report(
            metrics={"project_name": "Test"},
            pm_notes="Vendor delays noted",
            qa_pairs=[
                {"question": "What caused vendor delays?", "answer": "Late chip delivery"},
            ],
        )

        assert "vendor" in result["final_delivery_outcome"].lower()
        assert len(result["lessons_learned"]) >= 1
