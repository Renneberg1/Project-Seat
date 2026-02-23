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
- **Team Progress Tracking** — Per-team version progress with auto-detected team mapping at import, story point breakdowns, and Chart.js burnup charts with projection and velocity override

### Planned / Upcoming

See `docs/feature-backlog.md` for the full list. Highlights:

- **LLM XFT Minutes** — Structure meeting transcripts into formal XFT minutes
- **Release Planning Assistant** — LLM-assisted release plan drafting with estimate gap detection
- **CEO Review Output** — Aggregated project status reports for executive review
- **Dashboard UI Refresh** — Progress rings, risk heat maps, timeline views

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
