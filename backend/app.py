"""
Universal AI Residential Construction Planner — Flask Backend
----------------------------------------------------------------
Orchestrates the 5-agent pipeline:

  Planning Agent -> Layout Agent -> Validator
                                          |
                          Estimation Agent + Insight Agent

(Revision Agent runs separately, on-demand, via /api/revise.)

  - planning_agent   : free-text parsing (Agent 1) + lifestyle wizard
                       planning (was lifestyle_agent), both produce the
                       same plan shape.
  - layout_agent     : recursive room geometry (Agent 2) + SVG blueprint
                       rendering (was blueprint_agent).
  - estimation_agent : budget estimate (was budget_agent) + construction
                       timeline estimate (was timeline_agent).
  - insight_agent    : post-pipeline plan analysis (was analysis_agent)
                       + engineering recommendations (was research_agent).
  - revision_agent   : Tanglish/English NLP-driven layout edits.

Run with:
    python app.py
Then open frontend/index.html in a browser (it calls this API on
http://localhost:5000).
"""

from flask import Flask, request, jsonify
from flask_cors import CORS

import planning_agent      # planning (free-text) + lifestyle wizard planning
import layout_agent        # room geometry + blueprint SVG rendering
import validator
import estimation_agent    # budget + timeline estimation
import insight_agent       # analysis + engineering recommendations
import pdf_export
import revision_agent
import db

app = Flask(__name__)
CORS(app)

# In-memory store so /api/regenerate and /api/revise can reuse the last
# plan without re-running the Planning Agent (per the "Regeneration
# Feature" and "Revision Feature" described in the project spec).
SESSION_STORE = {}

# Persistent store (SQLite) for the "Save & Compare Plans" feature — lets
# a user permanently save a generated plan and later list/fetch/compare
# 2-3 saved plans side by side. See db.py.
db.init_db()


def _build_response(plan: dict, layout: dict, house_title: str = "Preliminary Floor Plan",
                     target_budget_inr=None, region: str = "default",
                     message: str = None):
    validation = validator.validate(layout)
    svgs = layout_agent.render_all_floors(layout, house_title, facing=plan.get("facing", "South"))
    budget = estimation_agent.estimate(plan["plot_area_sqft"], floors=plan["floors"],
                                    target_budget_inr=target_budget_inr,
                                    region=region)
    recommendations = insight_agent.recommend(plan)
    timeline = estimation_agent.estimate_timeline(plan["plot_area_sqft"], floors=plan["floors"])
    analysis = insight_agent.generate(plan, layout, validation, budget, timeline,
                                        target_budget_inr=target_budget_inr)

    return {
        "plan": plan,
        "layout": layout,
        "validation": validation,
        "svg_by_floor": svgs,
        "budget": budget,
        "recommendations": recommendations,
        "timeline": timeline,
        "analysis": analysis,
        "message": message,
    }


@app.route("/api/plan", methods=["POST"])
def create_plan():
    data = request.get_json(force=True) or {}
    requirements_text = data.get("requirements", "")
    seed = int(data.get("seed", 0))
    target_budget_inr = data.get("target_budget_inr")
    target_budget_inr = float(target_budget_inr) if target_budget_inr else None
    region = data.get("region", "default")

    if not requirements_text.strip():
        return jsonify({"error": "requirements text is required"}), 400

    plan = planning_agent.parse(requirements_text)
    layout = layout_agent.generate_layout(plan, seed=seed)

    session_id = data.get("session_id", "default")
    SESSION_STORE[session_id] = {"plan": plan, "layout": layout, "seed": seed,
                                  "target_budget_inr": target_budget_inr,
                                  "region": region}

    return jsonify(_build_response(plan, layout, target_budget_inr=target_budget_inr,
                                    region=region))


@app.route("/api/plan/wizard", methods=["POST"])
def create_plan_wizard():
    """Feature 2: builds a plan from the step-by-step lifestyle wizard's
    structured answers instead of a free-text requirements string. The
    Lifestyle Agent decides the room list AND its per-floor distribution;
    everything downstream (layout generation, validation, blueprint,
    budget, timeline, analysis) is the exact same pipeline as /api/plan."""
    data = request.get_json(force=True) or {}
    seed = int(data.get("seed", 0))
    target_budget_inr = data.get("target_budget_inr")
    target_budget_inr = float(target_budget_inr) if target_budget_inr else None
    region = data.get("region", "default")

    plan = planning_agent.build_plan(data)
    layout = layout_agent.generate_layout(plan, seed=seed)

    session_id = data.get("session_id", "default")
    SESSION_STORE[session_id] = {"plan": plan, "layout": layout, "seed": seed,
                                  "target_budget_inr": target_budget_inr,
                                  "region": region}

    return jsonify(_build_response(plan, layout, target_budget_inr=target_budget_inr,
                                    region=region))


@app.route("/api/regenerate", methods=["POST"])
def regenerate():
    """Regeneration Feature: only the Layout Agent re-runs; Planning Agent
    is not re-invoked, preserving architectural intent while producing a
    new geometric arrangement."""
    data = request.get_json(force=True) or {}
    session_id = data.get("session_id", "default")

    if session_id not in SESSION_STORE:
        return jsonify({"error": "no existing plan for this session; call /api/plan first"}), 400

    session = SESSION_STORE[session_id]
    new_seed = session["seed"] + 1
    layout = layout_agent.generate_layout(session["plan"], seed=new_seed)

    session["layout"] = layout
    session["seed"] = new_seed

    return jsonify(_build_response(session["plan"], layout, target_budget_inr=session.get("target_budget_inr"),
                                    region=session.get("region", "default")))


@app.route("/api/revise", methods=["POST"])
def revise():
    """Revision Feature: natural language edits (e.g. 'Move the kitchen
    near the living room', 'Make the kitchen bigger', 'Swap Bedroom 1
    and Bedroom 2') update only the affected rooms."""
    data = request.get_json(force=True) or {}
    session_id = data.get("session_id", "default")
    instruction = data.get("instruction", "")

    if session_id not in SESSION_STORE:
        return jsonify({"error": "no existing plan for this session; call /api/plan first"}), 400

    session = SESSION_STORE[session_id]
    layout, plan, message = revision_agent.apply(session["plan"], session["layout"], instruction)
    session["layout"] = layout
    session["plan"] = plan

    return jsonify(_build_response(plan, layout, target_budget_inr=session.get("target_budget_inr"),
                                    region=session.get("region", "default"), message=message))


@app.route("/api/export/pdf", methods=["POST"])
def export_pdf():
    """Export Feature: generates a downloadable PDF containing the floor
    plan summary (room-by-room dimensions per floor), the blueprint
    drawing for each floor, and the full budget report (cost breakdown,
    material estimate)."""
    data = request.get_json(force=True) or {}
    session_id = data.get("session_id", "default")

    if session_id not in SESSION_STORE:
        return jsonify({"error": "no existing plan for this session; call /api/plan first"}), 400

    session = SESSION_STORE[session_id]
    plan = session["plan"]
    layout = session["layout"]
    budget = estimation_agent.estimate(plan["plot_area_sqft"], floors=plan["floors"],
                                    target_budget_inr=session.get("target_budget_inr"),
                                    region=session.get("region", "default"))
    svgs = layout_agent.render_all_floors(layout, house_title="Preliminary Floor Plan",
                                           facing=plan.get("facing", "South"))

    pdf_bytes = pdf_export.build_report_pdf(plan, layout, budget, svg_by_floor=svgs)

    from flask import Response
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=construction_plan_report.pdf"},
    )


@app.route("/api/plans/save", methods=["POST"])
def save_plan():
    """Save & Compare Plans feature: persists the session's current plan
    (plan + layout + budget + blueprint SVGs + timeline) to SQLite so it
    survives past this session and can be compared against other saved
    plans later."""
    data = request.get_json(force=True) or {}
    session_id = data.get("session_id", "default")
    name = data.get("name", "").strip()

    if session_id not in SESSION_STORE:
        return jsonify({"error": "no existing plan for this session; call /api/plan first"}), 400

    session = SESSION_STORE[session_id]
    plan = session["plan"]
    layout = session["layout"]
    region = session.get("region", "default")
    target_budget_inr = session.get("target_budget_inr")

    validation = validator.validate(layout)
    svgs = layout_agent.render_all_floors(layout, facing=plan.get("facing", "South"))
    budget = estimation_agent.estimate(plan["plot_area_sqft"], floors=plan["floors"],
                                    target_budget_inr=target_budget_inr, region=region)
    timeline = estimation_agent.estimate_timeline(plan["plot_area_sqft"], floors=plan["floors"])

    if not name:
        name = f"{plan['plot_area_sqft']} sqft · {plan['floors']}-floor"

    plan_id = db.save_plan(name, plan, layout, budget, svgs, timeline=timeline,
                            region=region)

    return jsonify({"id": plan_id, "name": name, "validation": validation})


@app.route("/api/plans", methods=["GET"])
def list_saved_plans():
    """Returns lightweight summaries of every saved plan (for the 'My
    Plans' list) — not the full SVG/layout payloads, to keep it light."""
    return jsonify({"plans": db.list_plans()})


@app.route("/api/plans/<int:plan_id>", methods=["GET"])
def get_saved_plan(plan_id):
    record = db.get_plan(plan_id)
    if not record:
        return jsonify({"error": "plan not found"}), 404
    return jsonify(record)


@app.route("/api/plans/<int:plan_id>", methods=["DELETE"])
def delete_saved_plan(plan_id):
    deleted = db.delete_plan(plan_id)
    if not deleted:
        return jsonify({"error": "plan not found"}), 404
    return jsonify({"deleted": True, "id": plan_id})


@app.route("/api/plans/compare", methods=["POST"])
def compare_saved_plans():
    """Save & Compare Plans feature: given 2-3 saved plan ids, returns
    their full records together so the frontend can render them
    side-by-side (cost, built-up area, layout/blueprint, timeline)."""
    data = request.get_json(force=True) or {}
    ids = data.get("ids", [])
    if not isinstance(ids, list) or not (2 <= len(ids) <= 3):
        return jsonify({"error": "provide 2 or 3 plan ids to compare"}), 400

    records = db.get_plans(ids)
    if len(records) != len(ids):
        return jsonify({"error": "one or more plan ids were not found"}), 404

    return jsonify({"plans": records})


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)