# Project Seat — Feature Backlog

Tracking planned features, improvements, and technical debt. Grouped by theme, roughly prioritised within each section. Items marked **(NEW)** were identified in the Feb 2026 codebase audit.

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

### Navigation Tab Grouping **(NEW)**
The project-level nav has 10 tabs (Dashboard, Features, Documents, Approvals, Transcripts, Charter, Health, CEO Review, Teams, Settings). On narrower screens these overflow. Group related tabs into dropdowns (e.g., "Analysis" for Transcripts/Charter/Health/CEO Review) or add a responsive hamburger menu for less-used tabs.

### Page Navigation Loading State **(NEW)**
Regular page navigation (clicking between Dashboard → Features → Documents) has no loading indication. When Jira API calls take 1–2 seconds, the UI feels unresponsive. Add an HTMX-compatible progress bar or page-level spinner for non-LLM navigations.

### Notification / Toast System **(NEW)**
Currently success/error feedback uses inline banners that can be missed. A toast notification system (auto-dismissing, stacking) would improve the UX for actions like "Settings saved", "Suggestion accepted", "Approval submitted".

### Offline Resilience — Bundle CDN Assets **(NEW)**
HTMX and Chart.js are loaded from CDN (`unpkg.com`, `jsdelivr.net`). If the CDN is down or blocked by a corporate proxy, the app is non-functional. Bundle these in `static/vendor/` for reliable offline operation.

---

## Infrastructure & Technical Debt

### Tier 1 — High Impact

#### Extract BaseAgent Class **(NEW)**
`_generate_with_retry()` and `_strip_fences()` are copy-pasted identically across `CharterAgent`, `HealthReviewAgent`, `CeoReviewAgent`, and `RiskRefineAgent` (~200 lines of duplication). Extract a `BaseAgent` class with the shared methods; concrete agents inherit from it.

#### Fix Leaked Connector in `gather_project_context()` **(NEW)**
`src/services/transcript.py` line ~324 creates a `JiraConnector` to fetch labels/components but never calls `.close()`, leaking an `httpx.AsyncClient` connection on every transcript analysis.

#### Add Database Indexes **(NEW)**
No secondary indexes exist beyond primary keys and UNIQUE constraints. Add indexes on the most-queried columns:
- `transcript_suggestions(transcript_id)`
- `transcript_suggestions(project_id, status)`
- `approval_queue(project_id, status)`
- `approval_queue(status)`
- `charter_suggestions(project_id)`
- `health_reviews(project_id)`
- `ceo_reviews(project_id)`

#### Enable TLS Verification by Default **(NEW)**
`verify=False` is hardcoded in `src/connectors/base.py` and `src/engine/providers/gemini.py`. Make it configurable via an env var (`VERIFY_SSL=true` default), with `false` as an opt-in escape hatch for corporate proxy environments.

#### Run Orchestrator Task Immediately on Startup **(NEW)**
The orchestrator's `_run_loop` sleeps first (24 hours for the daily snapshot task), then runs. The first snapshot is not taken until a full day after app start. Execute the task once immediately, then enter the sleep loop.

### Tier 2 — Medium Impact

#### Extract Shared `_render()` Helper **(NEW)**
6 route files define an identical `_render()` function (merge nav context, render template, set project cookie). Extract into `src/web/deps.py` as a single shared function.

#### Extract Q&A Pair Collection Utility **(NEW)**
The pattern for collecting `question_0`/`answer_0` pairs from form data is duplicated in 4 route files (charter, health_review, ceo_review, transcript). Extract into a shared helper.

#### HTML-Escape Exception Messages **(NEW)**
Error banners in transcript, charter, health_review, and ceo_review routes embed `str(exc)` directly in HTML without escaping. Use `html.escape()` for defense-in-depth against XSS via crafted error messages.

#### Enable SQLite WAL Mode **(NEW)**
SQLite defaults to journal mode `delete`, which locks the entire DB during writes. Enable WAL mode (`PRAGMA journal_mode = WAL`) for better concurrent read/write performance. One-line change in `get_db()`.

#### Versioned Database Migrations **(NEW)**
The current migration strategy runs every `ALTER TABLE` attempt wrapped in `try/except OperationalError: pass` on every startup. Implement a `schema_version` table with numbered migration functions so each runs exactly once, and support data migrations.

#### Cache Context Between Q&A Steps **(NEW)**
In CEO Review and Health Review workflows, `gather_ceo_context()` / `gather_all_context()` is called separately for both the questions step and the review step. The context is fetched twice per review. Either pass context through the form (like Q&A state) or cache with a short TTL keyed by project + timestamp.

#### Add ON DELETE CASCADE to Foreign Keys **(NEW)**
Only `release_documents` has `ON DELETE CASCADE`. Other project-child tables rely on manual deletion in `delete_project()`. Adding cascade to all FK constraints simplifies cleanup and prevents orphaned rows when new tables are added.

### Tier 3 — Nice to Have

#### Automatic CSS Cache-Busting **(NEW)**
`style.css?v=12` is manually incremented. Use a file hash or git commit short-hash for automatic cache-busting.

#### Remove Dead Code **(NEW)**
`src/web/routes/project.py` has an unused `_project_response()` function stub. Clean up along with the mid-file `import re` (move to top of file).

#### Provider Unit Tests **(NEW)**
`src/engine/providers/gemini.py` and `ollama.py` have no dedicated test files. Add tests for response parsing, error handling, retry logic, and edge cases (truncated responses, safety blocks).

#### FastAPI Dependency Injection **(NEW)**
`DashboardService()` is instantiated fresh in 40+ locations (including every `get_nav_context()` call). Using `Depends()` for service injection would reduce boilerplate and improve testability.

#### API Health Check Endpoint **(NEW)**
A `/api/health` endpoint that tests Atlassian API connectivity and returns status. Useful for debugging and could power a status indicator in the nav bar showing whether Jira/Confluence are reachable.

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
