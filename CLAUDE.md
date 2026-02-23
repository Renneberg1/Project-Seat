# Project Seat

An AI-assisted project management cockpit for medical device software engineering projects. Runs locally as a Python web application, connecting to Atlassian cloud tools via REST APIs, with an LLM as the reasoning engine.

## Tech Stack

- **Language:** Python 3.12+
- **Web framework:** FastAPI + Uvicorn
- **Frontend:** HTMX + Jinja2 templates + Chart.js (burnup charts)
- **Database:** SQLite (via sqlite3 stdlib, no ORM)
- **HTTP client:** httpx (async)
- **LLM:** Gemini 2.5 Flash (default) or Ollama — provider-agnostic via `src/engine/agent.py`
- **Package management:** uv (preferred) or pip + venv

## Architecture

The application has four layers:

1. **Web Frontend** — FastAPI + HTMX. Current views: Pipeline (phases overview), Project Detail (dashboard/features/documents/approvals/team progress), Approval Queue, Project Spin-Up Wizard, Project Import, Transcript Analysis, Charter Update.
2. **Core Engine** — Approval Engine (queue + gate all write actions), LLM Agent Layer (provider-agnostic interface with prompt templates + structured output), Orchestrator (task scheduling framework, wired into lifespan).
3. **API Connectors** — Thin wrappers around Jira, Confluence, and (future) Salesforce REST APIs. Each connector handles auth, pagination, rate limiting, error handling.
4. **Local Data Layer** — SQLite for state/config/audit trail. `.env` for API keys.

Key capabilities: project spin-up, release scope-freeze tracking, DHF/EQMS document tracking (draft vs released), product ideas (PI) board integration, LLM-powered transcript analysis with two-step approval gating, LLM-powered Charter update with two-step Q&A flow, per-team version progress tracking with burnup charts, Jira Plans timeline embed.

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
├── scripts/
│   └── seed_burnup.py           # Seed script for burnup chart test data
├── docs/
│   ├── architecture.pdf         # System architecture diagram
│   ├── workflow.pdf             # Product workflow diagram
│   ├── feature-backlog.md       # Planned features and technical debt tracker
│   ├── spinup-flow.md           # Spin-up workflow documentation
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
│   │   ├── approval.py          # Approval queue and gating logic
│   │   ├── agent.py             # LLM agent layer (provider protocol, factory, TranscriptAgent, CharterAgent)
│   │   ├── charter_storage_utils.py  # Charter XHTML section extraction and replacement
│   │   ├── orchestrator.py      # Task queue and scheduling (framework implemented, no tasks registered yet)
│   │   ├── providers/
│   │   │   ├── __init__.py
│   │   │   ├── gemini.py        # Gemini provider (httpx, structured output via responseSchema)
│   │   │   └── ollama.py        # Ollama provider (httpx, local inference)
│   │   └── prompts/
│   │       ├── __init__.py
│   │       ├── transcript.py        # Transcript analysis: system prompt, JSON schema, ADF helpers
│   │       ├── charter.py           # Charter update: questions + edits prompts, JSON schemas
│   │       └── (planned: release_plan.py, estimate_check.py — see docs/feature-backlog.md)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── spinup.py            # Project spin-up wizard logic
│   │   ├── dashboard.py         # Dashboard data aggregation
│   │   ├── dhf.py               # DHF/EQMS document tracking (draft vs released)
│   │   ├── import_project.py    # Import existing projects from Jira/Confluence
│   │   ├── release.py           # Release scope-freeze and document tracking
│   │   ├── transcript.py        # Transcript parsing, LLM analysis, suggestion management
│   │   ├── charter.py           # Charter section fetch, LLM Q&A, edit proposals, suggestion management
│   │   ├── team_progress.py     # Per-team version progress tracking (JQL-based)
│   │   └── team_snapshot.py     # Daily team progress snapshots for burnup charts
│   ├── web/
│   │   ├── __init__.py
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── approval.py
│   │   │   ├── import_project.py
│   │   │   ├── phases.py           # Pipeline/phases overview
│   │   │   ├── project.py          # Project detail (dashboard/features/docs/approvals)
│   │   │   ├── spinup.py
│   │   │   ├── transcript.py       # Upload, analyze, accept/reject suggestions
│   │   │   └── charter.py          # Charter view, LLM Q&A, edit proposals, accept/reject
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
│   │   │   ├── charter.html                     # Charter sections view + LLM update form
│   │   │   ├── project_team_progress.html       # Per-team version progress + burnup chart
│   │   │   └── partials/
│   │   │       ├── approval_pending.html
│   │   │       ├── approval_row.html
│   │   │       ├── import_confirm.html
│   │   │       ├── project_card.html
│   │   │       ├── transcript_parsed.html       # Parsed preview with Analyze button
│   │   │       ├── transcript_suggestions.html  # Suggestions panel with Accept All
│   │   │       ├── suggestion_row.html          # Individual suggestion accept/reject
│   │   │       ├── charter_questions.html       # LLM clarifying questions form
│   │   │       ├── charter_suggestions.html     # Charter edit proposals with Accept All
│   │   │       └── charter_suggestion_row.html  # Individual charter edit accept/reject
│   │   └── static/              # CSS (JS loaded from CDN: HTMX, Chart.js)
│   │       └── style.css
│   └── models/
│       ├── __init__.py
│       ├── project.py           # Project data models
│       ├── approval.py          # Approval queue item models
│       ├── jira.py              # Jira ticket data models
│       ├── dashboard.py         # Dashboard view models
│       ├── dhf.py               # DHF document models
│       ├── release.py           # Release and scope-freeze models
│       ├── transcript.py        # Transcript, suggestion, and project context models
│       └── charter.py           # Charter suggestion status and dataclass
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
    │   ├── test_charter_storage_utils.py  # Charter XHTML parsing + replacement tests
    │   ├── test_charter_agent.py    # CharterAgent questions + edits tests
    │   └── test_orchestrator.py
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
    │   ├── test_transcript.py       # Parser + service tests
    │   ├── test_charter.py          # Charter service + suggestion workflow tests
    │   ├── test_team_progress.py    # Team progress service tests
    │   └── test_team_snapshot.py    # Snapshot service tests
    └── test_web/
        ├── test_routes_approval.py
        ├── test_routes_import.py
        ├── test_routes_phases.py
        ├── test_routes_project.py
        ├── test_routes_spinup.py
        ├── test_routes_transcript.py
        ├── test_routes_charter.py   # Charter route contract tests
        └── test_routes_team_progress.py  # Team progress route tests
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
- `CharterAgent` orchestrates Charter updates via two-step LLM interaction: `ask_questions()` identifies gaps, `propose_edits()` returns section replacements — both retry on JSON parse failure
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
- Chart.js for data visualisation (burnup charts on team progress page)
- Jinja2 templates in `src/web/templates/`
- Keep templates simple; business logic lives in services, not in templates or routes
- Routes are thin — validate input, call a service, return a template

### Database
- SQLite via stdlib `sqlite3` — no ORM
- Schema and migrations in `src/database.py` (includes ALTER TABLE migrations run at startup)
- Tables: `projects`, `approval_log`, `approval_queue`, `transcript_cache`, `transcript_suggestions`, `charter_suggestions`, `releases`, `release_documents`, `config`, `team_progress_snapshots`

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
2. Fix version in RISK project and each selected team project (per-team version mapping: `{PROJECT_KEY: version_name}`, teams can use different version names)
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

## Charter Update Workflow

The Charter update pipeline is the second LLM-powered feature. It uses a two-step LLM interaction (clarifying questions, then precise edits) with the same approval gating model as transcripts.

### Charter XHTML Structure

The Charter page is stored in Confluence as XHTML with a `<table>` inside an `<ac:structured-macro ac:name="details">` block. Each `<tr>` has a `<th>` (section name) and `<td>` (content). **Project Scope** uses `rowspan="2"` — one `<th>` spanning two rows for "In Scope" and "Out of Scope" sub-sections.

The `charter_storage_utils.py` module handles parsing and modification:
- `extract_sections(storage_body)` → `[{name, content}]` (plain text, handles rowspan)
- `replace_section_content(storage_body, section_name, new_content)` → modified XHTML

### Flow

```
User enters free-form text describing changes
  → POST /charter/ask → CharterService.generate_questions()
      → CharterAgent.ask_questions() (LLM call #1: identify gaps)
  → UI shows clarifying questions with answer fields
  → User answers → POST /charter/analyze → CharterService.analyze_charter_update()
      → CharterAgent.propose_edits() (LLM call #2: section replacements)
  → Store suggestions in charter_suggestions (status=pending)
  → User reviews/accepts/rejects each edit
  → accept_suggestion() → ApprovalEngine.propose() with section_replace_mode payload
  → User approves in Approval Queue
  → ApprovalEngine.approve_and_execute() → replace_section_content() → Confluence update
```

If the LLM returns no questions (user input is already complete), the questions partial auto-submits to the analyze endpoint, skipping the Q&A step.

### Key Design Decisions

- **Two-step LLM interaction:** Step 1 (questions) ensures completeness before Step 2 (edits) proposes changes. Each step has its own system prompt and JSON schema.
- **Stateless Q&A:** No DB storage for the intermediate Q&A state — the questions form carries `user_input` as a hidden field and answers as form fields. Only the final suggestions are persisted.
- **Section replace mode:** The approval engine's `UPDATE_CONFLUENCE_PAGE` action supports `section_replace_mode: true` — at execution time, the current page body is fetched and `replace_section_content()` swaps the target `<td>` in-place, preventing overwrites of other sections changed between suggestion and approval.
- **Payload refresh at accept time:** Like transcripts, `accept_suggestion()` patches the `page_id` from current project data to prevent stale Confluence page references.

## Feature Backlog & Technical Debt

All planned features, improvements, and technical debt are tracked in `docs/feature-backlog.md`. When asked about remaining work, what to build next, or the project roadmap, always consult that file for the authoritative list. The backlog is grouped by theme (LLM features, Reporting, Dashboard/UI, Infrastructure) and includes a Completed section for reference.

## Important Notes

- This is a single-user application running locally
- All write actions to Jira/Confluence require explicit user approval
- The LLM provider is abstracted — the codebase should not have provider-specific code outside of `src/engine/agent.py` and `src/config.py`
- Sample data in `samples/` contains real Jira field structures — reference these when building connectors
- The `field-name-to-id.json` mapping is essential for working with Jira custom fields
