"""Seed fake historical snapshots for HOP: Drop 4 (project 12) for overlay testing.

Run:  python scripts/seed_drop4_test.py
Undo: python scripts/seed_drop4_test.py --undo
"""

import json
import sqlite3
import sys
from datetime import date, timedelta

DB_PATH = "seat.db"
PROJECT_ID = 12

# Drop 3 latest: ~2318 SP total, ~862 done, velocity ~16 SP/day
# Drop 4 target: similar scope (~2200 SP), 1/4 velocity (~4 SP/day)
# Release date: 2026-05-06
# Same teams as Drop 3, similar proportions

TEAMS = [
    # (team_key, version_name, final_scope, pct_of_total_done)
    ("AIM",  "HOP: Drop 4",  50.0,   0.02),
    ("CTCV", "HOP: Drop 4",  40.0,   0.01),
    ("YAM",  "HOP: Drop 4",  1100.0, 0.55),
    ("V2B",  "HOP: Drop 4",  680.0,  0.30),
    ("V2F",  "HOP: Drop 4",  330.0,  0.12),
]

TOTAL_SCOPE = sum(t[2] for t in TEAMS)  # ~2200

# Generate snapshots from 2026-02-24 to 2026-03-13 (matching Drop 3 range)
START = date(2026, 2, 24)
END = date(2026, 3, 13)

def generate_snapshots():
    """Build snapshot rows with gradual scope ramp-up and slow done growth."""
    snapshots = []
    d = START
    day_num = 0
    total_days = (END - START).days

    while d <= END:
        # Scope ramps up over first 2 weeks, then stabilises
        scope_pct = min(1.0, 0.6 + 0.4 * (day_num / max(total_days * 0.6, 1)))
        # Done grows at ~4 SP/day (1/4 of Drop 3's ~16 SP/day)
        total_done = min(4.0 * day_num, TOTAL_SCOPE * 0.15)  # cap at 15%

        per_team = []
        for team_key, version_name, final_scope, done_share in TEAMS:
            team_scope = round(final_scope * scope_pct, 2)
            team_done = round(total_done * done_share, 2)
            per_team.append({
                "team_key": team_key,
                "version_name": version_name,
                "sp_total": team_scope,
                "sp_done": min(team_done, team_scope),
                "total_issues": int(team_scope / 3),
                "done_count": int(min(team_done, team_scope) / 3),
            })

        sp_total = round(sum(t["sp_total"] for t in per_team), 2)
        sp_done = round(sum(t["sp_done"] for t in per_team), 2)

        snapshots.append({
            "date": d.isoformat(),
            "data": {
                "sp_total": sp_total,
                "sp_done": sp_done,
                "per_team": per_team,
            },
        })

        # Irregular intervals like real data
        d += timedelta(days=3 if day_num < 7 else 2)
        day_num = (d - START).days

    return snapshots


def seed():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    # Set project to active so it shows in overlay
    conn.execute("UPDATE projects SET status = 'active' WHERE id = ?", (PROJECT_ID,))

    # Remove existing snapshots for this project (the single real one)
    conn.execute("DELETE FROM team_progress_snapshots WHERE project_id = ?", (PROJECT_ID,))

    snapshots = generate_snapshots()
    for s in snapshots:
        conn.execute(
            "INSERT INTO team_progress_snapshots (project_id, snapshot_date, data_json) VALUES (?, ?, ?)",
            (PROJECT_ID, s["date"], json.dumps(s["data"])),
        )

    conn.commit()
    print(f"Seeded {len(snapshots)} snapshots for project {PROJECT_ID}")
    print(f"Set project {PROJECT_ID} status to 'active'")

    # Verify
    row = conn.execute(
        "SELECT COUNT(*), MIN(snapshot_date), MAX(snapshot_date) FROM team_progress_snapshots WHERE project_id = ?",
        (PROJECT_ID,),
    ).fetchone()
    print(f"  {row[0]} snapshots from {row[1]} to {row[2]}")
    conn.close()


def undo():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    # Delete seeded snapshots
    conn.execute("DELETE FROM team_progress_snapshots WHERE project_id = ?", (PROJECT_ID,))

    # Restore original status
    conn.execute("UPDATE projects SET status = 'spinning_up' WHERE id = ?", (PROJECT_ID,))

    conn.commit()
    print(f"Removed all snapshots for project {PROJECT_ID}")
    print(f"Restored project {PROJECT_ID} status to 'spinning_up'")
    conn.close()


if __name__ == "__main__":
    if "--undo" in sys.argv:
        undo()
    else:
        seed()
