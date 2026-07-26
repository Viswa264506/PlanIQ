"""
Persistence Layer — SQLite
---------------------------
Adds a real backend/data layer on top of the previously purely in-memory
SESSION_STORE in app.py. This lets a user permanently save a generated
plan (name + plan + layout + budget + blueprint SVGs + timeline) and
later list, fetch, or compare 2-3 saved plans side by side.

Uses the Python standard library only (sqlite3) — no extra dependency
needed. The DB file lives next to this module as plans.db and is created
automatically on first run.
"""

import sqlite3
import json
import os
import time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plans.db")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Creates the saved_plans table if it doesn't already exist. Safe to
    call on every app startup."""
    conn = _conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            layout_json TEXT NOT NULL,
            budget_json TEXT NOT NULL,
            svg_json TEXT NOT NULL,
            timeline_json TEXT,
            region TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def save_plan(name: str, plan: dict, layout: dict, budget: dict, svg_by_floor: dict,
              timeline: dict = None, region: str = "default") -> int:
    """Persists one full generated plan. Returns the new row's id."""
    conn = _conn()
    cur = conn.execute(
        """INSERT INTO saved_plans
           (name, created_at, plan_json, layout_json, budget_json, svg_json, timeline_json, region)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            name.strip() or "Untitled Plan",
            time.strftime("%Y-%m-%d %H:%M:%S"),
            json.dumps(plan),
            json.dumps(layout),
            json.dumps(budget),
            json.dumps(svg_by_floor),
            json.dumps(timeline) if timeline else None,
            region,
        ),
    )
    conn.commit()
    plan_id = cur.lastrowid
    conn.close()
    return plan_id


def _row_to_summary(row) -> dict:
    plan = json.loads(row["plan_json"])
    budget = json.loads(row["budget_json"])
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "plot_area_sqft": plan.get("plot_area_sqft"),
        "floors": plan.get("floors"),
        "facing": plan.get("facing"),
        "bedrooms_requested": plan.get("bedrooms_requested"),
        "built_up_area_sqft": budget.get("built_up_area_sqft"),
        "estimated_total_cost_inr": budget.get("estimated_total_cost_inr"),
        "region": row["region"],
    }


def list_plans() -> list:
    """Returns lightweight summaries (for the 'My Plans' list), newest first."""
    conn = _conn()
    rows = conn.execute(
        "SELECT id, name, created_at, plan_json, budget_json, region "
        "FROM saved_plans ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [_row_to_summary(r) for r in rows]


def _row_to_full(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "plan": json.loads(row["plan_json"]),
        "layout": json.loads(row["layout_json"]),
        "budget": json.loads(row["budget_json"]),
        "svg_by_floor": json.loads(row["svg_json"]),
        "timeline": json.loads(row["timeline_json"]) if row["timeline_json"] else None,
        "region": row["region"],
    }


def get_plan(plan_id: int):
    """Returns the full saved record (plan/layout/budget/svgs/timeline), or None."""
    conn = _conn()
    row = conn.execute("SELECT * FROM saved_plans WHERE id=?", (plan_id,)).fetchone()
    conn.close()
    return _row_to_full(row) if row else None


def get_plans(ids) -> list:
    """Returns full records for a list of ids, preserving the given order
    and silently skipping any id that no longer exists."""
    by_id = {}
    conn = _conn()
    if ids:
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT * FROM saved_plans WHERE id IN ({placeholders})", list(ids)
        ).fetchall()
        by_id = {r["id"]: _row_to_full(r) for r in rows}
    conn.close()
    return [by_id[i] for i in ids if i in by_id]


def delete_plan(plan_id: int) -> bool:
    conn = _conn()
    cur = conn.execute("DELETE FROM saved_plans WHERE id=?", (plan_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted