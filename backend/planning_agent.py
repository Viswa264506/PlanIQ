import re
import json

import llm_client

ROOM_SCHEMA_EXAMPLE = {
    "rooms": [
        {
            "name": "Living Room",
            "priority": 1,
            "adjacent": ["Kitchen", "Staircase"],
            "preferred_direction": "Center",
        }
    ]
}

# Default area share (fraction of built-up plot area) used when the
# Layout Agent has to size a room that wasn't given an explicit size.
DEFAULT_ROOM_WEIGHTS = {
    "Living Room": 0.20,
    "Kitchen": 0.12,
    "Master Bedroom": 0.16,
    "Bedroom": 0.13,
    "Bathroom": 0.05,
    "Attached Bathroom": 0.05,
    "Common Bathroom": 0.05,
    "Pooja Room": 0.04,
    "Parking": 0.10,
    "Dining": 0.10,
    "Family Hall": 0.14,
    "Open Terrace": 0.10,
    "Staircase": 0.06,  # handled specially, but kept for reference
    "Parents Bedroom": 0.15,
    "Parents Room": 0.15,
    "Guest Room": 0.12,
    "Prayer Room": 0.04,
    "Office Room": 0.10,
    "Study Corner": 0.06,
    "Study Area": 0.08,
    "Balcony": 0.05,
    "Terrace": 0.08,
    "Small Kitchen": 0.09,
    "Open Kitchen": 0.13,
}

DIRECTION_WORDS = ["north-east", "north-west", "south-east", "south-west",
                   "north", "south", "east", "west", "center"]

ROOM_KEYWORDS = {
    "kitchen": "Kitchen",
    "living room": "Living Room",
    "hall": "Living Room",
    "pooja room": "Pooja Room",
    "pooja": "Pooja Room",
    "parking": "Parking",
    "dining": "Dining",
    "terrace": "Open Terrace",
    "family hall": "Family Hall",
    "staircase": "Staircase",
    "bathroom": "Bathroom",
    "toilet": "Bathroom",
}


def _extract_area_sqft(text: str) -> int:
    m = re.search(r"(\d{2,5})\s*(sq\s*ft|sqft|sq\.ft|square\s*feet)", text, re.I)
    if m:
        return int(m.group(1))
    return 1000  # sensible default plot size


def _extract_bedroom_count(text: str) -> int:
    m = re.search(r"(\d+)\s*(bhk|bedroom)", text, re.I)
    if m:
        return int(m.group(1))
    if "bhk" in text.lower():
        return 2
    return 2 if "bedroom" in text.lower() else 1


def _extract_floor_count(text: str) -> int:
    t = text.lower()
    if "ground + first" in t or "g+1" in t or "two floor" in t or "2 floor" in t or "first floor" in t:
        return 2
    return 1


def _extract_direction(text: str) -> str:
    t = text.lower()
    for d in DIRECTION_WORDS:
        if f"{d} facing" in t or f"{d}-facing" in t:
            return d.title()
    return "East"  # default


def _extract_extra_rooms(text: str):
    t = text.lower()
    found = []
    for keyword, canonical in ROOM_KEYWORDS.items():
        if keyword in t and canonical not in found:
            found.append(canonical)
    return found


PLANNING_SYSTEM_PROMPT = """You are an expert residential architect's planning assistant.
Given a homeowner's natural-language house requirements, extract a structured
architectural planning JSON with EXACTLY this shape and nothing else:

{
  "plot_area_sqft": <int>,
  "floors": <1 or 2>,
  "facing": "<North|South|East|West|North-East|North-West|South-East|South-West>",
  "bedrooms_requested": <int>,
  "rooms": [
    {
      "name": "<room name, e.g. Living Room, Kitchen, Master Bedroom, Bedroom 1, Bathroom, Pooja Room, Parking, Dining, Family Hall, Open Terrace, Staircase>",
      "priority": <int, 1 = highest priority>,
      "adjacent": ["<names of rooms this should be next to>"],
      "preferred_direction": "<Center|North|South|East|West|North-East|North-West|South-East|South-West|Left|Right>",
      "floor": <1 or 2>
    }
  ]
}

Rules:
- If floors=2, include exactly one "Staircase" room (floor 1, attached to Living Room, preferred_direction Left or Right).
- Distribute bedrooms/bathrooms sensibly across floors when floors=2 (e.g. Master Bedroom + Attached Bathroom on floor 1, remaining bedrooms + a shared Bathroom on floor 2).
- Include every room the user explicitly mentioned (kitchen, pooja room, parking, dining, terrace, family hall, etc).
- Always include Living Room and Kitchen even if not explicitly mentioned.
- Respond with ONLY the JSON object, no explanation, no markdown fences.
"""


def _parse_with_llm(requirements_text: str) -> dict:
    user_prompt = f"Homeowner's requirement:\n\"{requirements_text}\"\n\nReturn the planning JSON now."
    plan = llm_client.call_llm_json(PLANNING_SYSTEM_PROMPT, user_prompt)

    if not isinstance(plan, dict) or "rooms" not in plan or not isinstance(plan["rooms"], list):
        raise ValueError("LLM returned an unexpected plan shape.")
    if not plan["rooms"]:
        raise ValueError("LLM returned an empty room list.")

    plan.setdefault("plot_area_sqft", _extract_area_sqft(requirements_text))
    plan.setdefault("floors", _extract_floor_count(requirements_text))
    plan.setdefault("facing", _extract_direction(requirements_text))
    plan.setdefault("bedrooms_requested", _extract_bedroom_count(requirements_text))
    for room in plan["rooms"]:
        room.setdefault("floor", 1)
        room.setdefault("adjacent", [])
        room.setdefault("preferred_direction", "Center")
    return plan


def parse(requirements_text: str) -> dict:
    """
    Parses a natural-language requirement string into a structured
    architectural planning JSON, matching ROOM_SCHEMA_EXAMPLE's shape.

    Uses the Groq LLM when GROQ_API_KEY is configured; otherwise (or if
    the LLM call fails for any reason) falls back to the deterministic
    rule-based parser below, so the pipeline always completes.
    """
    if llm_client.is_configured():
        try:
            return _parse_with_llm(requirements_text)
        except Exception as e:
            print(f"[planning_agent] LLM parse failed, falling back to rule-based parser: {e}")

    return _parse_rule_based(requirements_text)


def _parse_rule_based(requirements_text: str) -> dict:
    """
    Deterministic fallback: parses a natural-language requirement string
    into a structured architectural planning JSON, matching
    ROOM_SCHEMA_EXAMPLE's shape.
    """
    text = requirements_text.strip()
    plot_area = _extract_area_sqft(text)
    bedrooms = _extract_bedroom_count(text)
    floors = _extract_floor_count(text)
    facing = _extract_direction(text)
    extra_rooms = _extract_extra_rooms(text)

    rooms = []
    priority = 1

    # Core rooms always present
    rooms.append({"name": "Living Room", "priority": priority,
                   "adjacent": ["Kitchen", "Staircase"],
                   "preferred_direction": "Center", "floor": 1})
    priority += 1

    # Public-zone rooms (must sit close to the Living Room / entrance, per
    # the zoning hierarchy Public -> Semi-Private -> Private -> Service)
    # are placed right after the Living Room, before Kitchen/bedrooms, so
    # the recursive split keeps them adjacent to it rather than pushed to
    # a far corner.
    public_zone_rooms = [r for r in extra_rooms if r in ("Parking", "Pooja Room")]
    for room_name in public_zone_rooms:
        rooms.append({"name": room_name, "priority": priority,
                       "adjacent": ["Living Room"],
                       "preferred_direction": "Center", "floor": 1})
        priority += 1

    rooms.append({"name": "Kitchen", "priority": priority,
                   "adjacent": ["Living Room", "Dining"],
                   "preferred_direction": "North-East" if facing != "North-East" else "North", "floor": 1})
    priority += 1

    # Semi-private room (Dining) follows the Kitchen, matching the
    # "Kitchen should always be close to Dining" rule.
    if "Dining" in extra_rooms:
        rooms.append({"name": "Dining", "priority": priority,
                       "adjacent": ["Kitchen", "Living Room"],
                       "preferred_direction": "Center", "floor": 1})
        priority += 1

    # Bedrooms distributed: first bedroom -> ground floor as Master Bedroom
    # (if multi-floor), remaining bedrooms on the top floor.
    if floors == 2:
        rooms.append({"name": "Master Bedroom", "priority": priority,
                       "adjacent": ["Attached Bathroom"],
                       "preferred_direction": "South-West", "floor": 1})
        priority += 1
        rooms.append({"name": "Attached Bathroom", "priority": priority,
                       "adjacent": ["Master Bedroom"],
                       "preferred_direction": "South", "floor": 1})
        priority += 1
        remaining_bedrooms = max(bedrooms - 1, 0)
        for i in range(remaining_bedrooms):
            rooms.append({"name": f"Bedroom {i + 1}", "priority": priority,
                           "adjacent": ["Bathroom"],
                           "preferred_direction": "West", "floor": 2})
            priority += 1
        rooms.append({"name": "Bathroom", "priority": priority,
                       "adjacent": [], "preferred_direction": "North", "floor": 2})
        priority += 1
    else:
        for i in range(bedrooms):
            name = "Master Bedroom" if i == 0 else f"Bedroom {i + 1}"
            rooms.append({"name": name, "priority": priority,
                           "adjacent": ["Bathroom"],
                           "preferred_direction": "South-West", "floor": 1})
            priority += 1
        rooms.append({"name": "Bathroom", "priority": priority,
                       "adjacent": [], "preferred_direction": "South", "floor": 1})
        priority += 1

    # Remaining extra rooms mentioned explicitly by the user (avoid duplicates).
    # Public-zone rooms and Dining were already placed above in their proper
    # zone; only rooms like Family Hall / Open Terrace land here.
    existing_names = {r["name"] for r in rooms}
    for room_name in extra_rooms:
        if room_name in existing_names or room_name == "Bathroom":
            continue
        floor = 1
        if room_name == "Open Terrace" or room_name == "Family Hall":
            floor = 2 if floors == 2 else 1
        rooms.append({"name": room_name, "priority": priority,
                       "adjacent": ["Living Room"],
                       "preferred_direction": "Center", "floor": floor})
        priority += 1
        existing_names.add(room_name)

    # Staircase is only added if the house has more than 1 floor
    if floors == 2:
        rooms.append({"name": "Staircase", "priority": priority,
                       "adjacent": ["Living Room"],
                       "preferred_direction": "Right", "floor": 1})
        priority += 1

    plan = {
        "plot_area_sqft": plot_area,
        "floors": floors,
        "facing": facing,
        "bedrooms_requested": bedrooms,
        "rooms": rooms,
    }
    return plan


# ======================================================================
# Merged in from lifestyle_agent.py (wizard-based planning)
# ======================================================================

"""
Agent — Lifestyle Planning
---------------------------
Feature 2 backend: turns the step-by-step wizard's answers (lifestyle,
floor count, land size, facing, bedrooms/bathrooms, kitchen type,
parking/pooja/balcony, special requirements) into the same structured
plan shape planning_agent.parse() produces — {plot_area_sqft, floors,
facing, bedrooms_requested, rooms:[...]} — so it drops straight into the
existing pipeline (layout_agent.generate_layout, validator, blueprint_agent,
budget_agent, timeline_agent, analysis_agent) completely unchanged.

Room distribution is done in phases (Universal Rules -> Lifestyle Rules ->
Remaining Bedrooms -> Remaining Bathrooms -> Amenities -> Balcony ->
Terrace -> Staircase), mirroring how an architect actually thinks about a
floor plan before handing it to the (unchanged) recursive-partitioning
layout generator. Every phase only appends to a shared room list; none of
them touch layout_agent, validator, blueprint_agent, budget_agent, or
timeline_agent.
"""

# Sensible per-lifestyle defaults. The wizard pre-fills these but every
# value stays editable by the user — this module never overrides an
# explicit answer, only fills in ones that were left blank.
LIFESTYLE_DEFAULTS = {
    "bachelor": {
        "bedrooms": 1, "bathrooms": 1, "kitchen_type": "Small Kitchen",
        "parking": True, "pooja_room": False, "balcony": False, "study": True,
    },
    "couple": {
        "bedrooms": 1, "bathrooms": 1, "kitchen_type": "Open Kitchen",
        "parking": False, "pooja_room": False, "balcony": True, "study": False,
    },
    "couple_with_kids": {
        "bedrooms": 2, "bathrooms": 2, "kitchen_type": "Kitchen",
        "parking": True, "pooja_room": True, "balcony": True, "study": True,
    },
    "family_with_adults": {
        "bedrooms": 3, "bathrooms": 3, "kitchen_type": "Kitchen",
        "parking": True, "pooja_room": True, "balcony": True, "study": False,
    },
    "joint_family": {
        "bedrooms": 4, "bathrooms": 4, "kitchen_type": "Kitchen",
        "parking": True, "pooja_room": True, "balcony": True, "study": False,
    },
    "senior_citizens": {
        "bedrooms": 2, "bathrooms": 2, "kitchen_type": "Kitchen",
        "parking": True, "pooja_room": True, "balcony": False, "study": False,
    },
    "wfh": {
        "bedrooms": 2, "bathrooms": 2, "kitchen_type": "Kitchen",
        "parking": True, "pooja_room": False, "balcony": True, "study": False,
    },
    "other": {
        "bedrooms": 2, "bathrooms": 2, "kitchen_type": "Kitchen",
        "parking": True, "pooja_room": False, "balcony": False, "study": False,
    },
}

LIFESTYLE_LABELS = {
    "bachelor": "Bachelor",
    "couple": "Couple",
    "couple_with_kids": "Couple with Kids",
    "family_with_adults": "Family with Adults",
    "joint_family": "Joint Family",
    "senior_citizens": "Senior Citizens",
    "wfh": "Work From Home",
    "other": "Other",
}

# Phase 1 / 2 — the label to use for the mandatory ground-floor bedroom in
# a multi-floor house (e.g. "Parents Bedroom" for a household where the
# older generation stays on the ground floor). Lifestyles not listed here
# just get a plain "Bedroom".
GROUND_BEDROOM_NAME = {
    "senior_citizens": "Parents Bedroom",
    "couple_with_kids": "Parents Bedroom",
    "family_with_adults": "Parents Bedroom",
    "joint_family": "Parents Room",
}

# Phase 5 — optional lifestyle-flavor rooms, beyond the core Living/
# Kitchen/Dining/Bedrooms/Bathrooms/Parking/Pooja/Balcony/Terrace (which
# all have their own dedicated phases/toggles). Ordered by priority — the
# first entries appear even in a 1-floor house; as floor count goes up,
# more of the list gets used, spread across the upper floors. One small
# list per lifestyle instead of a separate room table per floor-count.
LIFESTYLE_AMENITIES = {
    "bachelor": ["Study Corner", "Gaming Room", "Gym", "Laundry"],
    "couple": ["Walk-in Closet"],
    "couple_with_kids": ["Study Area", "Play Room", "Laundry"],
    "family_with_adults": ["Guest Room", "Family Lounge", "Study"],
    "joint_family": ["Guest Room", "Family Hall", "Gym", "Laundry"],
    "senior_citizens": ["Guest Room"],
    "wfh": ["Meeting Room", "Studio"],
    "other": [],
}

# Phase 7 — which lifestyles get a Terrace at all (a 1-floor house has no
# separate roof to speak of, so Terrace only applies once there's a
# top floor above the living space).
LIFESTYLE_WITH_TERRACE = {"bachelor", "couple_with_kids", "family_with_adults", "joint_family", "wfh"}


def _defaults_for(lifestyle: str) -> dict:
    return LIFESTYLE_DEFAULTS.get(lifestyle, LIFESTYLE_DEFAULTS["other"])


def _is_bedroom_name(name: str) -> bool:
    return "Bedroom" in name or name == "Parents Room"


def _is_bathroom_name(name: str) -> bool:
    return name == "Bathroom" or name.startswith("Bathroom ")


class _PlanCtx:
    """Shared mutable state threaded through the room-distribution phases.
    Keeps the phase functions simple (each just appends rooms / decrements
    a remaining-count), while `rooms`/`priority` stay in one place."""

    def __init__(self, lifestyle: str, floors: int, bedrooms: int, bathrooms: int):
        self.lifestyle = lifestyle
        self.ground = 1
        self.top = max(floors, 1)
        self.upper_floors = list(range(2, self.top + 1)) if self.top > 1 else [self.ground]
        self.rooms = []
        self._priority = 1
        self.remaining_bedrooms = bedrooms
        self.remaining_bathrooms = bathrooms

    def add(self, name, floor, adjacent=None, direction="Center"):
        room = {
            "name": name, "priority": self._priority,
            "adjacent": adjacent or [], "preferred_direction": direction, "floor": floor,
        }
        self.rooms.append(room)
        self._priority += 1
        return room

    def bedroom_floors(self):
        return sorted({r["floor"] for r in self.rooms if _is_bedroom_name(r["name"])})

    def has_bathroom_on(self, floor):
        return any(r["floor"] == floor and _is_bathroom_name(r["name"]) for r in self.rooms)


# ---------------------------------------------------------------- Phase 1

def _apply_universal_rules(ctx: _PlanCtx, kitchen_type: str, parking: bool,
                            pooja_room: bool, dining: bool):
    """Rules that hold for every lifestyle. In a multi-floor house, the
    ground floor MUST carry Living + Kitchen + Dining (if requested) +
    Parking (if requested) + Pooja (if requested) + at least one bedroom
    with its own bathroom — never leave the ground floor as just a public
    lobby with every bedroom upstairs."""
    ctx.add("Living Room", ctx.ground, ["Kitchen"], "Center")
    ctx.add(kitchen_type or "Kitchen", ctx.ground, ["Living Room", "Dining"], "South-East")
    if dining:
        ctx.add("Dining", ctx.ground, ["Kitchen", "Living Room"], "Center")
    if parking:
        ctx.add("Parking", ctx.ground, ["Living Room"], "Front")
    if pooja_room:
        ctx.add("Pooja Room", ctx.ground, ["Living Room"], "North-East")

    # Ground floor must have >= 1 bedroom (+ its own bathroom) once the
    # house has more than one floor.
    if ctx.top > 1 and ctx.remaining_bedrooms > 0:
        name = GROUND_BEDROOM_NAME.get(ctx.lifestyle, "Bedroom")
        ctx.add(name, ctx.ground, ["Bathroom"], "South-West")
        ctx.remaining_bedrooms -= 1
        ctx.add("Bathroom", ctx.ground, [name], "South")
        ctx.remaining_bathrooms = max(0, ctx.remaining_bathrooms - 1)


# ---------------------------------------------------------------- Phase 2

def _apply_lifestyle_rules(ctx: _PlanCtx, pooja_room: bool):
    """Lifestyle-only structural rules that go beyond the universal ones
    and beyond plain optional amenities. Currently: a Joint Family keeps a
    second, dedicated Prayer Room upstairs (private/quiet) in addition to
    the shared ground-floor Pooja Room from Phase 1."""
    if ctx.lifestyle == "joint_family" and pooja_room and ctx.top > 1:
        ctx.add("Prayer Room", ctx.top, ["Living Room"], "North-East")


# ---------------------------------------------------------------- Phase 3

def _allocate_remaining_bedrooms(ctx: _PlanCtx):
    """Master Bedroom preferred on upper floors; remaining bedrooms are
    spread evenly across whichever upper floors exist (or the ground
    floor, for a 1-floor house)."""
    master_used_floors = {f for f in ctx.upper_floors
                           if any(r["name"] == "Master Bedroom" and r["floor"] == f for r in ctx.rooms)}
    bedroom_i = 0
    for _ in range(ctx.remaining_bedrooms):
        f = ctx.upper_floors[bedroom_i % len(ctx.upper_floors)]
        if f not in master_used_floors:
            name = "Master Bedroom"
            master_used_floors.add(f)
        else:
            name = f"Bedroom {bedroom_i + 1}"
        ctx.add(name, f, ["Bathroom"], "South-West")
        bedroom_i += 1
    ctx.remaining_bedrooms = 0


# ---------------------------------------------------------------- Phase 4

def _allocate_remaining_bathrooms(ctx: _PlanCtx):
    """First guarantee every floor that has a bedroom also has a bathroom
    (never a Bedroom without a Bathroom on the same floor) — only after
    that is satisfied does any bathroom surplus get placed elsewhere."""
    for f in ctx.bedroom_floors():
        if ctx.remaining_bathrooms > 0 and not ctx.has_bathroom_on(f):
            ctx.add("Bathroom", f, [], "North")
            ctx.remaining_bathrooms -= 1

    bathroom_i = 0
    for _ in range(ctx.remaining_bathrooms):
        f = ctx.upper_floors[bathroom_i % len(ctx.upper_floors)]
        name = "Bathroom" if not ctx.has_bathroom_on(f) else f"Bathroom {bathroom_i + 2}"
        ctx.add(name, f, [], "North")
        bathroom_i += 1
    ctx.remaining_bathrooms = 0


# ---------------------------------------------------------------- Phase 5

def _allocate_amenities(ctx: _PlanCtx):
    """Optional lifestyle-flavor rooms — allocated last among the 'real'
    rooms, after bedrooms and bathrooms are already settled, so they can
    never crowd out an essential room. Budget scales with floor count: a
    1-floor house only gets the first (highest-priority) amenity; each
    additional floor unlocks more of the list (2 per upper floor)."""
    extra_floor = ctx.top if ctx.top > 1 else ctx.ground
    amenity_budget = 1 if ctx.top == 1 else 2 * len(ctx.upper_floors)
    amenities = LIFESTYLE_AMENITIES.get(ctx.lifestyle, [])[:amenity_budget]
    for i, name in enumerate(amenities):
        ctx.add(name, ctx.upper_floors[i % len(ctx.upper_floors)])

    # WFH's workspace is the defining room of the lifestyle, not an
    # optional extra — always included, on top of the amenity budget.
    if ctx.lifestyle == "wfh":
        ctx.add("Office Room", extra_floor, [], "North")


# ---------------------------------------------------------------- Phase 6

def _allocate_balcony(ctx: _PlanCtx, balcony: bool):
    """Prefer an upper floor; ground floor only when the house has just
    the one floor to work with."""
    if not balcony:
        return
    floor = ctx.top if ctx.top > 1 else ctx.ground
    ctx.add("Balcony", floor, [], "Center")


# ---------------------------------------------------------------- Phase 7

def _allocate_terrace(ctx: _PlanCtx):
    """Always the highest floor only — never mixed in with the amenity
    round-robin, which could otherwise land it on a middle floor."""
    if ctx.top > 1 and ctx.lifestyle in LIFESTYLE_WITH_TERRACE:
        ctx.add("Terrace", ctx.top, [], "Center")


# ---------------------------------------------------------------- Phase 8

def _allocate_staircase(ctx: _PlanCtx):
    """Always starts from the ground floor; only exists once the house
    has more than one floor."""
    if ctx.top > 1:
        ctx.add("Staircase", ctx.ground, ["Living Room"], "Right")


def _distribute_rooms(lifestyle: str, floors: int, bedrooms: int, bathrooms: int,
                       kitchen_type: str, parking: bool, pooja_room: bool,
                       balcony: bool, dining: bool) -> list:
    """
    Orchestrates the 8 planning phases (see module docstring) and returns
    the final room list — same shape as before: a list of dicts with
    name/priority/adjacent/preferred_direction/floor, ready for
    layout_agent.generate_layout() exactly as it already expects.
    """
    ctx = _PlanCtx(lifestyle, floors, bedrooms, bathrooms)

    _apply_universal_rules(ctx, kitchen_type, parking, pooja_room, dining)
    _apply_lifestyle_rules(ctx, pooja_room)
    _allocate_remaining_bedrooms(ctx)
    _allocate_remaining_bathrooms(ctx)
    _allocate_amenities(ctx)
    _allocate_balcony(ctx, balcony)
    _allocate_terrace(ctx)
    _allocate_staircase(ctx)

    return ctx.rooms


def build_plan(payload: dict) -> dict:
    """
    Builds a full plan dict (same shape as planning_agent.parse()) from
    the wizard's structured answers. `payload` keys: lifestyle, floors,
    plot_area_sqft, facing, bedrooms, bathrooms, kitchen_type, parking,
    pooja_room, balcony, dining, special_requirements.
    """
    lifestyle = payload.get("lifestyle") or "other"
    if lifestyle not in LIFESTYLE_DEFAULTS:
        lifestyle = "other"
    defaults = _defaults_for(lifestyle)

    floors = int(payload.get("floors") or 1)
    floors = max(1, min(floors, 4))

    plot_area_sqft = int(payload.get("plot_area_sqft") or 1000)
    facing = payload.get("facing") or "East"

    bedrooms = payload.get("bedrooms")
    bedrooms = int(bedrooms) if bedrooms not in (None, "") else defaults["bedrooms"]

    bathrooms = payload.get("bathrooms")
    bathrooms = int(bathrooms) if bathrooms not in (None, "") else defaults["bathrooms"]

    kitchen_type = payload.get("kitchen_type") or defaults["kitchen_type"]
    parking = payload.get("parking")
    parking = defaults["parking"] if parking is None else bool(parking)
    pooja_room = payload.get("pooja_room")
    pooja_room = defaults["pooja_room"] if pooja_room is None else bool(pooja_room)
    balcony = payload.get("balcony")
    balcony = defaults["balcony"] if balcony is None else bool(balcony)
    dining = payload.get("dining", True)

    rooms = _distribute_rooms(lifestyle, floors, bedrooms, bathrooms, kitchen_type,
                               parking, pooja_room, balcony, dining)

    plan = {
        "plot_area_sqft": plot_area_sqft,
        "floors": floors,
        "facing": facing,
        "bedrooms_requested": bedrooms,
        "lifestyle": lifestyle,
        "lifestyle_label": LIFESTYLE_LABELS.get(lifestyle, "Other"),
        "special_requirements": (payload.get("special_requirements") or "").strip(),
        "rooms": rooms,
    }
    return plan