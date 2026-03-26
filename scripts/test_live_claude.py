"""Live integration tests for Claude provider — token limits, schema compliance, two-pass flow."""

import asyncio
import json
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv()

from src.engine.agent import TranscriptAgent, HealthReviewAgent, get_provider
from src.config import LLMSettings
from src.services.context_resolver import ContextRequestResolver


def _settings():
    return LLMSettings(
        provider="claude",
        api_key=os.getenv("LLM_API_KEY"),
        model=os.getenv("LLM_MODEL"),
        verify_ssl=False,
    )


# ----------------------------------------------------------------
# TEST 1: Context resolver against real APIs
# ----------------------------------------------------------------

async def test_context_resolver():
    from src.config import settings

    print("=" * 60)
    print("TEST 1: ContextRequestResolver - real API calls")
    print("=" * 60)

    resolver = ContextRequestResolver(settings=settings)
    requests = [
        {"type": "jira_issue", "query": "PROG-256", "reason": "Known goal ticket"},
        {"type": "jira_search", "query": "HOP risk", "reason": "Text search"},
        {"type": "confluence_search", "query": "Charter", "reason": "Page search"},
    ]

    t0 = time.monotonic()
    results = await resolver.resolve(requests)
    elapsed = time.monotonic() - t0

    print(f"Resolved {len(results)}/{len(requests)} in {elapsed:.1f}s")

    errors = []
    for r in results:
        print(f"  [{r['type']}] {r['query']}: {len(r['result'])} chars")
        print(f"    Preview: {r['result'][:150]}")
        if len(r["result"]) > 3000:
            errors.append(f"Result exceeds 3000 char limit: {len(r['result'])}")
        if "failed" in r["result"].lower() and "not found" not in r["result"].lower():
            errors.append(f"{r['type']}({r['query']}): got failure")

    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        return False
    print("  PASS")
    return True


# ----------------------------------------------------------------
# TEST 2: Large transcript — token limit stress test
# ----------------------------------------------------------------

async def test_large_transcript():
    print()
    print("=" * 60)
    print("TEST 2: Large transcript (~15K chars) - token limit test")
    print("=" * 60)

    speakers = ["Thomas", "Sarah", "James", "Alice", "Bob"]
    lines = []
    for i in range(150):
        speaker = speakers[i % len(speakers)]
        lines.append(
            f"{speaker}: Line {i+1}. The CTC detection pipeline needs attention. "
            f"We should review RISK-200 and the model accuracy results. "
            f"The performance testing protocol needs an update."
        )
    large_transcript = "\n".join(lines)
    print(f"  Transcript: {len(large_transcript)} chars")

    context = {
        "project_name": "HOP Drop 4",
        "jira_goal_key": "PROG-300",
        "existing_risks": [
            {"key": f"RISK-{i}", "summary": f"Existing risk {i}", "status": "Open"}
            for i in range(20)
        ],
        "existing_decisions": [
            {"key": f"RISK-{100+i}", "summary": f"Decision {i}", "status": "Done"}
            for i in range(10)
        ],
        "charter_content": "<p>" + "Charter content. " * 200 + "</p>",
        "xft_content": "<p>" + "XFT notes. " * 100 + "</p>",
        "open_action_items": [
            {"title": f"Action {i}", "owner": "Sarah", "status": "open"}
            for i in range(5)
        ],
        "knowledge_entries": [
            {"title": f"Insight {i}", "type": "insight", "tags": "model"}
            for i in range(10)
        ],
    }

    provider = get_provider(_settings())
    agent = TranscriptAgent(provider)

    errors = []
    t0 = time.monotonic()
    try:
        result = await agent.analyze_transcript(large_transcript, context)
        elapsed = time.monotonic() - t0
        print(f"  Response time: {elapsed:.1f}s")

        # Check required top-level fields
        for field in ["meeting_summary", "suggestions", "context_requests"]:
            if field not in result:
                errors.append(f"Missing top-level field: {field}")
            else:
                print(f"  {field}: {type(result[field]).__name__} (len={len(result[field]) if isinstance(result[field], (str, list)) else 'N/A'})")

        # Check suggestion schema
        required_fields = [
            "type", "title", "background", "impact_analysis", "mitigation",
            "evidence", "priority", "timeline_impact_days", "confidence",
            "confluence_section_title", "confluence_content",
            "owner_name", "due_date_hint", "tags",
        ]
        for i, s in enumerate(result.get("suggestions", [])):
            missing = [f for f in required_fields if f not in s]
            if missing:
                errors.append(f"Suggestion {i} missing fields: {missing}")
            # Validate enums
            if s.get("type") not in ("risk", "decision", "xft_update", "charter_update", "action_item", "note", "insight"):
                errors.append(f"Suggestion {i}: invalid type '{s.get('type')}'")
            if s.get("priority") not in ("High", "Medium", "Low"):
                errors.append(f"Suggestion {i}: invalid priority '{s.get('priority')}'")
            if not isinstance(s.get("confidence"), (int, float)):
                errors.append(f"Suggestion {i}: confidence is not a number")
            elif not (0.0 <= s["confidence"] <= 1.0):
                errors.append(f"Suggestion {i}: confidence {s['confidence']} out of range 0-1")
            if not isinstance(s.get("timeline_impact_days"), (int, float)):
                errors.append(f"Suggestion {i}: timeline_impact_days is not a number")
            if not isinstance(s.get("tags"), list):
                errors.append(f"Suggestion {i}: tags is not a list")

        # Check context_requests schema
        for i, cr in enumerate(result.get("context_requests", [])):
            for f in ["type", "query", "reason"]:
                if f not in cr:
                    errors.append(f"Context request {i} missing field: {f}")
            if cr.get("type") not in ("jira_issue", "jira_search", "confluence_search"):
                errors.append(f"Context request {i}: invalid type '{cr.get('type')}'")

    except Exception as e:
        errors.append(f"{type(e).__name__}: {e}")
    finally:
        await provider.close()

    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        return False
    print("  PASS: All fields present, all types/enums valid")
    return True


# ----------------------------------------------------------------
# TEST 3: Health review — full context, schema validation
# ----------------------------------------------------------------

async def test_health_review_schema():
    print()
    print("=" * 60)
    print("TEST 3: Health review - full context + schema validation")
    print("=" * 60)

    context = {
        "project_name": "HOP Drop 4",
        "goal": {"key": "PROG-300", "summary": "HOP Drop 4", "status": "In Progress", "due_date": "2026-06-30"},
        "risk_count": 15, "open_risk_count": 8, "decision_count": 12,
        "risk_points": 45, "risk_threshold": 30, "risk_level": "High",
        "risks": [
            {"key": f"RISK-{i}", "summary": f"Risk {i} - model concern", "status": "Open"}
            for i in range(15)
        ],
        "decisions": [
            {"key": f"RISK-{100+i}", "summary": f"Decision {i}", "status": "Done"}
            for i in range(12)
        ],
        "initiatives": [
            {"key": "AIM-100", "summary": "CTC Model Dev", "epic_count": 8,
             "done_epic_count": 5, "task_count": 45, "done_task_count": 30},
        ],
        "team_reports": [
            {"team_key": "AIM", "version_name": "Drop 4", "total_issues": 45,
             "done_count": 30, "in_progress_count": 10, "todo_count": 5,
             "blocker_count": 2, "sp_total": 180, "sp_done": 120, "pct_done_issues": 67},
        ],
        "burnup_snapshots": [
            {"date": "2026-01-01", "sp_total": 200, "sp_done": 50},
            {"date": "2026-03-15", "sp_total": 260, "sp_done": 168},
        ],
        "dhf_summary": {"total_count": 50, "released_count": 32,
                        "draft_update_count": 10, "in_draft_count": 8},
        "releases": [{"name": "Drop 4 RC1", "locked": False}],
        "charter_content": "<p>HOP Drop 4 Charter - CTC detection scope</p>",
        "xft_content": "<p>XFT notes from recent meetings</p>",
        "meeting_summaries": [
            {"filename": "standup.vtt", "created_at": "2026-03-20",
             "summary": "Discussed model accuracy and data quality issues."},
        ],
        "open_action_items": [
            {"title": "Fix labelling pipeline", "owner": "Sarah", "status": "open"},
        ],
        "knowledge_entries": [
            {"title": "Edge cases need diverse data", "type": "insight"},
        ],
        "past_health_reviews": [
            {"health_rating": "Amber", "health_rationale": "Risk points approaching threshold",
             "created_at": "2026-03-12"},
        ],
    }

    provider = get_provider(_settings())
    agent = HealthReviewAgent(provider)

    errors = []
    t0 = time.monotonic()
    try:
        result = await agent.generate_review(context, [
            {"question": "How is team morale?", "answer": "Tired but motivated."},
            {"question": "External dependencies?", "answer": "Waiting on regulatory feedback."},
        ])
        elapsed = time.monotonic() - t0
        print(f"  Response time: {elapsed:.1f}s")

        # Required top-level fields
        required = ["health_rating", "health_rationale", "top_concerns",
                     "positive_observations", "questions_for_pm", "suggested_next_actions"]
        for f in required:
            if f not in result:
                errors.append(f"Missing field: {f}")
            else:
                val = result[f]
                if isinstance(val, list):
                    print(f"  {f}: {len(val)} items")
                else:
                    print(f"  {f}: {str(val)[:100]}")

        # Validate health_rating enum
        if result.get("health_rating") not in ("Green", "Amber", "Red"):
            errors.append(f"Invalid health_rating: '{result.get('health_rating')}'")

        # Validate concern structure
        for i, c in enumerate(result.get("top_concerns", [])):
            for f in ["area", "severity", "evidence", "recommendation"]:
                if f not in c:
                    errors.append(f"Concern {i} missing field: {f}")
            if c.get("severity") not in ("High", "Medium", "Low"):
                errors.append(f"Concern {i}: invalid severity '{c.get('severity')}'")
            print(f"    Concern: [{c.get('severity')}] {c.get('area')}")

        # Validate arrays are actually arrays of strings
        for f in ["positive_observations", "questions_for_pm", "suggested_next_actions"]:
            arr = result.get(f, [])
            if not isinstance(arr, list):
                errors.append(f"{f} is not a list")
            for i, item in enumerate(arr):
                if not isinstance(item, str):
                    errors.append(f"{f}[{i}] is not a string: {type(item)}")

    except Exception as e:
        errors.append(f"{type(e).__name__}: {e}")
    finally:
        await provider.close()

    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        return False
    print("  PASS: All fields valid, correct types and enums")
    return True


# ----------------------------------------------------------------
# TEST 4: Two-pass refinement — end-to-end with real Claude
# ----------------------------------------------------------------

async def test_two_pass_refinement():
    print()
    print("=" * 60)
    print("TEST 4: Two-pass refinement - context request + refine")
    print("=" * 60)

    # Transcript that references things not in context
    transcript = (
        "Thomas: Let's review RISK-200. Sarah, what did you find?\n"
        "Sarah: RISK-200 is worse than we thought. The labelling inconsistency "
        "affects 15% of training data. We need to check the performance testing "
        "protocol for the threshold.\n"
        "James: Also, CTCV-50 is stuck. Can we look into it?\n"
        "Thomas: Yes, and let's formally decide whether to pause training."
    )

    context = {
        "project_name": "HOP Drop 4",
        "jira_goal_key": "PROG-300",
        "existing_risks": [
            {"key": "RISK-200", "summary": "Data labelling inconsistency", "status": "Open"},
        ],
        "existing_decisions": [],
        "charter_content": None,
        "xft_content": None,
        "open_action_items": [],
        "knowledge_entries": [],
    }

    provider = get_provider(_settings())
    agent = TranscriptAgent(provider)

    errors = []
    try:
        # First pass
        t0 = time.monotonic()
        result1 = await agent.analyze_transcript(transcript, context)
        t1 = time.monotonic()
        print(f"  First pass: {t1 - t0:.1f}s")
        print(f"  Suggestions: {len(result1.get('suggestions', []))}")

        ctx_reqs = result1.get("context_requests", [])
        print(f"  Context requests: {len(ctx_reqs)}")
        for cr in ctx_reqs:
            print(f"    - [{cr['type']}] {cr['query']}")

        if not ctx_reqs:
            print("  INFO: No context requests (LLM decided context was sufficient)")
            print("  PASS (single-pass)")
        else:
            # Simulate fetched context
            fetched = []
            for cr in ctx_reqs:
                fetched.append({
                    "type": cr["type"],
                    "query": cr["query"],
                    "result": f"Simulated result for {cr['query']}: This ticket is about testing.",
                })

            # Second pass
            t2 = time.monotonic()
            result2 = await agent.refine_with_context(result1, fetched)
            t3 = time.monotonic()
            print(f"  Second pass: {t3 - t2:.1f}s")
            print(f"  Refined suggestions: {len(result2.get('suggestions', []))}")

            # Validate refined result has same schema
            for f in ["meeting_summary", "suggestions", "context_requests"]:
                if f not in result2:
                    errors.append(f"Refined result missing: {f}")

            # Refined context_requests should be empty
            if result2.get("context_requests"):
                print(f"  NOTE: Refined result has {len(result2['context_requests'])} context requests (expected 0)")

            for i, s in enumerate(result2.get("suggestions", [])):
                print(f"    {i+1}. [{s.get('type')}] {s.get('title')} (conf: {s.get('confidence')})")

            print(f"  Total time: {t3 - t0:.1f}s")

    except Exception as e:
        errors.append(f"{type(e).__name__}: {e}")
    finally:
        await provider.close()

    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        return False
    print("  PASS")
    return True


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------

async def main():
    results = []
    results.append(await test_context_resolver())
    results.append(await test_large_transcript())
    results.append(await test_health_review_schema())
    results.append(await test_two_pass_refinement())

    print()
    print("=" * 60)
    print(f"RESULTS: {sum(results)}/{len(results)} tests passed")
    print("=" * 60)

    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
