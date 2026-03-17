"""Consolidated Jira field IDs, issue type IDs, and project keys.

All magic strings from the Jira API live here — no hardcoded field IDs
or project keys should appear elsewhere in the codebase.
"""

# ---------------------------------------------------------------------------
# Project keys
# ---------------------------------------------------------------------------

PROG_PROJECT_KEY = "PROG"
RISK_PROJECT_KEY = "RISK"

# ---------------------------------------------------------------------------
# Issue type IDs
# ---------------------------------------------------------------------------

ISSUE_TYPE_RISK = "10832"
ISSUE_TYPE_DECISION = "12499"  # "Project Decision" type in RISK project (formerly "Project Issue")

# ---------------------------------------------------------------------------
# Custom field IDs — Risk / Decision fields
# ---------------------------------------------------------------------------

FIELD_IMPACT_ANALYSIS = "customfield_11166"
FIELD_MITIGATION_CONTROL = "customfield_11342"
FIELD_TIMELINE_IMPACT = "customfield_13267"

# ---------------------------------------------------------------------------
# Custom field IDs — Goal-level risk metrics
# ---------------------------------------------------------------------------

FIELD_RISK_THRESHOLD = "customfield_13265"
FIELD_RISK_POINTS = "customfield_13264"
FIELD_RISK_LEVEL = "customfield_13266"

# ---------------------------------------------------------------------------
# Custom field IDs — Release priority / PI State
# ---------------------------------------------------------------------------

FIELD_RELEASE_PRIORITY_A = "customfield_12812"
FIELD_RELEASE_PRIORITY_B = "customfield_11054"
FIELD_PI_STATE = "customfield_13530"

# ---------------------------------------------------------------------------
# Custom field IDs — Story points
# ---------------------------------------------------------------------------

FIELD_STORY_POINTS_NEXTGEN = "customfield_10016"
FIELD_STORY_POINTS_CLASSIC = "customfield_10026"
