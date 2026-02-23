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

### Planned / Upcoming

See `docs/feature-backlog.md` for the full list. Highlights:

- **LLM XFT Minutes** — Structure meeting transcripts into formal XFT minutes
- **Release Planning Assistant** — LLM-assisted release plan drafting with estimate gap detection
- **CEO Review Output** — Aggregated project status reports for executive review

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
