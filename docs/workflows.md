# Project Seat — LLM Workflow Documentation

Detailed flows, output structures, and design decisions for each LLM-powered workflow. For a concise summary, see the "LLM Workflows" section in `CLAUDE.md`.

---

## Transcript Workflow

The transcript analysis pipeline is the first LLM-powered feature. It follows a two-step approval gating model for regulatory traceability.

### Flow

```
Upload (.vtt/.txt/.docx)
  → TranscriptParser.parse() → store in transcript_cache
  → TranscriptService.analyze_transcript()
      → gather_project_context() (parallel: Jira risks/decisions + Confluence Charter/XFT)
      → TranscriptAgent.analyze_transcript() (LLM call with structured JSON output)
  → Store suggestions in transcript_suggestions (status=pending)
  → User reviews suggestions (accept/reject per item, or Accept All)
  → accept_suggestion() patches payload with live project data → ApprovalEngine.propose()
  → User approves in Approval Queue
  → ApprovalEngine.approve_and_execute() → Jira/Confluence connectors
```

### Suggestion Types

| Type | Action | Target |
|---|---|---|
| `risk` | `CREATE_JIRA_ISSUE` | RISK project, Risk type (id `10832`), child of PROG Goal |
| `decision` | `CREATE_JIRA_ISSUE` | RISK project, Project Issue type (id `12499`), child of PROG Goal |
| `xft_update` | `UPDATE_CONFLUENCE_PAGE` | XFT page (append meeting notes) |
| `charter_update` | `UPDATE_CONFLUENCE_PAGE` | Charter page (update section) |

### Key Design Decisions

- **Payload refresh at accept time:** When a suggestion is accepted, `accept_suggestion()` patches the stored payload with current project data (goal key, fix versions, Confluence page IDs). This prevents stale data from incomplete spin-ups baking into suggestions.
- **Confluence append mode:** XFT updates use `append_mode: true` — at execution time, the current page body is fetched and the new content is appended, preventing overwrites of changes made between suggestion and approval.
- **Jira ADF format:** Risk/decision descriptions, Impact Analysis (`customfield_11166`), and Mitigation/Control (`customfield_11342`) are all in Atlassian Document Format. ADF builder helpers are in `src/engine/prompts/transcript.py`.
- **Token budget:** Transcripts truncated to ~20K chars; existing risks/decisions as key+summary only; Charter/XFT content last 3K chars each. Total ~30K tokens.

---

## Charter Update Workflow

The Charter update pipeline is the second LLM-powered feature. It uses a two-step LLM interaction (clarifying questions, then precise edits) with the same approval gating model as transcripts.

### Charter XHTML Structure

The Charter page is stored in Confluence as XHTML with a `<table>` inside an `<ac:structured-macro ac:name="details">` block. Each `<tr>` has a `<th>` (section name) and `<td>` (content). **Project Scope** uses `rowspan="2"` — one `<th>` spanning two rows for "In Scope" and "Out of Scope" sub-sections.

The `charter_storage_utils.py` module handles parsing and modification:
- `extract_sections(storage_body)` → `[{name, content}]` (plain text, handles rowspan)
- `replace_section_content(storage_body, section_name, new_content)` → modified XHTML

### Flow

```
User enters free-form text describing changes
  → POST /charter/ask → CharterService.generate_questions()
      → CharterAgent.ask_questions() (LLM call #1: identify gaps)
  → UI shows clarifying questions with answer fields
  → User answers → POST /charter/analyze → CharterService.analyze_charter_update()
      → CharterAgent.propose_edits() (LLM call #2: section replacements)
  → Store suggestions in charter_suggestions (status=pending)
  → User reviews/accepts/rejects each edit
  → accept_suggestion() → ApprovalEngine.propose() with section_replace_mode payload
  → User approves in Approval Queue
  → ApprovalEngine.approve_and_execute() → replace_section_content() → Confluence update
```

If the LLM returns no questions (user input is already complete), the questions partial auto-submits to the analyze endpoint, skipping the Q&A step.

### Key Design Decisions

- **Two-step LLM interaction:** Step 1 (questions) ensures completeness before Step 2 (edits) proposes changes. Each step has its own system prompt and JSON schema.
- **Stateless Q&A:** No DB storage for the intermediate Q&A state — the questions form carries `user_input` as a hidden field and answers as form fields. Only the final suggestions are persisted.
- **Section replace mode:** The approval engine's `UPDATE_CONFLUENCE_PAGE` action supports `section_replace_mode: true` — at execution time, the current page body is fetched and `replace_section_content()` swaps the target `<td>` in-place, preventing overwrites of other sections changed between suggestion and approval.
- **Payload refresh at accept time:** Like transcripts, `accept_suggestion()` patches the `page_id` from current project data to prevent stale Confluence page references.

---

## Health Review Workflow

The health review is the third LLM-powered feature. It uses the same two-step Q&A pattern as Charter Update, but is read-only (no write actions, no approval queue).

### Flow

```
User clicks "Start Health Review"
  → POST /health-review/ask → HealthReviewService.generate_questions()
      → gather_all_context() (parallel: summary, initiatives, PI, team progress,
        snapshots, DHF, transcript context, releases, meeting summaries)
      → HealthReviewAgent.ask_questions() (LLM call #1: identify data gaps)
  → UI shows clarifying questions (or auto-submits if none needed)
  → User answers → POST /health-review/analyze → HealthReviewService.generate_review()
      → HealthReviewAgent.generate_review() (LLM call #2: structured review)
  → Persist review in health_reviews table
  → Display structured output (rating, concerns, positives, next actions)
```

### Output Structure

- **health_rating**: Green / Amber / Red
- **health_rationale**: One-line summary
- **top_concerns**: Ranked list with area, severity, evidence, recommendation
- **positive_observations**: Things going well
- **questions_for_pm**: Things warranting investigation
- **suggested_next_actions**: Concrete next steps

### Key Design Decisions

- **Read-only:** No write actions to Jira/Confluence — purely advisory, no approval queue needed
- **Comprehensive context:** Ingests all available project data (9 parallel fetches with graceful error handling per source)
- **Persisted reviews:** Stored in `health_reviews` table for historical comparison, displayed on the Health Review page
- **High token budget:** Uses `maxOutputTokens: 16384` because Gemini 2.5 Flash thinking tokens count against the output budget

---

## CEO Review Workflow

The CEO Review is the fourth LLM-powered feature. It uses the same two-step Q&A pattern as Health Review, but with a **last-2-weeks lens** and **Confluence publishing** via the approval queue.

### Flow

```
User enters optional PM notes → clicks "Generate CEO Review"
  → POST /ceo-review/ask → CeoReviewService.generate_questions()
      → gather_ceo_context() (9 parallel fetches: summary, initiatives, team reports,
        snapshots (14d), DHF docs, releases, new risks (2w), new decisions (2w), meetings)
      → compute_metrics() (deterministic: filter DHF by 2w, burnup delta, team progress)
      → CeoReviewAgent.ask_questions() (LLM call #1: identify gaps)
  → UI shows clarifying questions (or auto-submits if none needed)
  → User answers → POST /ceo-review/analyze → CeoReviewService.generate_review()
      → CeoReviewAgent.generate_review() (LLM call #2: structured update)
  → render_confluence_xhtml() → save_review() in ceo_reviews table
  → User reviews preview (data tables + LLM commentary)
  → Accept → accept_review() → ApprovalEngine.propose(UPDATE_CONFLUENCE_PAGE, append_mode=true)
  → User approves in Approval Queue → appended to CEO Review Confluence page
```

### Output Structure

- **health_indicator**: On Track / At Risk / Off Track
- **decisions_commentary**: Summary of new decisions
- **risks_commentary**: Summary of new risks and patterns
- **development_commentary**: Dev progress, velocity, blockers
- **documentation_commentary**: DHF progress, recently updated docs
- **escalations**: Issues needing leadership attention (issue, impact, ask)
- **next_milestones**: Upcoming concrete milestones

### Key Design Decisions

- **Hybrid output:** Deterministic data tables (new risks/decisions, team progress, DHF) combined with LLM-generated commentary — numbers are pre-computed, LLM writes narrative only
- **Last-2-weeks focus:** JQL `created >= -2w` for new risks/decisions, burnup snapshots limited to 14 days, DHF filtered by `last_modified`
- **Confluence append:** Uses existing `append_mode` in approval engine — fetches current page body at execution time and appends XHTML
- **Auto-discovery:** CEO Review page discovered from Charter ancestors: Charter → ancestors → Program → children → "CEO Review" title match
- **PM notes:** Free-form textarea for qualitative context (blockers, escalations, team dynamics) passed to both LLM steps

---

## Risk Refinement Workflow

The risk refinement feature adds iterative Q&A refinement for transcript-extracted risks and decisions, evaluating them against ISO 14971 quality criteria.

### Flow

```
User clicks "Refine" on a risk/decision suggestion
  → POST /{tid}/suggestions/{sid}/refine → TranscriptService.start_risk_refinement()
      → _extract_risk_draft() (parse ADF payload back to plain text fields)
      → gather_project_context() (existing risks/decisions for dedup)
      → RiskRefineAgent.refine() (LLM call: evaluate + ask questions)
  → UI shows quality assessment, current draft preview, question form
  → User answers → POST /{tid}/suggestions/{sid}/refine/answer
      → TranscriptService.continue_risk_refinement() (next round)
      → RiskRefineAgent.refine() (LLM call with accumulated Q&A)
  → Loop until satisfied or max 5 rounds
  → User clicks "Apply Refinement" → POST /{tid}/suggestions/{sid}/refine/apply
      → TranscriptService.apply_refinement() (rebuild Jira payload, update DB)
  → Suggestion row re-renders with refined content
  → User can Accept/Reject as usual
```

### Key Design Decisions

- **Single-method agent:** `RiskRefineAgent.refine()` handles both initial evaluation and follow-up rounds (unlike the two-step Charter/Health agents)
- **Stateless Q&A:** No new DB tables — state carried via hidden form fields (`risk_draft` JSON, `qa_history` JSON, `round_number`), same pattern as Charter Q&A
- **ADF round-trip:** `_extract_risk_draft()` parses the Jira ADF payload back to plain text for the LLM; `apply_refinement()` rebuilds ADF from the refined fields
- **Max 5 rounds:** `continue_risk_refinement()` forces `satisfied=true` at round 5 without an LLM call
- **Bail-out options:** "Apply Current Draft" applies partial refinement at any point; "Discard" removes the panel without changes

---

## Closure Report Workflow

The closure report is the fifth LLM-powered feature. It uses the same two-step Q&A pattern as CEO Review, with **full project lifecycle data** and **Confluence page creation** via the approval queue.

### Flow

```
PM enters optional notes → POST /closure/ask
  → ClosureService.generate_questions()
      → gather_closure_context() (parallel: ALL risks, ALL decisions, Charter, XFT,
        initiatives, team reports, full snapshots (365d), DHF docs, releases, meetings)
      → compute_closure_metrics() (deterministic: timeline, scope, risk/decision tables,
        DHF final status, team progress)
      → ClosureAgent.ask_questions() (LLM call #1: identify gaps in lessons learned,
        delivery assessment, success criteria, stakeholder satisfaction)
  → UI shows clarifying questions (or auto-submits if none)
  → PM answers → POST /closure/analyze
      → ClosureAgent.generate_report() (LLM call #2: narrative sections)
  → render_confluence_xhtml() → save to closure_reports table
  → PM reviews preview (data tables + LLM narrative)
  → Accept → ClosureService.accept_report()
      → ApprovalEngine.propose(CREATE_CONFLUENCE_PAGE) — child of Charter page
  → PM approves in Approval Queue → Confluence page created
```

### Output Structure

- **final_delivery_outcome**: 3-5 sentence narrative (LLM)
- **success_criteria_assessments**: Table with criterion/expected/actual/status/comments (LLM)
- **lessons_learned**: Categorised table with description/triggers/recommendations/owner (LLM)
- **timeline**: Planned vs Actual vs Deviation table (deterministic)
- **scope_delivered / scope_not_delivered**: Lists from initiative status (deterministic)
- **all_risks / all_decisions**: Full lifecycle tables (deterministic)
- **team_progress**: Final per-team SP breakdown (deterministic)
- **dhf_total / dhf_released**: Final document completion (deterministic)

### Key Design Decisions

- **Full lifecycle data:** Unlike CEO Review (2-week lens), closure gathers ALL risks/decisions (no date filter), 365 days of snapshots, and up to 20 meeting summaries
- **Hybrid output:** Deterministic data tables (timeline, scope, risks, DHF) combined with LLM-generated narrative (delivery outcome, success criteria, lessons learned)
- **Confluence page creation:** Uses `CREATE_CONFLUENCE_PAGE` (not update) — the closure report is a new child page of the Charter page, alongside the XFT page
- **Stateless Q&A:** Same pattern as CEO Review — no DB storage for intermediate Q&A state
- **Lessons learned categories:** Planning, Team, Technical, Implementation, Commercial, Testing, Change Management, Vendor, Documentation
