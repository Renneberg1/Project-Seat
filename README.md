# Project Seat

A locally-run project management cockpit for medical device software engineering projects. Automates project spin-up, release tracking, and DHF document monitoring across Jira and Confluence.

## Features

- **Project Spin-Up** — Create Jira Goal tickets, fix versions, and Confluence page trees from templates in one step
- **Project Import** — Import existing projects from Jira/Confluence into the cockpit
- **Pipeline Dashboard** — CI-style pipeline view of active projects grouped by phase
- **Release Tracking** — Scope-freeze snapshots and document tracking per release
- **DHF Document Tracking** — Compare draft vs released EQMS documents across Confluence spaces
- **Approval Queue** — All automated actions require explicit human approval before execution
- **Product Ideas Integration** — PI board version tracking linked to projects
- **Transcript Analysis** — Upload meeting transcripts (.vtt/.txt/.docx), run LLM analysis to extract risks, decisions, XFT updates, and charter updates. Two-step approval gating: review LLM suggestions, then approve actions through the standard approval queue. Supports Gemini and Ollama providers.
- **Charter Update** — LLM-powered two-step Q&A flow: the LLM asks clarifying questions, then proposes section-level edits to the Confluence Charter page, all gated through the approval queue
- **Project Health Review** — On-demand LLM health check: gathers all project data (risks, decisions, team progress, DHF docs, charter, meeting summaries), asks clarifying questions, then produces a structured Green/Amber/Red assessment with concerns, positives, and next actions
- **Team Progress Tracking** — Per-team version progress with auto-detected team mapping at import, story point breakdowns, and Chart.js burnup charts with projection and velocity override
- **Jira Plans Timeline** — Embed Jira Plans (Advanced Roadmaps) Gantt chart on the project dashboard via iframe, with direct link to Jira
- **Dashboard Redesign** — Information-dense layout with hero bar (phase/health/countdown), Chart.js doughnut charts (risks, DHF docs), scope composition bar, team breakdown stacked bars, 3-column activity/links section. Responsive at 768px and 480px breakpoints.
- **Dark Mode** — Toggle between light and dark themes. Defaults to OS preference, persists choice in localStorage. All colors driven by CSS custom properties with dark palette derived from brand navy. Chart.js charts rebuild on theme change.
- **CEO Review Output** — Generate fortnightly CEO-level status updates with a last-2-weeks lens. Deterministic data tables (new risks/decisions, team progress, DHF docs) combined with LLM-generated commentary, published to the program's CEO Review Confluence page via the approval queue.
- **Iterative Risk/Decision Refinement** — Refine LLM-extracted risks and decisions through a multi-round Q&A loop. The LLM evaluates each draft against ISO 14971 quality criteria, asks targeted questions to fill gaps, and iterates until satisfied (max 5 rounds). Users can bail out early with "Apply Current Draft" or discard at any time.
- **Typeahead Resource Linking** — Search-as-you-type for Confluence pages and Jira issues/projects/versions across all ID input fields. Replaces opaque numeric IDs with human-readable titles, with keyboard navigation, HTMX-powered server search with debounce, and TTL-cached results.
- **API Health Check** — `GET /api/health` returns JSON connectivity status for DB, Jira, and Confluence (200 if all pass, 503 if degraded)
- **Offline CDN Assets** — HTMX and Chart.js bundled locally for air-gapped/offline resilience; automatic cache-busting via content-hash query strings
- **Page Progress Bar** — Animated loading indicator at top of page for both regular navigation and HTMX requests
- **Navigation Tab Grouping** — Analysis tabs (Transcripts, Charter, Health, CEO Review) collapse into a dropdown on narrow screens (≤1024px), flat on desktop
- **FastAPI Dependency Injection** — All service/connector instantiation in routes uses `Depends()` factory functions from `deps.py`

### Planned / Upcoming

See `docs/feature-backlog.md` for the full list. Highlights:

- **LLM XFT Minutes** — Structure meeting transcripts into formal XFT minutes
- **Release Planning Assistant** — LLM-assisted release plan drafting with estimate gap detection

## Quick Start

```bash
# Clone the repo
git clone <your-repo-url>
cd project-seat

# Install dependencies
uv sync  # or: pip install -e .

# Set up environment
cp .env.example .env
# Edit .env with your API keys

# Run (kills stale processes on port 8000 first)
python dev.py
```

## Documentation

- `CLAUDE.md` — Full project context for AI-assisted development
- `docs/architecture.pdf` — System architecture diagram
- `docs/workflow.pdf` — Product workflow diagram
- `docs/feature-backlog.md` — Planned features and technical debt
- `docs/spinup-flow.md` — Spin-up workflow documentation
- `docs/jira-structure.md` — Jira hierarchy and template documentation
- `docs/confluence-structure.md` — Confluence page tree documentation
