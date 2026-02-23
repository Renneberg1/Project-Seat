# Project Seat — Feature Backlog

Tracking planned features, improvements, and technical debt. Grouped by theme, roughly prioritised within each section.

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

### Project Health Review (Senior PM Second Opinion)
On-demand LLM-powered project review that acts as a senior PM doing a health check. Ingests all available project data and returns structured feedback with areas of concern and recommendations.

**Data ingested (everything the app knows):**
- PROG Goal ticket (status, due date, summary, description)
- Risk register (open/closed counts, severity, components, risk points)
- Decision log (open/closed, timeline impact)
- Charter content (sections from Confluence)
- Jira Plans timeline (plan URL / embed reference)
- Team burnup data + velocity (from `team_progress_snapshots`)
- Per-team version progress (done/total/blockers/story points)
- DHF document status (released vs draft vs in-draft counts, release readiness %)
- Product Ideas summary (must-have/should-have breakdown, open vs done)
- Recent transcript analysis summaries (from `transcript_cache.meeting_summary`)
- Active release scope-freeze status

**Two-step interaction (same pattern as Charter Update):**
1. **Questions step:** LLM reviews all data and asks the PM clarifying questions it can't answer from the data alone (e.g. stakeholder sentiment, external dependencies, team morale, budget status, regulatory timeline pressures)
2. **Review step:** With answers folded in, LLM produces a structured review

**Output structure (structured JSON from LLM):**
- **Overall health rating** (Green / Amber / Red) with one-line rationale
- **Top concerns** (ranked list, each with: area, severity, evidence from data, recommendation)
- **Positive observations** (things going well, to reinforce)
- **Questions for the PM** (things the LLM noticed that warrant investigation)
- **Suggested next actions** (concrete, actionable items)

**Implementation notes:**
- New prompt template: `src/engine/prompts/health_review.py`
- New agent: `HealthReviewAgent` in `src/engine/agent.py` (or separate file) with `ask_questions()` and `generate_review()` methods
- New service: `src/services/health_review.py` — gathers all project context (reuse + extend `gather_project_context()` from transcript service)
- New route: `POST /project/{id}/health-review/ask` and `POST /project/{id}/health-review/analyze`
- New template: `src/web/templates/project_health_review.html` + partials for questions and review output
- Button on dashboard with HTMX loading spinner (same pattern as transcript analyze / charter ask)
- Read-only feature — no write actions, no approval queue needed
- Context budget: ~30-40K tokens (same as transcript analysis, but more diverse data sources)
- Could optionally persist reviews in a new `health_reviews` table for historical comparison

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

---

## Dashboard & UI

### Dashboard UI Refresh
Redesign the project dashboard to be more graphical and information-dense:
- **Progress rings/bars** for DHF completion, release readiness, sprint progress
- **Risk heat map** or severity distribution chart (High/Medium/Low counts as coloured badges or mini bar chart)
- **Timeline view** showing project phases with current position indicator
- **Sparklines** for trend data (risk count over time, velocity, doc completion)
- **Card-based layout** replacing the current table-heavy design
- Chart.js is already integrated (burnup chart on Team Progress tab) — extend to other dashboard sections

### Pipeline View Enhancements
- Drag-and-drop phase transitions (currently button-based)
- Project health indicator (green/amber/red) based on risk count + timeline status
- Collapsed vs expanded project cards with quick-glance metrics

### Transcript UI Improvements
- Diff preview for Confluence update suggestions (show what will be appended)
- Confidence threshold filter (hide low-confidence suggestions)
- Bulk operations: select multiple suggestions to accept/reject
- Transcript summary card on project dashboard (already partially implemented)

---

## Infrastructure & Technical Debt

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
- [x] LLM Loading Spinners (HTMX indicators on all LLM buttons: analyze, charter ask/analyze, re-analyze)
- [x] Re-analyze Button (re-run LLM on same transcript with updated project context)
- [x] Version Report Tracking Per Team (per-team version mapping with auto-detect at import, team progress dashboard with per-version JQL grouping, story point totals)
- [x] Burnup Chart (Chart.js burnup with scope vs done over time, dashed projection to due date, team filter, velocity override)
- [x] Confluence Formatting Guidance (LLM prompts include Confluence-specific formatting instructions for better output quality)
- [x] Risk/Decision Extraction from Arbitrary Text (covered by Transcript Direct Input — textarea accepts any text, not just transcripts)
- [x] Jira Plans Timeline Embed (iframe embed on dashboard, accepts bare URL or `<iframe>` snippet from Jira Plans Share, stored per project, integrated into import and spin-up flows)
