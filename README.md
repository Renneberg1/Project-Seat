# Project Seat

A locally-run project management cockpit for medical device software engineering projects. Automates project spin-up, release planning, transcript processing, and ongoing monitoring across Jira and Confluence.

## Features

- **Project Spin-Up** — Create Jira Goal tickets, fix versions, and Confluence page trees from templates in one step
- **Release Planning** — LLM-assisted release plan drafting with estimate gap detection
- **Transcript Processing** — Upload meeting transcripts and extract action items, decisions, and risks
- **Approval Queue** — All automated actions require explicit human approval before execution
- **Dashboard** — CI-style pipeline view of active projects and feature progression
- **Monitoring** — Track estimates, document completion, and scope changes

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

# Run
uvicorn src.main:app --reload --port 8000
```

## Documentation

- `CLAUDE.md` — Full project context for AI-assisted development
- `docs/architecture.pdf` — System architecture diagram
- `docs/workflow.pdf` — Product workflow diagram
- `docs/jira-structure.md` — Jira hierarchy and template documentation
- `docs/confluence-structure.md` — Confluence page tree documentation
