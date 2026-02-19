# Project Seat — Feature Backlog

Tracking planned features, improvements, and technical debt. Grouped by theme, roughly prioritised within each section.

---

## LLM-Powered Features

### Transcript Direct Input
Allow users to paste or type meeting notes directly into a text box instead of requiring a file upload. The existing `TranscriptParser._parse_txt()` already handles plain text — wire a textarea input through the same pipeline.

### LLM Charter Generation / Update
Guided LLM walkthrough to generate a new Charter page or update an existing one. The user answers structured questions (project scope, timeline, objectives, success criteria, regulatory strategy) and the LLM assembles a Charter page in the correct Confluence template format. For updates, the LLM diffs the current Charter content against new information (e.g. from a transcript or user input) and proposes section-level edits via the approval queue.

- New prompt template: `src/engine/prompts/charter.py`
- New agent method or dedicated `CharterAgent` class
- UI: step-by-step wizard in the project Charter tab
- Output: `UPDATE_CONFLUENCE_PAGE` approval items (one per section changed)

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

### Risk/Decision Extraction (Standalone)
Extract risks and decisions from arbitrary text input (not just transcripts). Useful for processing email threads, Slack exports, or design review notes.

- Prompt template: `src/engine/prompts/risk_decision.py` (stub exists in CLAUDE.md, file missing)
- Could share the suggestion review UI from the transcript workflow

### Estimate Gap Detection
Scan a project's Jira hierarchy and flag epics/tasks missing story points or time estimates. LLM provides confidence-weighted suggestions for likely estimate ranges based on similar past tickets.

- Prompt template: `src/engine/prompts/estimate_check.py` (stub exists in CLAUDE.md, file missing)

---

## Reporting & Status

### CEO Review Output
Generate formatted project status updates suitable for CEO review meetings. Aggregates:
- Project phase and timeline status
- Key risks (open count, top 3 by priority)
- Key decisions made since last review
- DHF document completion percentage
- Release readiness (scope freeze status, doc publication %)
- Blockers and escalations

Output options:
- Confluence page update (append to CEO Review page under the program)
- Downloadable summary (PDF or markdown)
- Could be LLM-enhanced to generate narrative summaries from raw data

### Regular Project Status Reports
Automated periodic status report generation per project. Pulls live data from Jira + Confluence and formats into a standard template:
- Sprint progress (velocity, burndown)
- Risk register changes (new, closed, escalated)
- Decision log updates
- Document completion delta since last report
- XFT meeting summary (from latest transcript analysis)

Delivery: Confluence page update or email-ready format.

### Version Report Tracking Per Software Team
Track fix version progress across each software team (AIM, CTCV, YAM, etc.) within a project. For each team's Jira project + fix version:
- Total issues, completed, in progress, remaining
- Story points completed vs total
- Burndown or progress bar
- Blockers and overdue items
- Cross-team dependency status

Display as a per-team breakdown on the project dashboard. Requires:
- Querying each team project's fix version (already created at spin-up)
- New `VersionReportService` or extension to `DashboardService`
- New dashboard section or dedicated "Team Progress" tab

---

## Dashboard & UI

### Dashboard UI Refresh
Redesign the project dashboard to be more graphical and information-dense:
- **Progress rings/bars** for DHF completion, release readiness, sprint progress
- **Risk heat map** or severity distribution chart (High/Medium/Low counts as coloured badges or mini bar chart)
- **Timeline view** showing project phases with current position indicator
- **Sparklines** for trend data (risk count over time, velocity, doc completion)
- **Card-based layout** replacing the current table-heavy design
- Consider lightweight charting: Chart.js (small, no framework dependency) or pure CSS/SVG charts to keep the HTMX-only frontend

### Pipeline View Enhancements
- Drag-and-drop phase transitions (currently button-based)
- Project health indicator (green/amber/red) based on risk count + timeline status
- Collapsed vs expanded project cards with quick-glance metrics

### Transcript UI Improvements
- Loading spinner on "Analyze with LLM" button — LLM calls take 3-8+ seconds; the button currently gives no feedback. Add an HTMX indicator (spinner + "Analyzing..." text) and disable the button during the request.
- Re-analyze button (re-run LLM on same transcript with updated project context)
- Diff preview for Confluence update suggestions (show what will be appended)
- Confidence threshold filter (hide low-confidence suggestions)
- Bulk operations: select multiple suggestions to accept/reject
- Transcript summary card on project dashboard (already partially implemented)

---

## Infrastructure & Technical Debt

### Connector Extensions (as needed)
- Jira: project/component listing, bulk operations
- Confluence: page deletion/archival, attachment upload, label management, space operations

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
