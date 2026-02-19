# Project Seat

An AI-assisted project management cockpit for medical device software engineering projects. Runs locally as a Python web application, connecting to Atlassian cloud tools via REST APIs, with an LLM as the reasoning engine.

## Tech Stack

- **Language:** Python 3.12+
- **Web framework:** FastAPI + Uvicorn
- **Frontend:** HTMX + Jinja2 templates
- **Database:** SQLite (via sqlite3 stdlib, no ORM)
- **HTTP client:** httpx (async)
- **LLM:** Gemini 2.5 Flash (default) or Ollama — provider-agnostic via `src/engine/agent.py`
- **Package management:** uv (preferred) or pip + venv

## Architecture

The application has four layers:

1. **Web Frontend** — FastAPI + HTMX. Current views: Pipeline (phases overview), Project Detail (dashboard/features/documents/approvals), Approval Queue, Project Spin-Up Wizard, Project Import, Transcript Analysis.
2. **Core Engine** — Approval Engine (queue + gate all write actions), LLM Agent Layer (provider-agnostic interface with prompt templates + structured output). *Planned:* Orchestrator (task scheduling).
3. **API Connectors** — Thin wrappers around Jira, Confluence, and (future) Salesforce REST APIs. Each connector handles auth, pagination, rate limiting, error handling.
4. **Local Data Layer** — SQLite for state/config/audit trail. `.env` for API keys.

Key capabilities: project spin-up, release scope-freeze tracking, DHF/EQMS document tracking (draft vs released), product ideas (PI) board integration, LLM-powered transcript analysis with two-step approval gating.

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
│   │   ├── page-hop-program.json
│   │   ├── page-product-development-projects.json
│   │   └── page-projects-releases.json
│   └── transcripts/             # (planned) Sample meeting transcripts for testing
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
│   │   ├── approval.py          # Approval queue and gating logic
│   │   ├── agent.py             # LLM agent layer (provider protocol, factory, TranscriptAgent)
│   │   ├── orchestrator.py      # (planned) Task queue and scheduling
│   │   ├── providers/
│   │   │   ├── __init__.py
│   │   │   ├── gemini.py        # Gemini provider (httpx, structured output via responseSchema)
│   │   │   └── ollama.py        # Ollama provider (httpx, local inference)
│   │   └── prompts/
│   │       ├── __init__.py
│   │       ├── transcript.py        # Transcript analysis: system prompt, JSON schema, ADF helpers
│   │       ├── release_plan.py      # (planned) Release planning prompt template
│   │       ├── risk_decision.py     # (planned) Risk/decision extraction prompt template
│   │       └── estimate_check.py    # (planned) Missing estimate detection prompt template
│   ├── services/
│   │   ├── __init__.py
│   │   ├── spinup.py            # Project spin-up wizard logic
│   │   ├── dashboard.py         # Dashboard data aggregation
│   │   ├── dhf.py               # DHF/EQMS document tracking (draft vs released)
│   │   ├── import_project.py    # Import existing projects from Jira/Confluence
│   │   ├── release.py           # Release scope-freeze and document tracking
│   │   └── transcript.py        # Transcript parsing, LLM analysis, suggestion management
│   ├── web/
│   │   ├── __init__.py
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── approval.py
│   │   │   ├── import_project.py
│   │   │   ├── phases.py           # Pipeline/phases overview
│   │   │   ├── project.py          # Project detail (dashboard/features/docs/approvals)
│   │   │   ├── spinup.py
│   │   │   └── transcript.py       # Upload, analyze, accept/reject suggestions
│   │   ├── templates/           # Jinja2 HTML templates
│   │   │   ├── base.html
│   │   │   ├── phases.html
│   │   │   ├── approval.html
│   │   │   ├── spinup.html
│   │   │   ├── spinup_result.html
│   │   │   ├── import.html
│   │   │   ├── project_dashboard.html
│   │   │   ├── project_features.html
│   │   │   ├── project_documents.html
│   │   │   ├── project_approvals.html
│   │   │   ├── initiative_detail.html
│   │   │   ├── transcript.html                  # Upload form + transcript history
│   │   │   ├── transcript_suggestions_page.html # Full-page suggestion review
│   │   │   └── partials/
│   │   │       ├── approval_pending.html
│   │   │       ├── approval_row.html
│   │   │       ├── import_confirm.html
│   │   │       ├── project_card.html
│   │   │       ├── transcript_parsed.html       # Parsed preview with Analyze button
│   │   │       ├── transcript_suggestions.html  # Suggestions panel with Accept All
│   │   │       └── suggestion_row.html          # Individual suggestion accept/reject
│   │   └── static/              # CSS, JS, images
│   │       ├── style.css
│   │       └── htmx.min.js
│   └── models/
│       ├── __init__.py
│       ├── project.py           # Project data models
│       ├── approval.py          # Approval queue item models
│       ├── jira.py              # Jira ticket data models
│       ├── dashboard.py         # Dashboard view models
│       ├── dhf.py               # DHF document models
│       ├── release.py           # Release and scope-freeze models
│       └── transcript.py        # Transcript, suggestion, and project context models
└── tests/
    ├── __init__.py
    ├── conftest.py              # Shared fixtures
    ├── test_database.py
    ├── test_connectors/
    │   ├── test_base.py
    │   ├── test_jira.py
    │   ├── test_confluence.py
    │   └── test_confluence_v2.py
    ├── test_engine/
    │   ├── test_approval.py
    │   ├── test_agent.py            # Provider factory + TranscriptAgent tests
    │   └── test_orchestrator.py     # (planned)
    ├── test_models/
    │   ├── test_project_models.py
    │   ├── test_approval_models.py
    │   ├── test_jira_models.py
    │   ├── test_dashboard_models.py
    │   └── test_dhf_models.py
    ├── test_services/
    │   ├── test_spinup.py
    │   ├── test_dashboard.py
    │   ├── test_dhf.py
    │   ├── test_import.py
    │   ├── test_release.py
    │   └── test_transcript.py       # Parser + service tests
    └── test_web/
        ├── test_routes_approval.py
        ├── test_routes_import.py
        ├── test_routes_phases.py
        ├── test_routes_project.py
        └── test_routes_spinup.py
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

### LLM Agent Layer
- All LLM interactions go through `src/engine/agent.py` — never call the LLM API directly from other modules
- `LLMProvider` is a `Protocol`: `generate(system_prompt, user_prompt, *, response_schema, temperature, max_tokens) -> str`
- Provider implementations live in `src/engine/providers/` — currently Gemini (`gemini.py`) and Ollama (`ollama.py`)
- `get_provider(settings)` factory reads `LLM_PROVIDER` env var to instantiate the right backend
- Prompt templates live in `src/engine/prompts/` as Python files that build the prompt string
- `TranscriptAgent` orchestrates transcript analysis: builds prompt, calls provider with JSON schema, retries on parse failure
- All LLM responses that result in write actions must pass through the Approval Engine first
- Gemini limitation: does not support JSON Schema union types (`["string", "null"]`) — use plain types with descriptive defaults
- Gemini uses `responseMimeType: application/json` + `responseSchema` for structured output; Ollama uses `format` parameter

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
- Schema and migrations in `src/database.py` (includes ALTER TABLE migrations run at startup)
- Tables: `projects`, `approval_log`, `approval_queue`, `transcript_cache`, `transcript_suggestions`, `releases`, `release_documents`, `config`

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
LLM_PROVIDER=gemini               # or: ollama
LLM_API_KEY=your-llm-key          # Gemini API key (not needed for Ollama)
LLM_MODEL=gemini-2.5-flash        # or: llama3.3:70b for Ollama
LLM_BASE_URL=http://localhost:11434  # Only needed for Ollama
EQMS_DRAFT_SPACE_ID=...           # Confluence space ID for draft DHF documents
EQMS_RELEASED_SPACE_ID=...        # Confluence space ID for released DHF documents
DB_PATH=seat.db                    # Optional, defaults to seat.db
```

## Transcript Workflow

The transcript analysis pipeline is the first LLM-powered feature. It follows a two-step approval gating model for regulatory traceability.

### Flow

```
Upload (.vtt/.txt/.docx)
  → TranscriptParser.parse() → store in transcript_cache
  → TranscriptService.analyze_transcript()
      → gather_project_context() (parallel: Jira risks/decisions + Confluence Charter/XFT)
      → TranscriptAgent.analyze_transcript() (LLM call with structured JSON output)
  → Store suggestions in transcript_suggestions (status=pending)
  → User reviews suggestions (accept/reject per item, or Accept All)
  → accept_suggestion() patches payload with live project data → ApprovalEngine.propose()
  → User approves in Approval Queue
  → ApprovalEngine.approve_and_execute() → Jira/Confluence connectors
```

### Suggestion Types

| Type | Action | Target |
|---|---|---|
| `risk` | `CREATE_JIRA_ISSUE` | RISK project, Risk type (id `10832`), child of PROG Goal |
| `decision` | `CREATE_JIRA_ISSUE` | RISK project, Project Issue type (id `12499`), child of PROG Goal |
| `xft_update` | `UPDATE_CONFLUENCE_PAGE` | XFT page (append meeting notes) |
| `charter_update` | `UPDATE_CONFLUENCE_PAGE` | Charter page (update section) |

### Key Design Decisions

- **Payload refresh at accept time:** When a suggestion is accepted, `accept_suggestion()` patches the stored payload with current project data (goal key, fix versions, Confluence page IDs). This prevents stale data from incomplete spin-ups baking into suggestions.
- **Confluence append mode:** XFT updates use `append_mode: true` — at execution time, the current page body is fetched and the new content is appended, preventing overwrites of changes made between suggestion and approval.
- **Jira ADF format:** Risk/decision descriptions, Impact Analysis (`customfield_11166`), and Mitigation/Control (`customfield_11342`) are all in Atlassian Document Format. ADF builder helpers are in `src/engine/prompts/transcript.py`.
- **Token budget:** Transcripts truncated to ~20K chars; existing risks/decisions as key+summary only; Charter/XFT content last 3K chars each. Total ~30K tokens.

## Important Notes

- This is a single-user application running locally
- All write actions to Jira/Confluence require explicit user approval
- The LLM provider is abstracted — the codebase should not have provider-specific code outside of `src/engine/agent.py` and `src/config.py`
- Sample data in `samples/` contains real Jira field structures — reference these when building connectors
- The `field-name-to-id.json` mapping is essential for working with Jira custom fields
