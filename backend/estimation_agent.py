"""
Agent 4 — Budget Estimation Agent
-----------------------------------
Estimates construction budget from built-up area and room configuration.
Produces a structured cost breakdown, not just a single total.

In production this stage is meant to call an LLM for more nuanced,
location-aware estimation. A transparent rule-based calculation is used
here so the project runs end-to-end without external API dependencies.
"""

import llm_client

# Approximate construction rate per sqft (INR).
RATE_PER_SQFT = 1850

COST_BREAKDOWN_PERCENT = {
    "Structure (RCC, walls, foundation)": 0.42,
    "Finishing (flooring, painting, false ceiling)": 0.25,
    "Electrical work": 0.10,
    "Plumbing & sanitary": 0.08,
    "Doors & windows": 0.08,
    "Miscellaneous & contingency": 0.07,
}

# Regional cost multiplier applied on top of the base rate — reflects
# typical local material/labor cost variance across Indian cities.
# "default" is used for any region not explicitly listed.
REGION_MULTIPLIERS = {
    "coimbatore": 0.92,
    "chennai": 1.05,
    "bangalore": 1.15,
    "hyderabad": 1.00,
    "mumbai": 1.35,
    "pune": 1.10,
    "delhi": 1.20,
    "kochi": 0.95,
    "madurai": 0.88,
    "default": 1.00,
}

# Rough per-sqft material quantity norms for a typical RCC-frame Indian
# residential build. These are ballpark planning figures, not a bill of
# quantities — actual requirements depend on structural design.
MATERIAL_NORMS_PER_SQFT = {
    "Cement (bags)": 0.40,
    "Steel/TMT bars (kg)": 4.0,
    "Bricks/Blocks (units)": 8.5,
    "Sand (cft)": 1.6,
    "Aggregate/Jelly (cft)": 1.2,
    "Paint (litres)": 0.12,
}


def _normalize_region(region: str) -> str:
    if not region:
        return "default"
    key = region.strip().lower()
    return key if key in REGION_MULTIPLIERS else "default"


BUDGET_SYSTEM_PROMPT = """You are a construction cost estimation assistant for
Indian residential projects. Given the built-up area and number of floors,
return ONLY a JSON object with EXACTLY this shape:

{
  "built_up_area_sqft": <number>,
  "rate_per_sqft_inr": <number>,
  "estimated_total_cost_inr": <number>,
  "cost_breakdown_inr": {
    "Structure (RCC, walls, foundation)": <number>,
    "Finishing (flooring, painting, false ceiling)": <number>,
    "Electrical work": <number>,
    "Plumbing & sanitary": <number>,
    "Doors & windows": <number>,
    "Miscellaneous & contingency": <number>
  },
  "disclaimer": "<one sentence disclaimer that this is a preliminary estimate only>"
}

The six cost_breakdown_inr values must sum to approximately
estimated_total_cost_inr. Use realistic current Indian construction rates.
Respond with ONLY the JSON object, no explanation, no markdown fences.
"""


def _estimate_with_llm(plot_area_sqft: float, floors: int) -> dict:
    built_up_area = plot_area_sqft * floors
    user_prompt = (
        f"Built-up area: {built_up_area} sqft (plot {plot_area_sqft} sqft x {floors} floor(s)).\n"
        f"Location: India (general/typical rates).\n"
        f"Return the budget JSON now."
    )
    result = llm_client.call_llm_json(BUDGET_SYSTEM_PROMPT, user_prompt)

    required_keys = {"built_up_area_sqft", "rate_per_sqft_inr",
                      "estimated_total_cost_inr", "cost_breakdown_inr", "disclaimer"}
    if not isinstance(result, dict) or not required_keys.issubset(result.keys()):
        raise ValueError("LLM returned an unexpected budget shape.")
    if not isinstance(result["cost_breakdown_inr"], dict) or not result["cost_breakdown_inr"]:
        raise ValueError("LLM returned an empty/invalid cost breakdown.")

    return result


def _estimate_rule_based(plot_area_sqft: float, floors: int, region: str = "default") -> dict:
    region_key = _normalize_region(region)
    region_multiplier = REGION_MULTIPLIERS[region_key]
    adjusted_rate = round(RATE_PER_SQFT * region_multiplier)

    built_up_area = plot_area_sqft * floors
    total_cost = built_up_area * adjusted_rate

    breakdown = {
        label: round(total_cost * pct)
        for label, pct in COST_BREAKDOWN_PERCENT.items()
    }

    return {
        "built_up_area_sqft": built_up_area,
        "region": region_key,
        "region_multiplier": region_multiplier,
        "base_rate_per_sqft_inr": RATE_PER_SQFT,
        "rate_per_sqft_inr": adjusted_rate,
        "estimated_total_cost_inr": round(total_cost),
        "cost_breakdown_inr": breakdown,
        "disclaimer": (
            "This is a preliminary, conceptual estimate for early planning "
            "only. Actual costs vary by location, material choice, labor "
            "rates, and design changes. Consult a licensed contractor or "
            "civil engineer for an accurate quotation."
        ),
    }


def _material_estimate(built_up_area_sqft: float) -> dict:
    """Rough material-wise quantity estimate scaled by built-up area."""
    return {
        label: round(built_up_area_sqft * per_sqft, 1)
        for label, per_sqft in MATERIAL_NORMS_PER_SQFT.items()
    }


def _budget_fit_analysis(built_up_area_sqft: float, target_budget_inr: float) -> dict:
    """
    Given a fixed built-up area and the user's target budget, works out
    whether the target budget comfortably covers, is tight for, or falls
    short of, the requested area — and, if not, what area it would afford.
    """
    implied_rate = target_budget_inr / built_up_area_sqft if built_up_area_sqft else 0
    cost_at_requested_area = round(built_up_area_sqft * RATE_PER_SQFT)
    area_affordable = round(target_budget_inr / RATE_PER_SQFT) if RATE_PER_SQFT else 0

    if target_budget_inr >= cost_at_requested_area * 1.15:
        fit_status = "comfortable"
        fit_message = (
            f"Your budget of ₹{target_budget_inr:,.0f} comfortably covers this "
            f"{built_up_area_sqft:.0f} sqft built-up area, with room for a higher finish level."
        )
    elif target_budget_inr >= cost_at_requested_area * 0.9:
        fit_status = "adequate"
        fit_message = (
            f"Your budget of ₹{target_budget_inr:,.0f} is a good match for this "
            f"{built_up_area_sqft:.0f} sqft built-up area."
        )
    else:
        fit_status = "tight"
        fit_message = (
            f"Your budget of ₹{target_budget_inr:,.0f} is tight for "
            f"{built_up_area_sqft:.0f} sqft — consider reducing built-up area to about "
            f"{area_affordable} sqft, or revisiting material/finish choices."
        )

    return {
        "target_budget_inr": target_budget_inr,
        "implied_rate_per_sqft_inr": round(implied_rate),
        "fit_status": fit_status,
        "fit_message": fit_message,
        "area_affordable_sqft": area_affordable,
        "cost_at_requested_area_inr": cost_at_requested_area,
    }


def estimate(plot_area_sqft: float, floors: int = 1,
             target_budget_inr: float = None, region: str = "default") -> dict:
    """
    Estimates the construction budget for the given plot area/floors.

    `region` applies a local cost multiplier on top of the base rate
    (see REGION_MULTIPLIERS). The result always includes a material-wise
    quantity estimate.

    If `target_budget_inr` is provided, also returns a "budget_fit"
    section comparing the user's target budget against what the
    requested built-up area actually costs.

    Uses the Groq LLM when GROQ_API_KEY is configured; otherwise (or if
    the LLM call fails) falls back to the deterministic rule-based
    calculation, so the pipeline always completes.
    """
    if llm_client.is_configured():
        try:
            result = _estimate_with_llm(plot_area_sqft, floors)
            result.setdefault("region", _normalize_region(region))
            result.setdefault("region_multiplier", REGION_MULTIPLIERS[_normalize_region(region)])
        except Exception as e:
            print(f"[budget_agent] LLM estimate failed, falling back to rule-based calculation: {e}")
            result = _estimate_rule_based(plot_area_sqft, floors, region)
    else:
        result = _estimate_rule_based(plot_area_sqft, floors, region)

    built_up_area = result.get("built_up_area_sqft", plot_area_sqft * floors)

    result["material_estimate"] = _material_estimate(built_up_area)

    if target_budget_inr:
        result["budget_fit"] = _budget_fit_analysis(built_up_area, target_budget_inr)

    return result


# ======================================================================
# Merged in from timeline_agent.py (construction timeline estimation)
# ======================================================================

"""
Agent 6 — Construction Timeline Estimator Agent
--------------------------------------------------
Deterministic, rule-based (no LLM call, same reasoning as blueprint_agent):
breaks the build down into four sequential phases —

    Foundation -> Structure -> Roofing -> Finishing

— and estimates a duration in days for each, scaled by built-up area and
floor count. Pairs naturally with the Budget Agent since both are derived
from the same plot_area/floors inputs, so the frontend can show cost and
time side by side.

These are ballpark planning durations for early-stage decision making,
not a contractor-grade construction schedule.
"""

BASE_AREA_SQFT = 1000.0  # calibration reference: ~1000 sqft, single floor

# Baseline days per phase at the reference area/floor.
BASE_PHASE_DAYS = {
    "Foundation": 18,
    "Structure": 45,
    "Roofing": 15,
    "Finishing": 40,
}

PHASE_DESCRIPTIONS = {
    "Foundation": "Site excavation, footings, PCC/RCC foundation and plinth beam work.",
    "Structure": "Column, beam and slab RCC framework plus brick/block walling, floor by floor.",
    "Roofing": "Roof slab casting (or truss/sheet roofing) and terrace waterproofing.",
    "Finishing": "Plastering, flooring, painting, electrical, plumbing and fixture installation.",
}

# Each additional floor doesn't cost a full extra floor's worth of time —
# the foundation is a one-time cost, and repeated floors benefit from
# crews/formwork already being set up.
EXTRA_FLOOR_MULTIPLIER = 0.65

MIN_PHASE_DAYS = 5


def estimate_timeline(plot_area_sqft: float, floors: int = 1) -> dict:
    """
    Returns:
      {
        "phases": [
          {"phase", "description", "duration_days", "start_day", "end_day", "percent_of_total"},
          ...
        ],
        "total_days": int,
        "total_weeks": float,
        "total_months": float,
        "estimated_completion_note": str,
      }

    Phases are modeled sequentially (no overlap) to keep the Gantt simple
    and readable; in a real project some phases (e.g. electrical rough-in
    during Structure, or Roofing on a lower floor while Structure
    continues above) do overlap somewhat, which the note below flags.
    """
    floors = max(int(floors or 1), 1)

    area_scale = max(float(plot_area_sqft or BASE_AREA_SQFT), 1.0) / BASE_AREA_SQFT
    floor_factor = 1 + max(floors - 1, 0) * EXTRA_FLOOR_MULTIPLIER

    # Square-root scaling on area: doubling area doesn't double timeline,
    # since crew size/parallel work scales with area too — it's a rough
    # heuristic that keeps big/small plots realistic relative to each other.
    raw_days = {
        "Foundation": BASE_PHASE_DAYS["Foundation"] * (area_scale ** 0.5),
        "Structure": BASE_PHASE_DAYS["Structure"] * (area_scale ** 0.5) * floor_factor,
        "Roofing": BASE_PHASE_DAYS["Roofing"] * (area_scale ** 0.35) * (1 + max(floors - 1, 0) * 0.15),
        "Finishing": BASE_PHASE_DAYS["Finishing"] * (area_scale ** 0.5) * floor_factor,
    }

    phases = []
    cursor = 0
    for phase_name in ("Foundation", "Structure", "Roofing", "Finishing"):
        duration = max(MIN_PHASE_DAYS, round(raw_days[phase_name]))
        start = cursor + 1
        end = cursor + duration
        phases.append({
            "phase": phase_name,
            "description": PHASE_DESCRIPTIONS[phase_name],
            "duration_days": duration,
            "start_day": start,
            "end_day": end,
        })
        cursor = end

    total_days = cursor
    for p in phases:
        p["percent_of_total"] = round(p["duration_days"] / total_days * 100, 1) if total_days else 0

    total_weeks = round(total_days / 7, 1)
    total_months = round(total_days / 30, 1)

    return {
        "phases": phases,
        "total_days": total_days,
        "total_weeks": total_weeks,
        "total_months": total_months,
        "estimated_completion_note": (
            f"At a typical single-crew pace, this build is estimated at about "
            f"{total_days} days (~{total_weeks} weeks / ~{total_months} months) "
            f"end-to-end, assuming phases run one after another. Actual duration "
            f"varies with labor availability, weather, material lead times, and "
            f"approvals — treat this as a planning estimate, not a contractual schedule."
        ),
    }
