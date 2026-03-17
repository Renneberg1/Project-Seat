# Project Seat — Feature Backlog

Tracking planned features, improvements, and technical debt. Grouped by theme, roughly prioritised within each section. Items marked **(NEW)** were identified in the Feb 2026 codebase audit. Items marked **(MAR-2026)** were identified in the Mar 2026 codebase scan.

---

## LLM-Powered Features

### LLM XFT Minutes Setup
LLM-assisted creation and formatting of XFT meeting minutes. Given a transcript or direct input, the LLM:
1. Structures minutes into the XFT template format (attendees, agenda, discussion, action items, decisions)
2. Cross-references action items against existing Jira tickets
3. Proposes the formatted minutes as an `UPDATE_CONFLUENCE_PAGE` (append mode) to the XFT page

- New prompt template: `src/engine/prompts/xft_minutes.py`
- Reuses `gather_project_context()` for existing ticket awareness
- Could share the transcript upload flow — after analysis, user chooses "Generate XFT Minutes" as an alternative to individual suggestion review

### Release Planning Assistant
LLM-assisted release plan drafting with estimate gap detection. Analyses the initiative/epic/task hierarchy for a project, identifies missing estimates, flags scope risks, and drafts a release timeline.

- Prompt template: `src/engine/prompts/release_plan.py` (stub exists in CLAUDE.md, file missing)
- Inputs: Jira initiative hierarchy + epic estimates + sprint data
- Outputs: Release plan document, list of missing estimates, scope risk warnings

### Estimate Gap Detection
Scan a project's Jira hierarchy and flag epics/tasks missing story points or time estimates. LLM provides confidence-weighted suggestions for likely estimate ranges based on similar past tickets.

- Prompt template: `src/engine/prompts/estimate_check.py` (stub exists in CLAUDE.md, file missing)

### LLM Rate Limit Tracking **(NEW)**
Track daily Gemini API calls and surface the remaining quota in the UI. Warn when approaching the 250 RPD free-tier limit; block with a clear message when exhausted, rather than surfacing a raw API error.

- Counter in `config` table or in-memory, reset daily
- Badge/indicator in the nav bar or on LLM-powered pages
- Graceful degradation: disable "Analyze" / "Generate" buttons when quota is near

---

## Reporting & Status

### Regular Project Status Reports
Automated periodic status report generation per project. Pulls live data from Jira + Confluence and formats into a standard template:
- Sprint progress (velocity, burndown)
- Risk register changes (new, closed, escalated)
- Decision log updates
- Document completion delta since last report
- XFT meeting summary (from latest transcript analysis)

Delivery: Confluence page update or email-ready format.

### Cross-Project Portfolio View **(NEW)**
A single-page view comparing all active projects side-by-side:
- Health indicator (Green / Amber / Red) per project from latest Health Review
- Key metrics: open risks, DHF %, team velocity trend
- Sortable/filterable table or card grid
- Export to PDF or Confluence for leadership briefings

### Historical Trend Dashboard **(NEW)**
Track key metrics over time per project (risk count, DHF completion %, story points done, health rating changes). Display sparkline charts on the dashboard and a dedicated trend page. Data already exists in `health_reviews`, `team_progress_snapshots`, and `ceo_reviews` tables.

---

## Dashboard & UI

### Pipeline View Enhancements
- Drag-and-drop phase transitions (currently button-based)
- Project health indicator (green/amber/red) based on risk count + timeline status
- Collapsed vs expanded project cards with quick-glance metrics

### Transcript UI Improvements
- Diff preview for Confluence update suggestions (show what will be appended)
- Confidence threshold filter (hide low-confidence suggestions)
- Bulk operations: select multiple suggestions to accept/reject
- Transcript summary card on project dashboard (already partially implemented)

### Notification / Toast System **(NEW)**
Currently success/error feedback uses inline banners that can be missed. A toast notification system (auto-dismissing, stacking) would improve the UX for actions like "Settings saved", "Suggestion accepted", "Approval submitted".

---

## Infrastructure & Technical Debt

### Extract Meetings Route Orchestration into Service Layer **(MAR-2026)**
`reanalyse_recording`, `retry_recording`, and `assign_recording` handlers in `meetings.py:387-571` contain non-trivial orchestration logic (status state machine, project mapping, re-analysis pipeline). This belongs in `ZoomIngestionService`, not in route handlers.

### Add Return Type Hints to Repository and Service Layer **(MAR-2026)**
207 function signatures missing return type annotations, concentrated in:
- All 10 repository files (no return types at all)
- Most service files (`transcript.py`, `charter.py`, `ceo_review.py`, `closure.py`, `risk_refinement.py`, `knowledge.py`, etc.)
- All 100+ FastAPI route handlers (minor, FastAPI doesn't require them)

### Connector Extensions (as needed)
- Jira: project/component listing, bulk operations
- Confluence: page deletion/archival, attachment upload, label management, space operations

### Jira Plans Embed Improvements
- Auto-detect plan URL from Jira API (currently requires manual paste)
- Height/zoom controls on the embedded iframe
- Fallback screenshot or static image when iframe embedding is blocked

### Project Model Extensions (remaining)
The `projects` table could further benefit from:
- `team_lead` / `pm` / `stakeholders` — people tracking
- `target_release_date` — for timeline tracking
- `risk_tolerance` / `risk_budget` — for risk monitoring thresholds

---

## Completed Features (for reference)

- [x] Project Spin-Up (Goal + versions + Charter + XFT via approval queue)
- [x] Project Import (from existing Jira/Confluence)
- [x] Pipeline Dashboard (phase-based project view)
- [x] Release Scope-Freeze (snapshot + document tracking)
- [x] DHF Document Tracking (draft vs released comparison)
- [x] Approval Queue (6 action types, audit trail, retry)
- [x] Product Ideas Integration (PI board version tracking)
- [x] Transcript Analysis (upload .vtt/.txt/.docx, Gemini/Ollama LLM analysis, suggestion review, two-step approval gating, risk/decision/XFT/charter suggestion types)
- [x] LLM Provider Layer (provider-agnostic Protocol, Gemini + Ollama implementations)
- [x] Performance Optimizations (parallel fetches, batched JQL, TTL cache)
- [x] Silent Exception Handling (replaced bare `pass` with `logger.warning()` at all locations)
- [x] Hardcoded Confluence Space (configurable via `CONFLUENCE_SPACE_KEY` env var)
- [x] Goal Description Overwrite (goal_summary preserved alongside Confluence links)
- [x] Partial Failure Logging (execution success/failure logged, batch summaries in approve-all)
- [x] Project Model Extensions (`default_component`, `default_label` columns with transcript fallback)
- [x] Release Audit Logging (lock/unlock/save_documents write to approval_log)
- [x] Task Orchestrator (minimal framework in `src/engine/orchestrator.py`, wired into lifespan)
- [x] Test Coverage Gaps (accept/reject suggestions, retry, append_mode, orchestrator, sample VTT)
- [x] Transcript Direct Input (textarea alternative to file upload)
- [x] LLM Charter Generation / Update (two-step Q&A flow, `CharterAgent`, section-level edits via approval queue)
- [x] LLM Loading Spinners (animated CSS spinner + button disabling on all LLM buttons via HTMX indicators and hx-disabled-elt)
- [x] Re-analyze Button (re-run LLM on same transcript with updated project context)
- [x] Version Report Tracking Per Team (per-team version mapping with auto-detect at import, team progress dashboard with per-version JQL grouping, story point totals)
- [x] Burnup Chart (Chart.js burnup with scope vs done over time, dashed projection to due date, team filter, velocity override)
- [x] Confluence Formatting Guidance (LLM prompts include Confluence-specific formatting instructions for better output quality)
- [x] Risk/Decision Extraction from Arbitrary Text (covered by Transcript Direct Input — textarea accepts any text, not just transcripts)
- [x] Jira Plans Timeline Embed (iframe embed on dashboard, accepts bare URL or `<iframe>` snippet from Jira Plans Share, stored per project, integrated into import and spin-up flows)
- [x] Project Health Review (on-demand LLM health check: two-step Q&A flow, gathers all project data, structured review with Green/Amber/Red rating, concerns, positives, next actions, persisted in `health_reviews` table)
- [x] Dashboard UI Redesign (hero bar with phase/health/countdown, 4 metric cards with Chart.js doughnuts for risks and DHF, scope composition bar with type pills, team % card, full-width team breakdown stacked bars, 3-column activity/links section, responsive at 768px/480px, body widened to 1280px)
- [x] Dark Mode (CSS custom properties for all colors, `data-theme` toggle with localStorage + OS preference, dark palette derived from brand navy, Chart.js chart rebuild on theme change, sun/moon toggle button, FOUC prevention)
- [x] CEO Review Output (fortnightly CEO-level status updates with last-2-weeks lens, hybrid deterministic data tables + LLM commentary, two-step Q&A flow, Confluence append via approval queue, auto-discovery of CEO Review page from Charter ancestors)
- [x] Iterative Risk/Decision Refinement (multi-round LLM Q&A loop to refine transcript-extracted risks/decisions against ISO 14971 quality criteria, max 5 rounds, early bail-out with Apply Current Draft, stateless via hidden form fields)
- [x] Typeahead Resource Linking (search-as-you-type for Confluence pages and Jira issues/projects/versions, reusable Jinja2 macro, vanilla JS keyboard nav, HTMX debounced search, TTL cache, display value resolution on page load, migrated across Settings/Import/Documents pages)
- [x] Extract BaseAgent Class (shared `_generate_with_retry()` and `_strip_fences()` in base class, eliminating ~200 lines of duplication across 5 agents)
- [x] Fix Leaked Connector in `gather_project_context()` (proper `async with` for JiraConnector in transcript service)
- [x] Add Database Indexes (secondary indexes on 8 frequently-queried columns across 7 tables)
- [x] Enable TLS Verification by Default (configurable `VERIFY_SSL` env var, defaults to true)
- [x] Run Orchestrator Task Immediately on Startup (`run_immediately` param fires task before first sleep interval)
- [x] Extract Shared `_render()` Helper (`render_project_page()` in `src/web/deps.py`, removed from 6 route files)
- [x] Extract Q&A Pair Collection Utility (`collect_qa_pairs()` in `src/web/deps.py`, removed from 4 route files)
- [x] HTML-Escape Exception Messages (`html.escape()` on all error banners in 4 route files)
- [x] Enable SQLite WAL Mode (`PRAGMA journal_mode = WAL` in database init)
- [x] Versioned Database Migrations (`schema_versions` table with numbered migration functions, each runs exactly once)
- [x] Cache Context Between Q&A Steps (10-minute TTL cache in health_review and ceo_review services, Step 2 reuses Step 1 data)
- [x] Add ON DELETE CASCADE to Foreign Keys (all FK constraints, simplified `delete_project()` to single DELETE)
- [x] Automatic CSS Cache-Busting (MD5 content-hash query strings on all static assets, computed at import time in `deps.py`)
- [x] Remove Dead Code (verified no dead code — `_project_response()` already removed, `import re` is used)
- [x] Provider Unit Tests (17 tests for Gemini and Ollama providers: response parsing, error handling, schema params, client reuse, close)
- [x] FastAPI Dependency Injection (all service/connector instantiation in routes uses `Depends()` factory functions from `deps.py`)
- [x] API Health Check Endpoint (`GET /api/health` returns JSON connectivity status for DB, Jira, Confluence; 200 ok / 503 degraded)
- [x] Bundle CDN Assets — Offline Resilience (HTMX 2.0.4 and Chart.js 4.x bundled in `static/vendor/` for air-gapped operation)
- [x] Page Navigation Loading State (animated progress bar at top of page for regular navigation and HTMX requests)
- [x] Navigation Tab Grouping (Analysis tabs collapse into dropdown on ≤1024px, flat on desktop; pure CSS via `:focus-within`)
- [x] Service Layer Refactor — Split `transcript.py` (980→450 lines) into `transcript_parser.py`, `_transcript_helpers.py`, and `risk_refinement.py`; extracted `ProjectContextService` consolidating duplicated context-gathering across 3 services; extracted 8 repository files centralising ~60 raw SQL queries (no `get_db()` calls in services/engine/routes)
- [x] Project Closure Report (formal closure report covering delivery outcome, timeline, scope, risk/issue closure, success criteria, and lessons learned; two-step LLM Q&A with hybrid deterministic data tables + LLM narrative; published to Confluence as child of Charter page via approval queue)
- [x] Automatic Zoom Transcript Ingestion (Server-to-Server OAuth connector, on-demand sync via "Sync Zoom" button + startup, auto-pagination, VTT transcript download + Zoom VTT `Name: text` format parsing, recording deduplication, Zoom Inbox page with status filtering)
- [x] Zoom-to-Project Matching (hybrid title match + LLM fallback: substring/fuzzy matching on project names/aliases/team keys, `ZoomMatchAgent` for ambiguous meetings, multi-project mapping, triage queue for unmatched recordings with assign/dismiss/retry)
- [x] Project Knowledge Database (per-project action items + notes + insights from LLM transcript analysis and manual entry, `KnowledgeRepository` with CRUD + LIKE search, `KnowledgeService` routing LLM suggestions, tabbed Knowledge Base page, Confluence publish via approval queue, project aliases for Zoom matching)
- [x] Unified Meetings Page (merged Transcripts + Zoom Inbox into single `/meetings/` page with source/project/status filtering, inline project assignment + analyze, `source` column on `transcript_cache`, Zoom sync/dismiss/retry/reanalyse controls, backward-compat redirects from old URLs)
- [x] Consolidate Jira Field ID Constants (`src/jira_constants.py` — named constants for all hardcoded field IDs, issue type IDs, project keys; consumed by 7 files)
- [x] Extract Shared Retry/Backoff Utility (`src/connectors/retry.py` — shared constants, `backoff_sleep()`, `retry_after_or_backoff()`; consumed by `base.py` and `zoom.py`)
- [x] Extract Shared Error Banner Helper (`error_banner()` in `src/web/deps.py` — HTML-escaped error responses; replaced ~25 inline banners across 8 route files)
- [x] Move `_extract_plan_url` to Shared Utility (`extract_plan_url()` in `src/web/deps.py`; removed route-to-route coupling)
- [x] Fix `os.getenv` Bypassing Settings in Agent (`agent.py` now uses `settings.base_url` instead of `os.getenv`)
- [x] Lambda Assigned to Module Variable (`ceo_review.py` — converted `_TWO_WEEKS_AGO` lambda to `def _two_weeks_ago()`)
- [x] Fix DI Violations in Meetings Routes (added `Depends()` params for `TranscriptService`, `TranscriptParser`, `ZoomMatchingService` to 3 handlers)
- [x] Expose Public Methods on KnowledgeService (`get_action_item()` and `get_knowledge_entry()` public methods; routes no longer access `_repo` directly)
- [x] Move OAuth Code Exchange into ZoomConnector (`exchange_authorization_code()` method; removed raw `httpx` from zoom routes)
- [x] Add Logging to Silent Exception Blocks (5 locations: approval, charter, settings×2, typeahead — all now log with `logger.warning/debug`)
- [x] HTML-Escape Remaining Error Responses (import_project and knowledge routes now use `error_banner()`)
- [x] Add Logging to Repository Layer (all 10 repository files have module-level loggers with strategic debug/info/warning statements)
- [x] Add Logging to `risk_refinement.py` and `connectors/jira.py` (module loggers + key log points for refinement rounds and connector operations)
- [x] `ProjectContextService` Bypasses Service Layer (constructor-injected `transcript_repo` and `knowledge_repo` params; no more inline instantiation)
- [x] `ReleaseService` Bypasses ApprovalEngine for Audit (now uses `ApprovalEngine.log_audit_raw()` pass-through)
- [x] Repository Unit Tests (6 test files: project, approval, transcript, release, zoom, knowledge repos — 125 tests covering CRUD, edge cases, cascades)
- [x] Missing Model Tests (5 new test files: ceo_review, charter, closure, zoom, knowledge models — 38 tests covering `from_row()`, enums, JSON parsing)
- [x] Risk Refinement Service Tests (27 tests covering `start_risk_refinement`, `continue_risk_refinement`, `apply_refinement` with mocked agent/repos)
- [x] Transcript-Only Zoom Meeting Ingestion (second discovery path for meetings with live transcripts but no cloud recording; `list_past_meetings()` + `get_meeting_transcript()` + `download_meeting_transcript()` on connector; `discovery_source` column on `zoom_recordings`; rate-limited transcript probing; integrated into full sync pipeline)
- [x] Stacked Fix Version Burnup Charts (multi-version stacked scope bands with per-version colors, combined done line overlay, optional per-version done breakdown toggle with dashed lines, per-version projections, single-version fallback identical to previous behavior)
