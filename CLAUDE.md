# Project Seat

An AI-assisted project management cockpit for medical device software engineering projects. Runs locally as a Python web application, connecting to Atlassian cloud tools via REST APIs, with an LLM as the reasoning engine.

## Tech Stack

- **Language:** Python 3.12+
- **Web framework:** FastAPI + Uvicorn
- **Frontend:** HTMX + Jinja2 templates + Chart.js (dashboard doughnuts, stacked bars, burnup charts)
- **Database:** SQLite (via sqlite3 stdlib, no ORM)
- **HTTP client:** httpx (async)
- **LLM:** Gemini 2.5 Flash (default) or Ollama — provider-agnostic via `src/engine/agent.py`
- **Package management:** uv (preferred) or pip + venv

## Architecture

The application has four layers:

1. **Web Frontend** — FastAPI + HTMX. Current views: Pipeline (phases overview), Project Detail (dashboard/features/documents/approvals/team progress), Approval Queue, Project Spin-Up Wizard, Project Import, Transcript Analysis, Charter Update, Health Review, CEO Review, Closure Report.
2. **Core Engine** — Approval Engine (queue + gate all write actions), LLM Agent Layer (provider-agnostic interface with prompt templates + structured output), Orchestrator (task scheduling framework, wired into lifespan).
3. **API Connectors** — Thin wrappers around Jira, Confluence, and (future) Salesforce REST APIs. Each connector handles auth, pagination, rate limiting, error handling.
4. **Local Data Layer** — SQLite for state/config/audit trail. `.env` for API keys.

Key capabilities: project spin-up, release scope-freeze tracking, DHF/EQMS document tracking (draft vs released), product ideas (PI) board integration, LLM-powered transcript analysis with two-step approval gating, LLM-powered Charter update with two-step Q&A flow, LLM-powered project health review with two-step Q&A flow, LLM-powered CEO Review output with hybrid data tables + commentary, LLM-powered project closure report with full lifecycle data + lessons learned, iterative risk/decision refinement with multi-round Q&A, per-team version progress tracking with burnup charts, Jira Plans timeline embed, typeahead search for Atlassian resource linking.

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
│   │   ├── agent.py             # LLM agent layer (provider protocol, factory, TranscriptAgent, CharterAgent, HealthReviewAgent, RiskRefineAgent)
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
│   │       ├── health_review.py     # Health review: questions + review prompts, JSON schemas
│   │       ├── ceo_review.py        # CEO review: questions + review prompts, JSON schemas
│   │       ├── closure.py           # Closure report: questions + report prompts, JSON schemas
│   │       ├── risk_refine.py       # Risk/decision refinement: quality criteria, Q&A loop schema
│   │       └── (planned: release_plan.py, estimate_check.py — see docs/feature-backlog.md)
│   ├── repositories/            # Data access layer (all raw SQL lives here)
│   │   ├── __init__.py
│   │   ├── project_repo.py      # projects table CRUD
│   │   ├── approval_repo.py     # approval_queue + approval_log tables
│   │   ├── transcript_repo.py   # transcript_cache + transcript_suggestions tables
│   │   ├── charter_repo.py      # charter_suggestions table
│   │   ├── review_repo.py       # health_reviews + ceo_reviews tables
│   │   ├── closure_repo.py      # closure_reports table
│   │   ├── release_repo.py      # releases + release_documents tables
│   │   ├── snapshot_repo.py     # team_progress_snapshots table
│   │   └── config_repo.py       # config table (if used)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── spinup.py            # Project spin-up wizard logic
│   │   ├── dashboard.py         # Dashboard data aggregation
│   │   ├── dhf.py               # DHF/EQMS document tracking (draft vs released)
│   │   ├── import_project.py    # Import existing projects from Jira/Confluence
│   │   ├── release.py           # Release scope-freeze and document tracking
│   │   ├── transcript.py        # LLM analysis, suggestion management (delegates parsing to transcript_parser)
│   │   ├── transcript_parser.py # File format parsing (.vtt/.txt/.docx), no async/DB/service deps
│   │   ├── _transcript_helpers.py # Shared helpers for transcript + risk refinement services
│   │   ├── risk_refinement.py   # Iterative risk/decision refinement via LLM Q&A
│   │   ├── project_context.py   # Centralised parallel context-gathering for all LLM services
│   │   ├── charter.py           # Charter section fetch, LLM Q&A, edit proposals, suggestion management
│   │   ├── health_review.py     # Health review: context gathering, LLM Q&A, review persistence
│   │   ├── ceo_review.py        # CEO review: data gathering, LLM Q&A, XHTML render, publish
│   │   ├── closure.py           # Closure report: data gathering, LLM Q&A, XHTML render, publish
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
│   │   │   ├── charter.py          # Charter view, LLM Q&A, edit proposals, accept/reject
│   │   │   ├── health_review.py    # Health review page, LLM Q&A, review output
│   │   │   ├── ceo_review.py      # CEO review page, LLM Q&A, preview, accept/reject
│   │   │   ├── closure.py        # Closure report page, LLM Q&A, preview, accept/reject
│   │   │   ├── settings.py        # Project settings page
│   │   │   ├── health.py          # API health check endpoint (/api/health)
│   │   │   └── typeahead.py       # Typeahead search endpoints for Atlassian resources
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
│   │   │   ├── project_health_review.html      # Health review page + past reviews
│   │   │   ├── project_ceo_review.html         # CEO review page + PM notes + past reviews
│   │   │   ├── project_closure.html           # Closure report page + PM notes + past reports
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
│   │   │       ├── charter_suggestion_row.html  # Individual charter edit accept/reject
│   │   │       ├── health_review_questions.html # Health review clarifying questions form
│   │   │       ├── health_review_output.html    # Health review structured output
│   │   │       ├── ceo_review_questions.html   # CEO review clarifying questions form
│   │   │       ├── ceo_review_preview.html     # CEO review preview with accept/reject
│   │   │       ├── ceo_review_row.html         # Individual past CEO review row
│   │   │       ├── closure_questions.html     # Closure report clarifying questions form
│   │   │       ├── closure_preview.html       # Closure report preview with accept/reject
│   │   │       ├── closure_row.html           # Individual past closure report row
│   │   │       ├── risk_refine_panel.html      # Risk/decision refinement Q&A panel
│   │   │       ├── typeahead_input.html       # Reusable typeahead input macro
│   │   │       └── typeahead_results.html     # Typeahead search results partial
│   │   └── static/              # CSS + JS + bundled vendor libs
│   │       ├── style.css
│   │       ├── typeahead.js     # Typeahead keyboard nav and selection logic
│   │       └── vendor/
│   │           ├── htmx.min.js      # HTMX 2.0.4 (bundled for offline)
│   │           └── chart.umd.min.js # Chart.js 4.x UMD (bundled for offline)
│   └── models/
│       ├── __init__.py
│       ├── project.py           # Project data models
│       ├── approval.py          # Approval queue item models
│       ├── jira.py              # Jira ticket data models
│       ├── dashboard.py         # Dashboard view models
│       ├── dhf.py               # DHF document models
│       ├── release.py           # Release and scope-freeze models
│       ├── transcript.py        # Transcript, suggestion, and project context models
│       ├── charter.py           # Charter suggestion status and dataclass
│       ├── ceo_review.py       # CEO review status and dataclass
│       └── closure.py          # Closure report status and dataclass
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
    │   ├── test_health_review_agent.py  # HealthReviewAgent questions + review tests
    │   ├── test_risk_refine_agent.py   # RiskRefineAgent refinement loop tests
    │   ├── test_closure_agent.py    # ClosureAgent questions + report tests
    │   ├── test_orchestrator.py
    │   └── test_providers/
    │       ├── __init__.py
    │       ├── test_gemini.py       # Gemini provider unit tests
    │       └── test_ollama.py       # Ollama provider unit tests
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
    │   ├── test_health_review.py    # Health review service tests
    │   ├── test_ceo_review.py       # CEO review service + agent + route tests
    │   ├── test_closure.py          # Closure report service tests
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
        ├── test_routes_health_review.py  # Health review route tests
        ├── test_routes_team_progress.py  # Team progress route tests
        ├── test_routes_closure.py      # Closure report route tests
        ├── test_routes_typeahead.py     # Typeahead search route tests
        └── test_routes_health.py       # API health check route tests
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
- `HealthReviewAgent` orchestrates project health reviews via two-step LLM interaction: `ask_questions()` identifies data gaps, `generate_review()` returns structured assessment — read-only, no approval queue needed
- `CeoReviewAgent` orchestrates CEO status updates via two-step LLM interaction: `ask_questions()` identifies gaps in 2-week data, `generate_review()` returns structured update with health indicator, commentary, escalations, and milestones — publishes to Confluence via approval queue
- `ClosureAgent` orchestrates project closure reports via two-step LLM interaction: `ask_questions()` identifies gaps in lessons learned/delivery assessment/success criteria, `generate_report()` returns narrative sections (delivery outcome, success criteria, lessons learned) — deterministic data tables pre-computed, published to Confluence via approval queue
- `RiskRefineAgent` iteratively refines transcript-extracted risks/decisions via a single `refine()` method: evaluates against ISO 14971 quality criteria, asks targeted questions, incorporates answers, repeats until satisfied (max 5 rounds)
- All LLM responses that result in write actions must pass through the Approval Engine first
- Gemini limitation: does not support JSON Schema union types (`["string", "null"]`) — use plain types with descriptive defaults
- Gemini limitation: 2.5 Flash uses "thinking" tokens that count against `maxOutputTokens` — use 16384+ for structured output to avoid truncation
- Gemini uses `responseMimeType: application/json` + `responseSchema` for structured output; Ollama uses `format` parameter
- Gemini provider logs `finishReason` warnings when response is truncated (`MAX_TOKENS`, `SAFETY`, etc.)

### Approval Engine
- Every write action (creating Jira tickets, updating Confluence pages, etc.) requires user approval
- The approval queue stores the proposed action, the source context (what triggered it), and a preview of what will be created/changed
- Approved actions are logged in SQLite for audit trail
- This is critical for regulatory traceability — a human approved every change

### Frontend
- HTMX for reactivity — no JavaScript framework
- Chart.js for data visualisation: doughnut charts (risk/DHF on dashboard), stacked horizontal bars (team breakdown on dashboard), burnup charts (team progress page)
- Jinja2 templates in `src/web/templates/`
- Keep templates simple; business logic lives in services, not in templates or routes
- Routes are thin — validate input, call a service, return a template
- LLM loading indicators use animated CSS spinners (opacity-based, compatible with HTMX's built-in `.htmx-indicator` mechanism) and `hx-disabled-elt` for button disabling during requests
- Dashboard layout uses CSS Grid with `.dash-*` class prefix: hero bar, 4-column metric cards, full-width team breakdown, 3-column activity/links section. Responsive at 768px (2-col) and 480px (1-col).
- **Typeahead inputs** use the `typeahead_input` Jinja2 macro from `partials/typeahead_input.html`. Import with `{% from "partials/typeahead_input.html" import typeahead_input %}` and call with `name`, `label`, `value`, `endpoint`, `placeholder`, `display_value`, and optional `params` dict. The macro generates a visible search input (HTMX-powered), a hidden input for form submission, and a results dropdown. JS logic is in `static/typeahead.js`. Endpoints are under `/api/typeahead/` (confluence-pages, jira-issues, jira-projects, jira-versions).
- **Dark mode** uses `data-theme` attribute on `<html>` (`"light"` or `"dark"`). All colors are CSS custom properties defined in `:root` (light) and `[data-theme="dark"]` (dark) blocks in `style.css`. Never use hardcoded color values — always reference a `var(--*)` token. The toggle button is in `base.html` with localStorage persistence and OS preference detection via `prefers-color-scheme`. Chart.js charts read colors via `getThemeColor('--var-name')` and rebuild on the `theme-changed` custom event. Utility classes: `.text-secondary`, `.text-tertiary`, `.text-muted`.
- **Static asset cache-busting** uses MD5 content hashes computed at import time in `deps.py`. The `static_versions` dict is a Jinja2 global — use `?v={{ static_versions.get('filename', '0') }}` in templates. New static files are automatically picked up via `rglob`.
- **Offline CDN assets** — HTMX and Chart.js are bundled in `static/vendor/` and served locally. Google Fonts remains on CDN (cosmetic, has system font fallback).
- **Page progress bar** — `<div id="page-progress">` in `base.html` with inline JS: animates on `<a>` clicks (non-HTMX, non-external) and on `htmx:beforeRequest`/`htmx:afterRequest` events. CSS in `style.css` (`.page-progress`, `.active`, `.done`).
- **Navigation tab grouping** — Analysis tabs (Transcripts, Charter, Health, CEO Review) are wrapped in `.nav-dropdown`. On desktop (`>1024px`), `.nav-dropdown-menu` uses `display: contents` so children render flat in the flex row. On `≤1024px`, it becomes a positioned dropdown via `:focus-within`/`:hover`. No JS needed.
- **Dependency injection** — All service/connector instantiation in routes uses `Depends()` with factory functions from `src/web/deps.py`. Never instantiate services directly in route functions. When adding a new service, add a factory in `deps.py` and use `Depends(get_new_service)` in the route signature.

### Repository Layer
- All raw SQL lives in `src/repositories/` — services and routes never call `get_db()` directly
- Each repository class takes an optional `db_path` constructor argument, defaulting to `src.config.settings.db_path` (lazy lookup for test compatibility)
- Services accept optional repository parameters in their constructors for dependency injection in tests:
  ```python
  class TranscriptService:
      def __init__(self, repo: TranscriptRepository | None = None, ...):
          self._repo = repo or TranscriptRepository(self._settings.db_path)
  ```
- Route-level project updates go through `DashboardService.update_project()` (DI-injected) rather than creating repositories directly

### ProjectContextService
- `src/services/project_context.py` centralises parallel context-gathering used by transcript, health review, CEO review, and risk refinement services
- Callers pass boolean flags to select which data sources to fetch (e.g., `risks=True, charter=True, snapshots=True`)
- Each source fails independently — one connector error does not block the others
- Individual services retain thin `gather_*_context()` wrappers that call `ProjectContextService.gather()` and adapt the result

### Database
- SQLite via stdlib `sqlite3` — no ORM
- Schema and migrations in `src/database.py` (includes ALTER TABLE migrations run at startup)
- Tables: `projects`, `approval_log`, `approval_queue`, `transcript_cache`, `transcript_suggestions`, `charter_suggestions`, `releases`, `release_documents`, `config`, `team_progress_snapshots`, `health_reviews`, `ceo_reviews`, `closure_reports`

### Testing
- Use pytest
- Mock API responses using sample data from `samples/`
- Test connectors against saved JSON responses, not live APIs
- Test the agent layer with known prompts and expected structured outputs

### Documentation Updates on Feature Commits
When committing a new feature or significant change, **always update the following project documentation** as part of the same commit:
1. **`README.md`** — Update the Features list if a new user-visible capability was added. Remove from "Planned / Upcoming" if it was listed there.
2. **`CLAUDE.md`** — Update the relevant sections: Tech Stack (if new dependencies), Architecture (if new views/layers), Folder Structure (if new files), Key Conventions (if new patterns). Keep descriptions factual and concise.
3. **`docs/feature-backlog.md`** — Move the feature from its planned section to the "Completed Features" list at the bottom. Include a one-line summary of what was delivered.
4. **Folder Structure in CLAUDE.md** — Add any new files or directories created by the feature.

This ensures project docs stay in sync with the codebase without requiring a separate documentation pass.

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

## Health Review Workflow

The health review is the third LLM-powered feature. It uses the same two-step Q&A pattern as Charter Update, but is read-only (no write actions, no approval queue).

### Flow

```
User clicks "Start Health Review"
  → POST /health-review/ask → HealthReviewService.generate_questions()
      → gather_all_context() (parallel: summary, initiatives, PI, team progress,
        snapshots, DHF, transcript context, releases, meeting summaries)
      → HealthReviewAgent.ask_questions() (LLM call #1: identify data gaps)
  → UI shows clarifying questions (or auto-submits if none needed)
  → User answers → POST /health-review/analyze → HealthReviewService.generate_review()
      → HealthReviewAgent.generate_review() (LLM call #2: structured review)
  → Persist review in health_reviews table
  → Display structured output (rating, concerns, positives, next actions)
```

### Output Structure

- **health_rating**: Green / Amber / Red
- **health_rationale**: One-line summary
- **top_concerns**: Ranked list with area, severity, evidence, recommendation
- **positive_observations**: Things going well
- **questions_for_pm**: Things warranting investigation
- **suggested_next_actions**: Concrete next steps

### Key Design Decisions

- **Read-only:** No write actions to Jira/Confluence — purely advisory, no approval queue needed
- **Comprehensive context:** Ingests all available project data (9 parallel fetches with graceful error handling per source)
- **Persisted reviews:** Stored in `health_reviews` table for historical comparison, displayed on the Health Review page
- **High token budget:** Uses `maxOutputTokens: 16384` because Gemini 2.5 Flash thinking tokens count against the output budget

## CEO Review Workflow

The CEO Review is the fourth LLM-powered feature. It uses the same two-step Q&A pattern as Health Review, but with a **last-2-weeks lens** and **Confluence publishing** via the approval queue.

### Flow

```
User enters optional PM notes → clicks "Generate CEO Review"
  → POST /ceo-review/ask → CeoReviewService.generate_questions()
      → gather_ceo_context() (9 parallel fetches: summary, initiatives, team reports,
        snapshots (14d), DHF docs, releases, new risks (2w), new decisions (2w), meetings)
      → compute_metrics() (deterministic: filter DHF by 2w, burnup delta, team progress)
      → CeoReviewAgent.ask_questions() (LLM call #1: identify gaps)
  → UI shows clarifying questions (or auto-submits if none needed)
  → User answers → POST /ceo-review/analyze → CeoReviewService.generate_review()
      → CeoReviewAgent.generate_review() (LLM call #2: structured update)
  → render_confluence_xhtml() → save_review() in ceo_reviews table
  → User reviews preview (data tables + LLM commentary)
  → Accept → accept_review() → ApprovalEngine.propose(UPDATE_CONFLUENCE_PAGE, append_mode=true)
  → User approves in Approval Queue → appended to CEO Review Confluence page
```

### Output Structure

- **health_indicator**: On Track / At Risk / Off Track
- **decisions_commentary**: Summary of new decisions
- **risks_commentary**: Summary of new risks and patterns
- **development_commentary**: Dev progress, velocity, blockers
- **documentation_commentary**: DHF progress, recently updated docs
- **escalations**: Issues needing leadership attention (issue, impact, ask)
- **next_milestones**: Upcoming concrete milestones

### Key Design Decisions

- **Hybrid output:** Deterministic data tables (new risks/decisions, team progress, DHF) combined with LLM-generated commentary — numbers are pre-computed, LLM writes narrative only
- **Last-2-weeks focus:** JQL `created >= -2w` for new risks/decisions, burnup snapshots limited to 14 days, DHF filtered by `last_modified`
- **Confluence append:** Uses existing `append_mode` in approval engine — fetches current page body at execution time and appends XHTML
- **Auto-discovery:** CEO Review page discovered from Charter ancestors: Charter → ancestors → Program → children → "CEO Review" title match
- **PM notes:** Free-form textarea for qualitative context (blockers, escalations, team dynamics) passed to both LLM steps

## Risk Refinement Workflow

The risk refinement feature adds iterative Q&A refinement for transcript-extracted risks and decisions, evaluating them against ISO 14971 quality criteria.

### Flow

```
User clicks "Refine" on a risk/decision suggestion
  → POST /{tid}/suggestions/{sid}/refine → TranscriptService.start_risk_refinement()
      → _extract_risk_draft() (parse ADF payload back to plain text fields)
      → gather_project_context() (existing risks/decisions for dedup)
      → RiskRefineAgent.refine() (LLM call: evaluate + ask questions)
  → UI shows quality assessment, current draft preview, question form
  → User answers → POST /{tid}/suggestions/{sid}/refine/answer
      → TranscriptService.continue_risk_refinement() (next round)
      → RiskRefineAgent.refine() (LLM call with accumulated Q&A)
  → Loop until satisfied or max 5 rounds
  → User clicks "Apply Refinement" → POST /{tid}/suggestions/{sid}/refine/apply
      → TranscriptService.apply_refinement() (rebuild Jira payload, update DB)
  → Suggestion row re-renders with refined content
  → User can Accept/Reject as usual
```

### Key Design Decisions

- **Single-method agent:** `RiskRefineAgent.refine()` handles both initial evaluation and follow-up rounds (unlike the two-step Charter/Health agents)
- **Stateless Q&A:** No new DB tables — state carried via hidden form fields (`risk_draft` JSON, `qa_history` JSON, `round_number`), same pattern as Charter Q&A
- **ADF round-trip:** `_extract_risk_draft()` parses the Jira ADF payload back to plain text for the LLM; `apply_refinement()` rebuilds ADF from the refined fields
- **Max 5 rounds:** `continue_risk_refinement()` forces `satisfied=true` at round 5 without an LLM call
- **Bail-out options:** "Apply Current Draft" applies partial refinement at any point; "Discard" removes the panel without changes

## Closure Report Workflow

The closure report is the fifth LLM-powered feature. It uses the same two-step Q&A pattern as CEO Review, with **full project lifecycle data** and **Confluence page creation** via the approval queue.

### Flow

```
PM enters optional notes → POST /closure/ask
  → ClosureService.generate_questions()
      → gather_closure_context() (parallel: ALL risks, ALL decisions, Charter, XFT,
        initiatives, team reports, full snapshots (365d), DHF docs, releases, meetings)
      → compute_closure_metrics() (deterministic: timeline, scope, risk/decision tables,
        DHF final status, team progress)
      → ClosureAgent.ask_questions() (LLM call #1: identify gaps in lessons learned,
        delivery assessment, success criteria, stakeholder satisfaction)
  → UI shows clarifying questions (or auto-submits if none)
  → PM answers → POST /closure/analyze
      → ClosureAgent.generate_report() (LLM call #2: narrative sections)
  → render_confluence_xhtml() → save to closure_reports table
  → PM reviews preview (data tables + LLM narrative)
  → Accept → ClosureService.accept_report()
      → ApprovalEngine.propose(CREATE_CONFLUENCE_PAGE) — child of Charter page
  → PM approves in Approval Queue → Confluence page created
```

### Output Structure

- **final_delivery_outcome**: 3-5 sentence narrative (LLM)
- **success_criteria_assessments**: Table with criterion/expected/actual/status/comments (LLM)
- **lessons_learned**: Categorised table with description/triggers/recommendations/owner (LLM)
- **timeline**: Planned vs Actual vs Deviation table (deterministic)
- **scope_delivered / scope_not_delivered**: Lists from initiative status (deterministic)
- **all_risks / all_decisions**: Full lifecycle tables (deterministic)
- **team_progress**: Final per-team SP breakdown (deterministic)
- **dhf_total / dhf_released**: Final document completion (deterministic)

### Key Design Decisions

- **Full lifecycle data:** Unlike CEO Review (2-week lens), closure gathers ALL risks/decisions (no date filter), 365 days of snapshots, and up to 20 meeting summaries
- **Hybrid output:** Deterministic data tables (timeline, scope, risks, DHF) combined with LLM-generated narrative (delivery outcome, success criteria, lessons learned)
- **Confluence page creation:** Uses `CREATE_CONFLUENCE_PAGE` (not update) — the closure report is a new child page of the Charter page, alongside the XFT page
- **Stateless Q&A:** Same pattern as CEO Review — no DB storage for intermediate Q&A state
- **Lessons learned categories:** Planning, Team, Technical, Implementation, Commercial, Testing, Change Management, Vendor, Documentation

## Feature Backlog & Technical Debt

All planned features, improvements, and technical debt are tracked in `docs/feature-backlog.md`. When asked about remaining work, what to build next, or the project roadmap, always consult that file for the authoritative list. The backlog is grouped by theme (LLM features, Reporting, Dashboard/UI, Infrastructure) and includes a Completed section for reference.

## Important Notes

- This is a single-user application running locally
- All write actions to Jira/Confluence require explicit user approval
- The LLM provider is abstracted — the codebase should not have provider-specific code outside of `src/engine/agent.py` and `src/config.py`
- Sample data in `samples/` contains real Jira field structures — reference these when building connectors
- The `field-name-to-id.json` mapping is essential for working with Jira custom fields
