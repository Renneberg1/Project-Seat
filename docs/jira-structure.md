# Jira Structure

## Hierarchy

```
Goal (PROG project)
├── Initiative (per team project: AIM, CTCV, YAM, etc.)
│   ├── Epic (feature-level work)
│   │   └── Task (developer work items)
├── Risk (RISK project, linked to Goal)
└── Decision / "Project Issue" (RISK project, linked to Goal)
```

## Issue Types by Project

| Project | Issue Types Used | Purpose |
|---------|-----------------|---------|
| PROG | Goal | Top-level project/release tracking |
| AIM, CTCV, YAM, etc. | Initiative, Epic, Task | Team-level delivery work |
| RISK | Risk, Project Issue (Decision) | Risk and decision tracking |

## Spin-Up Actions

When a new project is created, the cockpit:

1. **Creates a Goal** in the PROG project
   - Summary: "[Product] [Release]" (e.g. "HOP Drop 2")
   - Description: Links to Confluence Charter and scope (PI board filter)
   - Fields: Assignee, due date, priority, labels

2. **Creates a fix version** in the RISK project (e.g. "HOP Drop 2")

3. **Creates the same fix version** in all team projects selected during spin-up

4. **Links Confluence pages** in the Goal description

## RISK Project

- **Risk tickets** require:
  - Component (e.g. "HOP Frontend", "HOP Backend", "V1 Enterprise")
  - Fix version matching the project (e.g. "HOP Drop 2")
  - Link to parent PROG Goal ticket
- **Decision tickets** use the "Project Issue" issue type in the same RISK project
- Jira automation handles risk score calculation and aggregation to project level
- Custom fields: Risk Threshold, Risk Points, Risk Level

## Key Custom Fields

Refer to `samples/jira/field-name-to-id.json` for the mapping of field display names to Jira custom field IDs. Critical fields include:
- Risk Threshold
- Risk Points
- Risk Level
- T-Shirt Size
- Timeline Status

## Naming Conventions (Suggested)

- **Goal:** "[Product] [Release]" — e.g. "HOP Drop 2"
- **Initiative:** "[Component/Area] - [Release]" — e.g. "CTC Model - Drop 2"
- **Epic/Task:** Descriptive, at team discretion

## Example

See `samples/jira/prog-256.json` for a real Goal ticket (HOP Drop 2) and `samples/jira/aim-3295.json` for an Initiative (CTC Model - Drop 2).
