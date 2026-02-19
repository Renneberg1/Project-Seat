# Spin-Up Workflow

How the project spin-up wizard creates Jira issues, fix versions, and Confluence pages.

## Overview

Spin-up is a two-phase process:

1. **Prepare** — The user submits a form. The service creates a local project row in SQLite and queues 4–6+ approval items (depending on team project count). Two Confluence API calls happen immediately (template fetch, parent page lookup) to populate the queued payloads.
2. **Execute** — The user reviews the approval queue and approves items one-by-one or all-at-once. Each approval triggers the actual Jira/Confluence API call. Items with sentinel dependencies are resolved just before execution using results from earlier items.

## Inputs

The spin-up form (`POST /spinup/`) collects:

| Field | Type | Required | Notes |
|---|---|---|---|
| `project_name` | string | yes | Used as Goal summary, version name, and page title prefix |
| `program` | string | yes | e.g. "HOP" — used to locate the parent Confluence page |
| `team_projects` | comma-separated string | no | Jira project keys (e.g. "AIM, CTCV, YAM") — a fix version is created in each |
| `target_date` | string | no | ISO date, set as Goal `duedate` and version `releaseDate` |
| `labels` | comma-separated string | no | Applied to the Goal ticket |
| `goal_summary` | string | no | Free text, becomes the Goal's ADF description |
| `pi_version` | string | no | Stored in the local `projects` table only — not sent to Jira |

**Hardcoded values:**
- `confluence_space_key` defaults to `"HPP"` (set in `SpinUpRequest` model)
- `PROG_PROJECT_KEY = "PROG"` — the Jira project for Goal tickets
- `RISK_PROJECT_KEY = "RISK"` — always gets a fix version
- `GOAL_ISSUE_TYPE_ID = "10423"` — the Goal issue type in PROG
- `CHARTER_TEMPLATE_ID = "3559363918"` — Confluence template page
- `XFT_TEMPLATE_ID = "3559363934"` — Confluence template page

## Immediate Actions (during `prepare_spinup`)

These happen before any approval item is created:

1. **Insert local project** — `_create_local_project()` inserts a row into `projects` with `jira_goal_key="pending"`, `status="spinning_up"`, and `pi_version` if provided. Returns the `project_id` used to link all approval items.

2. **Fetch Charter template** — `_fetch_template_body(CHARTER_TEMPLATE_ID)` calls `GET /wiki/rest/api/content/3559363918?expand=body.storage` and extracts the storage-format XHTML body. Placeholders are then replaced.

3. **Fetch XFT template** — Same as above for `XFT_TEMPLATE_ID = "3559363934"`.

4. **Find parent page** — `_find_projects_releases_page()` searches Confluence for `"{program} Program"` in the space, then iterates its children looking for one titled `"Projects/Releases"`. Falls back to the program page itself if the child isn't found.

5. **Replace placeholders** — Both template bodies go through `_replace_placeholders()`:
   - `[Insert project name & release]` → `project_name`
   - `[Insert project name]` → `project_name`
   - `[Project Name]` → `project_name`
   - `[Target Date]` → `target_date` or `"TBD"`
   - `[Program]` → `program`

## Queued Approval Items

After the immediate actions, `prepare_spinup` queues the following items. The exact count is `4 + len(team_projects) + 2` (minimum 6 with no team projects).

### Item 1: Create Goal ticket

| Field | Value |
|---|---|
| Action | `CREATE_JIRA_ISSUE` |
| API | `POST /rest/api/3/issue` |
| Payload | `project_key: "PROG"`, `issue_type_id: "10423"`, `summary: project_name` |
| Optional fields | `description` (ADF doc), `labels`, `duedate` |
| Returns | `{"id": "...", "key": "PROG-XXX", "self": "..."}` |

### Item 2: Create RISK fix version

| Field | Value |
|---|---|
| Action | `CREATE_JIRA_VERSION` |
| API | `POST /rest/api/3/version` |
| Payload | `project_key: "RISK"`, `name: project_name`, `releaseDate: target_date` |

### Items 3..N: Create team project fix versions

One item per entry in `team_projects`. Same action/payload shape as item 2, with the team project key instead of RISK.

### Item N+1: Create Charter page

| Field | Value |
|---|---|
| Action | `CREATE_CONFLUENCE_PAGE` |
| API | `POST /wiki/rest/api/content` |
| Payload | `space_key: "HPP"`, `title: "{project_name} Charter"`, `body_storage: <template>`, `parent_id: <Projects/Releases page ID>` |
| Returns | `{"id": "...", "title": "...", ...}` |

### Item N+2: Create XFT page (sentinel dependency)

| Field | Value |
|---|---|
| Action | `CREATE_CONFLUENCE_PAGE` |
| API | `POST /wiki/rest/api/content` |
| Payload | `space_key: "HPP"`, `title: "{project_name} XFT"`, `body_storage: <template>`, `parent_id: "__CHARTER_PAGE_ID__"` |

The `parent_id` uses a **sentinel value** `__CHARTER_PAGE_ID__` that gets replaced at execution time with the real Charter page ID from item N+1's result.

### Item N+3: Update Goal description (sentinel dependency)

| Field | Value |
|---|---|
| Action | `UPDATE_JIRA_ISSUE` |
| API | `PUT /rest/api/3/issue/{key}` |
| Payload | `key: "__GOAL_KEY__"`, `fields.description: "__GOAL_DESCRIPTION_PLACEHOLDER__"` |

This item has **two sentinel values**:
- `__GOAL_KEY__` — replaced with the actual PROG-XXX key from item 1's result
- `__GOAL_DESCRIPTION_PLACEHOLDER__` — replaced with a full ADF document containing inlineCard links to the Charter and XFT pages

## Sentinel Resolution

When `execute_approved_item()` runs, it calls `_resolve_sentinels()` before the API call:

1. Loads all previously executed items for the same `project_id`
2. Scans their results to find:
   - **Goal key** — from `CREATE_JIRA_ISSUE` results where `key` starts with `"PROG"`
   - **Charter page ID** — from `CREATE_CONFLUENCE_PAGE` results where `title` contains `"Charter"` but not `"XFT"`
   - **XFT page ID** — from `CREATE_CONFLUENCE_PAGE` results where `title` contains `"XFT"`
3. String-replaces sentinel values in the JSON payload
4. For the description placeholder specifically, builds a full ADF document via `_build_goal_description()`:
   - Creates paragraphs with `inlineCard` nodes linking to `https://{domain}.atlassian.net/wiki/spaces/HPP/pages/{id}`
   - Includes both Charter and XFT links (XFT only if already executed)

**Important:** The resolution is string-based (`json.dumps` → replace → `json.loads`), so it works regardless of where in the payload the sentinel appears. The updated payload is persisted back to the `approval_queue` table before execution.

## Execution Flow

Execution happens via the approval routes:

- **Single item:** `POST /approval/{item_id}/approve` → calls `SpinUpService.execute_approved_item(item_id)`
- **All items:** `POST /approval/approve-all` → iterates pending items in ID order, calling `execute_approved_item()` for each

The `approve_and_execute()` method in `ApprovalEngine`:
1. Validates the item is in `PENDING` status
2. Marks it `APPROVED`
3. Dispatches to the appropriate connector method
4. On success: stores the result JSON and marks `EXECUTED`
5. On failure: stores the error and marks `FAILED`
6. Writes an entry to the `approval_log` audit trail

Items are executed **sequentially in ID order** when using approve-all. This is critical because later items depend on earlier items' results for sentinel resolution.

## Key Files

| File | Role |
|---|---|
| `src/web/routes/spinup.py` | Form rendering and submission (parses form, calls service) |
| `src/services/spinup.py` | Core logic: `prepare_spinup()`, sentinel resolution, template fetching |
| `src/engine/approval.py` | Queue management, action dispatch, audit logging |
| `src/models/project.py` | `SpinUpRequest` and `Project` dataclasses |
| `src/models/approval.py` | `ApprovalAction` enum, `ApprovalStatus` enum, `ApprovalItem` dataclass |
| `src/connectors/jira.py` | `create_issue()`, `create_version()`, `update_issue()` |
| `src/connectors/confluence.py` | `get_page()`, `create_page()`, `search_pages()`, `get_page_children()` |
| `src/web/routes/approval.py` | Approve/reject/approve-all endpoints |
| `src/web/templates/spinup.html` | Spin-up form |
| `src/web/templates/spinup_result.html` | Result page after queuing |
| `src/web/templates/approval.html` | Approval queue UI |

## Notes and Gotchas

1. **Ordering matters.** The approve-all route processes items by ascending ID. If you approve item N+2 (XFT page) before item N+1 (Charter page), the sentinel won't resolve because the Charter result doesn't exist yet. The XFT page would be created with a literal `"__CHARTER_PAGE_ID__"` as its parent, which would fail.

2. **Description overwrite.** Item N+3 replaces the Goal's entire `description` field with Confluence links. If `goal_summary` was provided in step 1, that text is lost — the update overwrites it with only the page links. The original summary is set on creation but then replaced.

3. **`pi_version` is local-only.** The `pi_version` field is stored in the SQLite `projects` table but is never sent to Jira. It's used by the dashboard for grouping/filtering projects by PI.

4. **Space key is hardcoded.** `confluence_space_key` defaults to `"HPP"` in the `SpinUpRequest` model. The form doesn't expose this field — all projects are created in the same Confluence space.

5. **Page link URLs use hardcoded space.** `_build_goal_description()` constructs page URLs with `/spaces/HPP/pages/{id}`. This is hardcoded, not derived from `confluence_space_key`.

6. **Template placeholders are case-sensitive.** The replacement list in `_replace_placeholders()` uses exact string matching — `[project name]` would not match `[Project Name]`.

7. **Parent page fallback.** If the "Projects/Releases" child page isn't found under the program page, the Charter is created directly under the program page instead. This is a silent fallback with a log warning.

8. **No rollback on partial failure.** If item 3 fails but items 1–2 succeeded, the Goal and RISK version exist in Jira. There's no automatic cleanup — the user must manually delete or retry.

9. **Connector lifecycle.** Each API call creates and closes its own connector instance. There's no connection pooling across items.
