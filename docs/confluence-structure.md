# Confluence Structure

## Space

All project documentation lives in the **PMO Project Portfolio** space.

## Page Hierarchy

```
PMO Project Portfolio
├── PMO Dashboards
└── Product Development Projects
    └── [Product] Program (e.g. "HOP Program")
        ├── CEO Review
        └── Projects/Releases
            ├── [Project Charter]        ← Created from template at spin-up
            │   ├── [Project] Software Readiness
            │   ├── [Project] XFT        ← Created from template at spin-up
            │   └── [Next sub-project]
            └── [Other projects...]
    └── Completed Releases
```

## Template Pages

Templates are regular Confluence pages (not system templates). The cockpit fetches their content and creates new pages with the same structure.

| Template | Page ID | Purpose |
|----------|---------|---------|
| Project Charter | 3559363918 | Top-level project page with status, scope, stakeholders |
| Project XFT | 3559363934 | Cross-functional team meeting page with agenda, risks, decisions |

## Charter Template Sections

- Project name/release, date, project manager, executive sponsor
- Status tracker: INITIATION → PLANNING → EXECUTION → MONITORING → CLOSED
- OKR alignment
- Commercial objective
- Project scope (in scope / out of scope, links to PIs)
- Commercial driver
- Success criteria
- Stakeholders (Engineering, Product, Program Delivery, Commercial, Med Affairs)

## XFT Template Sections

- Project manager, project phase, links to planning template and closure report
- XFT members (Clinical, Regulatory, Project, Clinical AI, Systems, Product)
- Communication channels
- Project goals (strategic alignment, outcomes, driver)
- Roadmap & milestone (embedded Jira Plans / timeline)
- Risks (filtered from RISK project for this release)
- Agenda table (topic, owner, status, est. completion)
- Decisions table (open question, date, answer/outcome)

## Spin-Up Actions

1. Fetch Charter template page content (ID: 3559363918) via REST API
2. Create new page under `[Product] Program → Projects/Releases` with:
   - Title: project name (e.g. "V2 Drop 2")
   - Body: Charter template content with placeholders replaced
3. Fetch XFT template page content (ID: 3559363934) via REST API
4. Create new page as child of the Charter page with:
   - Title: "[Project] XFT" (e.g. "HOP XFT")
   - Body: XFT template content with placeholders replaced

## Ongoing Lifecycle Actions

- Create meeting notes pages under XFT page for specific decisions
- Update CEO Review page with latest project status
- Update Charter status field as project progresses through phases

## Example

See `samples/confluence/charter-template.json` and `samples/confluence/xft-template.json` for the full page content including HTML body structure.
