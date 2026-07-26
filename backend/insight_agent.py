"""
Agent — AI Project Analysis
----------------------------
Runs AFTER the full pipeline (Planning -> Layout -> Validation -> Budget ->
Timeline) and produces the "AI Project Analysis Card": an architect-style
read of the plan that was actually generated, not a restatement of the
user's inputs.

Everything here is computed dynamically from the plan/layout/validation/
budget/timeline objects that are already on hand — nothing is hardcoded.
When GROQ_API_KEY is configured, the numeric facts are handed to the LLM
to be written up as a short "Overall Assessment" in an architect's voice;
otherwise (or if that call fails) a deterministic, still data-driven
paragraph is assembled instead, so the feature always works.
"""

import llm_client

# Rough recommended minimum livable area (sqft) per room type, used only
# to flag rooms that came out cramped after the recursive partition —
# not a hard rule, the layout algorithm itself is untouched.
MIN_RECOMMENDED_AREA_SQFT = {
    "Living Room": 120,
    "Family Hall": 140,
    "Kitchen": 70,
    "Master Bedroom": 120,
    "Bedroom": 100,
    "Bathroom": 25,
    "Attached Bathroom": 30,
    "Common Bathroom": 25,
    "Pooja Room": 16,
    "Parking": 100,
    "Dining": 80,
    "Open Terrace": 60,
    "Staircase": 0,
}


def _min_area_for(name: str) -> float:
    if name in MIN_RECOMMENDED_AREA_SQFT:
        return MIN_RECOMMENDED_AREA_SQFT[name]
    if name.startswith("Bedroom"):
        return MIN_RECOMMENDED_AREA_SQFT["Bedroom"]
    if "Bathroom" in name:
        return MIN_RECOMMENDED_AREA_SQFT["Bathroom"]
    return 60.0


def _touches_exterior(room: dict, plot_w: float, plot_h: float, eps: float = 0.75) -> bool:
    """A room that shares an edge with the outer plot boundary can have a
    window on that wall (natural light/ventilation). Purely interior rooms
    (no boundary-touching edge) cannot, and get flagged below."""
    return (
        room["x"] <= eps
        or room["y"] <= eps
        or room["x"] + room["width"] >= plot_w - eps
        or room["y"] + room["height"] >= plot_h - eps
    )


def _project_type(plan: dict) -> str:
    bedrooms = plan.get("bedrooms_requested", 0)
    floors = plan.get("floors", 1)
    label = f"Residential {bedrooms}BHK" if bedrooms else "Residential"
    if floors > 1:
        label += f", {floors}-floor (G+{floors - 1})"
    return label


def _buildability(validation: dict, room_flags: list) -> dict:
    cramped = [r for r in room_flags if r["flag"] == "cramped"]
    if not validation["valid"]:
        return {
            "buildable": False,
            "reason": (
                "The generated layout failed structural validation "
                f"({len(validation['errors'])} issue(s): "
                + "; ".join(validation["errors"][:3])
                + (", …" if len(validation["errors"]) > 3 else "")
                + "). It should be regenerated or revised before construction."
            ),
        }
    if cramped:
        names = ", ".join(r["name"] for r in cramped[:3])
        return {
            "buildable": True,
            "reason": (
                "Zero overlaps and every room sits fully inside the plot boundary, "
                f"so this is structurally buildable. A few rooms ({names}) came out "
                "smaller than typically comfortable and are worth revising before finalizing."
            ),
        }
    return {
        "buildable": True,
        "reason": (
            "The layout passed all validation checks — no overlapping rooms, no "
            "boundary violations, and every room meets a comfortable minimum size. "
            "This design is practically buildable as generated."
        ),
    }


def _plot_utilization(layout: dict) -> float:
    plot_w, plot_h = layout["plot_width"], layout["plot_height"]
    footprint = plot_w * plot_h
    ground = layout["floors"].get(1) or layout["floors"].get(min(layout["floors"].keys()))
    if not ground or footprint <= 0:
        return 0.0
    used = sum(r["area"] for r in ground if r["name"] != "Staircase")
    return round(min(used / footprint, 1.0) * 100, 1)


def _cost_summary(budget: dict) -> dict:
    selected_cost = budget.get("estimated_total_cost_inr")
    message = (
        f"This build is priced at roughly ₹{selected_cost:,.0f} for this "
        "built-up area, based on current regional material and labour rates "
        "— realistic for the design as generated."
    ) if selected_cost is not None else "Cost could not be computed."
    return {"message": message}


def _budget_compatibility(budget: dict, target_budget_inr) -> dict:
    fit = budget.get("budget_fit")
    if not target_budget_inr or not fit:
        return {
            "target_provided": False,
            "message": "No target budget was provided, so this reflects the plain cost estimate rather than a fit check.",
        }
    within = fit.get("within_budget", fit.get("fits", None))
    return {
        "target_provided": True,
        "within_budget": within,
        "message": fit.get("note") or fit.get("message") or (
            "Fits within the stated target budget." if within else
            "Exceeds the stated target budget for this build."
        ),
    }


def _room_analysis(layout: dict, plan: dict) -> list:
    room_meta = {r["name"]: r for r in plan.get("rooms", [])}
    plot_w, plot_h = layout["plot_width"], layout["plot_height"]
    results = []
    for floor_num, rooms in sorted(layout["floors"].items()):
        for room in rooms:
            name = room["name"]
            area = room.get("area", 0)
            min_area = _min_area_for(name)
            flag = "ok"
            notes = []

            if name == "Staircase":
                notes.append("Connects the floors; footprint reserved outside the main tiled area.")
            else:
                if area < min_area:
                    flag = "cramped"
                    notes.append(
                        f"{area:.0f} sqft is below the ~{min_area:.0f} sqft comfortable minimum for this room type."
                    )
                else:
                    notes.append(f"{area:.0f} sqft — comfortable for its purpose.")

                exterior = _touches_exterior(room, plot_w, plot_h)
                if exterior:
                    notes.append("Sits on an outer wall, so natural lighting and cross-ventilation are feasible.")
                elif name not in ("Bathroom", "Attached Bathroom", "Common Bathroom", "Pooja Room"):
                    flag = "cramped" if flag == "cramped" else "interior"
                    notes.append("Fully interior room — no exterior wall, so it will depend on borrowed/artificial lighting and ventilation.")

                meta = room_meta.get(name, {})
                preferred = meta.get("preferred_direction")
                if preferred and preferred not in ("Center", "Left", "Right"):
                    notes.append(f"Placed with a {preferred} orientation preference in mind.")

            results.append({
                "floor": floor_num,
                "name": name,
                "area_sqft": area,
                "flag": flag,
                "notes": " ".join(notes),
            })
    return results


def _future_expansion(plan: dict) -> dict:
    floors = plan.get("floors", 1)
    if floors >= 4:
        return {
            "possible": False,
            "notes": "Already at 4 floors in this plan; further vertical expansion would need a fresh structural review.",
        }
    return {
        "possible": True,
        "notes": (
            f"Adding a floor above the current {floors}-floor design is generally feasible, "
            "though the footing and column sizing should be re-verified by a structural engineer. "
            "Assumption: the staircase position in this layout is retained as-is for continuity to the new floor."
        ),
    }


def _overall_assessment_rule_based(plan, buildability, cost_summary, budget_compat, room_flags, future) -> str:
    cramped = [r["name"] for r in room_flags if r["flag"] == "cramped"]
    bedrooms = plan.get("bedrooms_requested", 0)
    family_line = {
        1: "a single occupant or couple",
        2: "a small family",
    }.get(bedrooms, "a larger family" if bedrooms >= 3 else "the intended occupants")

    sentences = [
        f"This layout is suitable for {family_line}."
    ]
    if buildability["buildable"]:
        sentences.append("It is structurally buildable as generated, with no overlaps or boundary violations.")
    else:
        sentences.append("It currently has structural issues that should be resolved before construction.")

    sentences.append(cost_summary["message"])

    if cramped:
        sentences.append(
            "Minor improvements are recommended in " + ", ".join(cramped[:3]) +
            (" and other rooms" if len(cramped) > 3 else "") + " to bring them up to a comfortable size."
        )
    else:
        sentences.append("Every room meets a comfortable minimum size, so no resizing is strictly necessary.")

    if budget_compat.get("target_provided"):
        sentences.append(budget_compat["message"])

    sentences.append(future["notes"])

    return " ".join(sentences)


def _overall_assessment_llm(plan, buildability, cost_summary, budget_compat, room_flags, future) -> str:
    cramped = [r["name"] for r in room_flags if r["flag"] == "cramped"]
    facts = (
        f"Project: {plan.get('bedrooms_requested')}BHK, {plan.get('floors')} floor(s), "
        f"facing {plan.get('facing')}.\n"
        f"Buildable: {buildability['buildable']} — {buildability['reason']}\n"
        f"Cost note: {cost_summary['message']}\n"
        f"Cramped rooms: {', '.join(cramped) if cramped else 'none'}\n"
        f"Budget fit: {budget_compat.get('message')}\n"
        f"Future expansion: {future['notes']}\n"
    )
    system = (
        "You are an experienced residential architect giving a short, direct written "
        "opinion on a house design that has already been generated. Write 3-5 plain "
        "sentences, in the voice of an architect briefing a client — confident, specific, "
        "no headings, no markdown, no bullet points. Only use the facts given; do not "
        "invent numbers you were not given."
    )
    user = f"Facts about the generated design:\n{facts}\nWrite the overall assessment now."
    return llm_client.call_llm(system, user, temperature=0.4).strip()


def generate(plan: dict, layout: dict, validation: dict, budget: dict, timeline: dict,
             target_budget_inr=None) -> dict:
    """Builds the full AI Project Analysis card payload."""
    room_flags = _room_analysis(layout, plan)
    buildability = _buildability(validation, room_flags)
    cost_summary = _cost_summary(budget)
    budget_compat = _budget_compatibility(budget, target_budget_inr)
    future = _future_expansion(plan)
    utilization = _plot_utilization(layout)
    built_up_area = budget.get("built_up_area_sqft", plan.get("plot_area_sqft", 0) * plan.get("floors", 1))

    overall = None
    if llm_client.is_configured():
        try:
            overall = _overall_assessment_llm(plan, buildability, cost_summary, budget_compat,
                                               room_flags, future)
        except Exception as e:
            print(f"[analysis_agent] LLM overall assessment failed, falling back: {e}")
    if not overall:
        overall = _overall_assessment_rule_based(plan, buildability, cost_summary, budget_compat, room_flags, future)

    return {
        "project_type": _project_type(plan),
        "buildability": buildability,
        "plot_utilization_percent": utilization,
        "built_up_area_sqft": round(built_up_area, 1),
        "cost_summary": cost_summary,
        "budget_compatibility": budget_compat,
        "room_analysis": room_flags,
        "future_expansion": future,
        "overall_assessment": overall,
    }


# ======================================================================
# Merged in from research_agent.py (engineering recommendations)
# ======================================================================

"""
Agent 5 — Research Agent
--------------------------
Provides engineering recommendations: construction suggestions, space
utilization advice, sustainability recommendations, ventilation guidance,
and future expansion possibilities.

Rule-based here for reproducibility without external API dependency; can
be swapped for an LLM call that reasons over the specific plan JSON.
"""


import json

import llm_client

RESEARCH_SYSTEM_PROMPT = """You are a senior civil engineer and residential
design consultant. Given a structured house plan JSON, produce 5-8 concise,
practical engineering recommendations covering: construction suggestions,
space utilization, sustainability, ventilation, and future expansion.

Respond with ONLY a JSON object of this exact shape, no explanation, no
markdown fences:

{ "recommendations": ["<tip 1>", "<tip 2>", "..."] }

Each tip should be one or two sentences, specific to the given plan (facing
direction, floors, and rooms present) rather than generic filler.
"""


def _recommend_with_llm(plan: dict) -> list:
    user_prompt = f"House plan JSON:\n{json.dumps(plan)}\n\nReturn the recommendations JSON now."
    result = llm_client.call_llm_json(RESEARCH_SYSTEM_PROMPT, user_prompt)

    if not isinstance(result, dict) or "recommendations" not in result:
        raise ValueError("LLM returned an unexpected recommendations shape.")
    tips = result["recommendations"]
    if not isinstance(tips, list) or not tips:
        raise ValueError("LLM returned an empty recommendations list.")
    return tips


def recommend(plan: dict) -> list:
    """
    Provides engineering recommendations for the given plan.

    Uses the Groq LLM when GROQ_API_KEY is configured; otherwise (or if
    the LLM call fails) falls back to the deterministic rule-based tips,
    so the pipeline always completes.
    """
    if llm_client.is_configured():
        try:
            return _recommend_with_llm(plan)
        except Exception as e:
            print(f"[research_agent] LLM recommend failed, falling back to rule-based tips: {e}")

    return _recommend_rule_based(plan)


def _recommend_rule_based(plan: dict) -> list:
    tips = []
    facing = plan.get("facing", "East")
    floors = plan.get("floors", 1)
    room_names = [r["name"] for r in plan.get("rooms", [])]

    tips.append(
        f"Since the plot faces {facing}, orient the main entrance and "
        f"living room windows toward {facing} to maximize natural morning light."
    )

    if "Pooja Room" in room_names:
        tips.append(
            "Vaastu convention favors placing the Pooja Room in the "
            "North-East corner of the house, away from bathrooms and staircases."
        )

    if any(name.startswith("Bedroom") for name in room_names) or "Master Bedroom" in room_names:
        tips.append(
            "Provide cross-ventilation in all bedrooms by placing windows "
            "on two different walls where possible, improving airflow and reducing cooling costs."
        )

    if "Kitchen" in room_names:
        tips.append(
            "Position the kitchen with a window or exhaust facing outward "
            "to vent cooking heat and odors, and keep it adjacent to the dining area for convenience."
        )

    if floors == 2:
        tips.append(
            "Keep the staircase position identical on both floors and use "
            "RCC construction for the first-floor slab to allow future vertical expansion (e.g., a second floor later)."
        )
    else:
        tips.append(
            "Design the foundation and columns to support at least one "
            "additional floor in the future, even if only a single floor is built now — this avoids expensive retrofitting later."
        )

    tips.append(
        "Consider rainwater harvesting near the parking or terrace area "
        "and use fly-ash bricks or AAC blocks for walls to improve sustainability and thermal comfort."
    )

    tips.append(
        "Leave at least a 3 ft setback on all sides of the plot (where "
        "local building bylaws allow) for maintenance access and better ventilation between the house and boundary wall."
    )

    return tips
