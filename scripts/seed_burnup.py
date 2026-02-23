"""Seed team_progress_snapshots with sample historical data for testing the burnup chart.

Usage:
    python scripts/seed_burnup.py [PROJECT_ID]

Defaults to project ID 1. Uses DB_PATH from .env (or seat.db).
Inserts ~30 days of data simulating scope growing slightly and done ramping up.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import sys
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "seat.db")
PROJECT_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1
DAYS = 30


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    # Verify project exists
    row = conn.execute("SELECT id, name FROM projects WHERE id = ?", (PROJECT_ID,)).fetchone()
    if not row:
        print(f"Project {PROJECT_ID} not found in {DB_PATH}. Available projects:")
        for r in conn.execute("SELECT id, name FROM projects").fetchall():
            print(f"  {r[0]}: {r[1]}")
        conn.close()
        sys.exit(1)

    print(f"Seeding burnup data for project {row[0]}: {row[1]}")

    today = date.today()
    inserted = 0

    # Per-team config: (team_key, scope_base, sp_per_day)
    TEAMS = [
        ("AIM", 500, 14),
        ("CTCV", 400, 10),
        ("YAM", 300, 6),
    ]

    for i in range(DAYS, 0, -1):
        d = (today - timedelta(days=i)).isoformat()
        day_num = DAYS - i  # 0-based day index

        per_team = []
        agg_total = 0
        agg_done = 0
        for team_key, scope_base, sp_per_day in TEAMS:
            random.seed(hash((team_key, day_num)))
            team_total = round(scope_base + 2 * day_num + random.uniform(-1, 1), 1)
            team_done = round(min(sp_per_day * day_num + random.uniform(-2, 2), team_total), 1)
            if team_done < 0:
                team_done = 0
            per_team.append({
                "team_key": team_key, "version_name": "seed",
                "sp_total": team_total, "sp_done": team_done,
            })
            agg_total += team_total
            agg_done += team_done

        sp_total = round(agg_total, 1)
        sp_done = round(agg_done, 1)

        data = json.dumps({
            "sp_total": sp_total,
            "sp_done": sp_done,
            "per_team": per_team,
        })

        conn.execute(
            "INSERT OR REPLACE INTO team_progress_snapshots "
            "(project_id, snapshot_date, data_json) VALUES (?, ?, ?)",
            (PROJECT_ID, d, data),
        )
        inserted += 1

    conn.commit()
    conn.close()
    print(f"Inserted {inserted} snapshots ({DAYS} days back from today).")
    print("Start the app and visit the Teams page to see the burnup chart.")


if __name__ == "__main__":
    main()
