# Project Seat

An AI-assisted project management cockpit for medical device software engineering projects. Runs locally as a Python web app, connecting to Jira and Confluence via REST APIs, with an LLM as the reasoning engine.

## What It Does

- **Manages projects** across their lifecycle — spin-up, release tracking, DHF document monitoring, team progress, and closure
- **Unified Meetings page** — manual transcript upload and Zoom recording ingestion in a single view, with source/project/status filtering, inline project assignment, and LLM analysis
- **Analyses meeting transcripts** using an LLM to extract risks, decisions, and action items, with iterative refinement against ISO 14971 quality criteria, semantic dedup against existing Jira items, and two-pass context enrichment (agent can request additional Jira/Confluence lookups)
- **Ingests Zoom recordings** automatically via OAuth — fetches new recordings on demand, matches them to projects (title match + LLM fallback), and queues unmatched meetings for manual triage
- **Builds a project knowledge base** — action items, notes, and insights extracted by the LLM during transcript analysis are stored per-project in a searchable knowledge database
- **Generates structured reports** — project health reviews, CEO status updates, and closure reports — combining deterministic data tables with LLM-written narrative
- **Enforces governance** — every automated write action to Jira or Confluence passes through a human-approval queue with a full audit trail

## Tech Stack

Python 3.12+ / FastAPI / HTMX / Jinja2 / Chart.js / SQLite / Claude Sonnet (default), Gemini 2.5 Flash, or Ollama

## Quick Start

```bash
uv sync                # Install dependencies
cp .env.example .env   # Add your Atlassian + LLM API keys
python dev.py          # Run on http://localhost:8000
```

## Documentation

| Document | Description |
|---|---|
| `CLAUDE.md` | Full project context for AI-assisted development |
| `docs/features.md` | Complete feature list |
| `docs/feature-backlog.md` | Planned features and technical debt |
| `docs/workflows.md` | Detailed LLM workflow documentation |
| `docs/architecture.mmd` | System architecture diagram (Mermaid) |
| `docs/workflow.mmd` | Product workflow diagram (Mermaid) |
| `docs/spinup-flow.md` | Spin-up workflow |
| `docs/jira-structure.md` | Jira hierarchy and templates |
| `docs/confluence-structure.md` | Confluence page tree |
