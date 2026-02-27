# Project Seat — Feature List

Complete list of delivered features, grouped by category.

---

## Project Management

- **Project Spin-Up** — Create Jira Goal tickets, fix versions, and Confluence page trees from templates in one step
- **Project Import** — Import existing projects from Jira/Confluence into the cockpit
- **Pipeline Dashboard** — CI-style pipeline view of active projects grouped by phase
- **Release Tracking** — Scope-freeze snapshots and document tracking per release
- **DHF Document Tracking** — Compare draft vs released EQMS documents across Confluence spaces
- **Team Progress Tracking** — Per-team version progress with auto-detected team mapping, story point breakdowns, and burnup charts with projection and velocity override
- **Jira Plans Timeline** — Embed Jira Plans Gantt chart on the project dashboard via iframe
- **Product Ideas Integration** — PI board version tracking linked to projects

## LLM-Powered Analysis

- **Transcript Analysis** — Upload meeting transcripts (.vtt/.txt/.docx), run LLM analysis to extract risks, decisions, XFT updates, and charter updates. Two-step approval gating with Gemini and Ollama provider support.
- **Charter Update** — Two-step Q&A flow: the LLM asks clarifying questions, then proposes section-level edits to the Confluence Charter page, gated through the approval queue
- **Project Health Review** — On-demand health check gathering all project data (risks, decisions, team progress, DHF docs, charter, meeting summaries), producing a structured Green/Amber/Red assessment with concerns, positives, and next actions
- **CEO Review Output** — Fortnightly CEO-level status updates with a last-2-weeks lens. Deterministic data tables combined with LLM-generated commentary, published to the CEO Review Confluence page via the approval queue.
- **Project Closure Report** — Formal closure reports covering delivery outcome, timeline adherence, scope completion, risk/issue closure, success criteria assessment, and lessons learned. Hybrid deterministic data tables and LLM narrative, published to Confluence via the approval queue.
- **Iterative Risk/Decision Refinement** — Multi-round Q&A loop evaluating LLM-extracted risks and decisions against ISO 14971 quality criteria, with early bail-out support

## Governance & Traceability

- **Approval Queue** — All automated write actions (Jira tickets, Confluence pages) require explicit human approval before execution, with full audit trail in SQLite
- **API Health Check** — `GET /api/health` returns JSON connectivity status for DB, Jira, and Confluence

## UI & Infrastructure

- **Dashboard Layout** — Information-dense design with hero bar, doughnut charts, scope composition bar, team breakdown stacked bars, and 3-column activity/links section. Responsive at 768px and 480px.
- **Dark Mode** — Light/dark theme toggle with OS preference detection, localStorage persistence, and CSS custom properties throughout
- **Typeahead Resource Linking** — Search-as-you-type for Confluence pages and Jira issues/projects/versions, replacing opaque numeric IDs with human-readable titles
- **Offline CDN Assets** — HTMX and Chart.js bundled locally for air-gapped operation; automatic cache-busting via content-hash query strings
- **Page Progress Bar** — Animated loading indicator for both regular navigation and HTMX requests
- **Navigation Tab Grouping** — Analysis tabs collapse into a dropdown on narrow screens, flat on desktop
- **Dependency Injection** — All service/connector instantiation in routes uses FastAPI `Depends()` factories
