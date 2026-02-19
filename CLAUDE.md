# Project Seat

An AI-assisted project management cockpit for medical device software engineering projects. Runs locally as a Python web application, connecting to Atlassian cloud tools via REST APIs, with an LLM as the reasoning engine.

## Tech Stack

- **Language:** Python 3.14
- **Web framework:** FastAPI + Uvicorn
- **Frontend:** HTMX + Jinja2 templates
- **Database:** SQLite (via sqlite3 stdlib, no ORM)
- **HTTP client:** httpx (async)
- **LLM:** TBD (Claude API or alternative — abstracted behind agent layer)
- **Package management:** uv (preferred) or pip + venv

## Architecture

The application has four layers:

1. **Web Frontend** — FastAPI + HTMX. Four views: Dashboard (CI-style pipeline), Approval Queue, Project Spin-Up Wizard, Transcript Upload.
2. **Core Engine** — Orchestrator (task scheduling), LLM Agent Layer (prompt templates + context assembly), Approval Engine (queue + gate all write actions).
3. **API Connectors** — Thin wrappers around Jira, Confluence, and (future) Salesforce REST APIs. Each connector handles auth, pagination, rate limiting, error handling.
4. **Local Data Layer** — SQLite for state/config/audit trail. `.env` for API keys.

See `docs/architecture.pdf` and `docs/workflow.pdf` for visual diagrams.

## Folder Structure

```
project-seat/
├── CLAUDE.md                    # This file
├── README.md                    # Project overview and setup instructions
├── dev.py                       # Dev server launcher (kills stale port 8000 processes)
├── pyproject.toml               # Python project config and dependencies
├── .env.example                 # Template for required API keys
├── .gitignore
├── docs/
│   ├── architecture.pdf         # System architecture diagram
│   ├── workflow.pdf             # Product workflow diagram
│   ├── jira-structure.md        # Jira hierarchy and template documentation
│   └── confluence-structure.md  # Confluence page tree and template documentation
├── samples/                     # Sample API responses (do NOT commit API tokens)
│   ├── jira/
│   │   ├── prog-256.json
│   │   ├── aim-3295.json
│   │   ├── risk-145.json
│   │   ├── prog-issue-types.json
│   │   ├── risk-issue-types.json
│   │   ├── risk-versions.json
│   │   ├── field-definitions.json
│   │   └── field-name-to-id.json
│   ├── confluence/
│   │   ├── charter-template.json
│   │   ├── xft-template.json
│   │   └── page-*.json
│   └── transcripts/             # Sample meeting transcripts for testing
├── src/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app entry point
│   ├── config.py                # Settings, env loading, constants
│   ├── database.py              # SQLite setup, migrations, queries
│   ├── connectors/
│   │   ├── __init__.py
│   │   ├── base.py              # Base connector class (auth, retry, pagination)
│   │   ├── jira.py              # Jira REST API connector
│   │   └── confluence.py        # Confluence REST API connector
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── orchestrator.py      # Task queue and scheduling
│   │   ├── agent.py             # LLM agent layer (prompts, context, parsing)
│   │   ├── approval.py          # Approval queue and gating logic
│   │   └── prompts/
│   │       ├── release_plan.py      # Release planning prompt template
│   │       ├── transcript.py        # Transcript processing prompt template
│   │       ├── risk_decision.py     # Risk/decision extraction prompt template
│   │       └── estimate_check.py    # Missing estimate detection prompt template
│   ├── services/
│   │   ├── __init__.py
│   │   ├── spinup.py            # Project spin-up wizard logic
│   │   ├── transcript.py        # Transcript upload and processing
│   │   ├── dashboard.py         # Dashboard data aggregation
│   │   └── monitoring.py        # Ongoing project monitoring
│   ├── web/
│   │   ├── __init__.py
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── dashboard.py
│   │   │   ├── approval.py
│   │   │   ├── spinup.py
│   │   │   └── transcript.py
│   │   ├── templates/           # Jinja2 HTML templates
│   │   │   ├── base.html
│   │   │   ├── dashboard.html
│   │   │   ├── approval.html
│   │   │   ├── spinup.html
│   │   │   └── transcript.html
│   │   └── static/              # CSS, JS, images
│   │       ├── style.css
│   │       └── htmx.min.js
│   └── models/
│       ├── __init__.py
│       ├── project.py           # Project, release data models
│       ├── approval.py          # Approval queue item models
│       └── jira.py              # Jira ticket data models
└── tests/
    ├── __init__.py
    ├── conftest.py              # Shared fixtures
    ├── test_connectors/
    │   ├── test_jira.py
    │   └── test_confluence.py
    ├── test_engine/
    │   ├── test_orchestrator.py
    │   ├── test_agent.py
    │   └── test_approval.py
    └── test_services/
        ├── test_spinup.py
        └── test_transcript.py
```

## How to Run

```bash
# Install dependencies
uv sync  # or: pip install -e .

# Copy and fill in API keys
cp .env.example .env

# Run the app (kills stale processes on port 8000 first)
python dev.py

# Run tests
pytest
```

## Key Conventions

### Connectors
- All connectors inherit from `BaseConnector` in `src/connectors/base.py`
- Base class handles: authentication (Basic auth with API token), automatic retry with backoff, pagination, rate limit handling, error logging
- Connectors expose clean Python methods — no raw HTTP outside the connector layer
- Never call Jira/Confluence APIs directly from services or engine code; always go through a connector

### LLM Agent
- All LLM interactions go through `src/engine/agent.py` — never call the LLM API directly from other modules
- Prompt templates live in `src/engine/prompts/` as Python files that build the prompt string
- The agent layer is LLM-agnostic: it takes a prompt and returns structured output. The specific LLM provider is configured in `src/config.py`
- All LLM responses that result in write actions must pass through the Approval Engine first

### Approval Engine
- Every write action (creating Jira tickets, updating Confluence pages, etc.) requires user approval
- The approval queue stores the proposed action, the source context (what triggered it), and a preview of what will be created/changed
- Approved actions are logged in SQLite for audit trail
- This is critical for regulatory traceability — a human approved every change

### Frontend
- HTMX for reactivity — no JavaScript framework
- Jinja2 templates in `src/web/templates/`
- Keep templates simple; business logic lives in services, not in templates or routes
- Routes are thin — validate input, call a service, return a template

### Database
- SQLite via stdlib `sqlite3` — no ORM
- Schema migrations in `src/database.py`
- Tables: projects, approval_log, transcript_cache, config

### Testing
- Use pytest
- Mock API responses using sample data from `samples/`
- Test connectors against saved JSON responses, not live APIs
- Test the agent layer with known prompts and expected structured outputs

## Jira Structure

The project hierarchy in Jira:

```
Goal (PROG project)
├── Initiative (per team project: AIM, CTCV, YAM, etc.)
│   ├── Epic (feature-level work)
│   │   └── Task (developer work items)
├── Risk (RISK project, linked to Goal)
└── Decision / Project Issue (RISK project, linked to Goal)
```

**At spin-up, the cockpit creates:**
1. Goal ticket in PROG project
2. Fix version in RISK project and all selected team projects
3. Confluence Charter page from template (page ID: 3559363918), placed under the correct Program → Projects/Releases parent
4. Confluence XFT page from template (page ID: 3559363934), as child of Charter page
5. Links to Confluence pages in the Goal ticket description

**The cockpit does NOT create:** Initiatives, Epics, or Tasks (teams do this manually).

**RISK project:** Risks need a component (e.g. "HOP Frontend") and a fix version matching the project. They are linked to the parent PROG Goal. Decisions use the "Project Issue" issue type in the same project.

## Confluence Structure

All project pages live in the **PMO Project Portfolio** space.

```
PMO Project Portfolio
└── Product Development Projects
    └── [Product] Program (e.g. "HOP Program")
        ├── CEO Review
        └── Projects/Releases
            └── [Project Charter] (from template page 3559363918)
                └── [Project XFT] (from template page 3559363934)
```

The Charter template page and XFT template page are regular Confluence pages (not system templates). The cockpit fetches their content via the REST API and creates new pages with that structure, replacing placeholders with project details.

## Environment Variables

```
ATLASSIAN_DOMAIN=yourcompany
ATLASSIAN_EMAIL=your.email@company.com
ATLASSIAN_API_TOKEN=your-token
LLM_PROVIDER=claude  # or: openai, ollama, etc.
LLM_API_KEY=your-llm-key
LLM_MODEL=claude-sonnet-4-20250514
```

## Important Notes

- This is a single-user application running locally
- All write actions to Jira/Confluence require explicit user approval
- The LLM provider is abstracted — the codebase should not have provider-specific code outside of `src/engine/agent.py` and `src/config.py`
- Sample data in `samples/` contains real Jira field structures — reference these when building connectors
- The `field-name-to-id.json` mapping is essential for working with Jira custom fields
