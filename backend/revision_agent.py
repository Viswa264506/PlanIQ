"""
Agent — Smart NLP Revision (Tanglish + English)
-------------------------------------------------
Feature 3: understands mixed Tamil-English ("Tanglish") revision requests
like "Kitchen konjam bigger venum" or "Bedroom 2-ku attached bathroom add
pannunga", extracts {action, target room(s), direction}, and applies only
the minimum geometry change needed — it never regenerates floors that
weren't mentioned.

Design: action verbs in these instructions are consistently written in
English even inside a Tanglish sentence (bigger, add, remove, merge...) —
only the helper/filler words are Tamil (pannunga, venum, ku, la, oda...).
So intent detection is plain keyword/regex spotting on the English verbs,
and room detection matches directly against the *actual* room names
already in the generated layout (robust to whatever surrounds them,
Tamil or English).

Supported operations: Add, Remove, Move, Resize (Increase/Decrease),
Merge, Split, Replace, Rotate, Improve ventilation, Improve lighting,
Swap (kept for backward compatibility with the original revise feature).
"""

import copy
import re

import layout_agent
import validator

MIN_ROOM_DIM = layout_agent.MIN_ROOM_DIM

# Generic (non-exact) room-type keywords, used only when no exact room
# name from the current layout appears in the instruction text.
GENERIC_ROOM_KEYWORDS = {
    "kitchen": "Kitchen",
    "hall": "Living Room",
    "living": "Living Room",
    "parking": "Parking",
    "pooja": "Pooja Room",
    "prayer": "Prayer Room",
    "dining": "Dining",
    "bathroom": "Bathroom",
    "toilet": "Bathroom",
    "bedroom": "Bedroom",
    "terrace": "Open Terrace",
    "balcony": "Balcony",
    "staircase": "Staircase",
    "guest": "Guest Room",
    "study": "Study",
    "office": "Office Room",
}

NEW_ROOM_KEYWORDS = {
    "attached bathroom": "Attached Bathroom",
    "balcony": "Balcony",
    "guest room": "Guest Room",
    "study room": "Study Area",
    "study area": "Study Area",
    "office": "Office Room",
    "terrace": "Open Terrace",
    "pooja room": "Pooja Room",
    "dining": "Dining",
    "store room": "Store Room",
    "storeroom": "Store Room",
}

ACTION_PATTERNS = [
    (r"\battached\s+bathroom\b.*\badd\b|\badd\b.*\battached\s+bathroom\b", "add_named"),
    (r"\badd\b|\bkattunga\b|\bvenum\b.*\badd\b", "add_named"),
    (r"\bremove\b|\bdelete\b|\bvendam\b|\btheekunga\b", "remove"),
    (r"\bmerge\b|\bcombine\b|\bjoin\b", "merge"),
    (r"\bsplit\b|\bdivide\b|\bseparate\b", "split"),
    (r"\breplace\b|\bconvert\b", "replace"),
    (r"\brotate\b|\bturn\b", "rotate"),
    (r"\bswap\b", "swap"),
    (r"\bventilation\b|\bair\s*flow\b|\bairflow\b|\bcross\s*vent", "improve_ventilation"),
    (r"\bsunlight\b|\blighting\b|\bbright(er)?\b|\blight\b", "improve_lighting"),
    (r"\bbigger\b|\blarger\b|\bincrease\b|\bexpand\b|\bperiya\b", "increase"),
    (r"\bsmaller\b|\bdecrease\b|\breduce\b|\bshrink\b|\bchinna\b", "decrease"),
    (r"\bmove\b|\bshift\b|\brelocate\b", "move"),
]

DIRECTION_COMBOS = ["north-east", "north east", "south-east", "south east",
                     "north-west", "north west", "south-west", "south west"]


def _detect_action(lower: str) -> str:
    for pattern, name in ACTION_PATTERNS:
        if re.search(pattern, lower):
            return name
    return "unknown"


def _detect_direction(lower: str):
    normalized = lower.replace("-", " ")
    for combo in DIRECTION_COMBOS:
        if combo.replace("-", " ") in normalized:
            return combo.replace(" ", "-").title()
    for d in ["north", "south", "east", "west"]:
        if re.search(rf"\b{d}\b", lower):
            return d.title()
    return None


def _detect_target_floor(lower: str):
    """Picks up phrasing like 'to floor 1' / 'floor 2' so a move
    instruction can target a specific floor rather than another room."""
    m = re.search(r"floor\s*(\d+)", lower)
    return int(m.group(1)) if m else None


def _detect_new_room_name(lower: str):
    for kw, canon in NEW_ROOM_KEYWORDS.items():
        if kw in lower:
            return canon
    return None


def _detect_rooms(lower: str, layout: dict) -> list:
    exact = []
    for rooms in layout["floors"].values():
        for r in rooms:
            n = r["name"]
            if n.lower() in lower and n not in exact:
                exact.append(n)
    if exact:
        exact.sort(key=lambda n: lower.find(n.lower()))
        return exact

    found = []
    for kw, canon in GENERIC_ROOM_KEYWORDS.items():
        if re.search(rf"\b{kw}\b", lower):
            for rooms in layout["floors"].values():
                for r in rooms:
                    if canon.lower() in r["name"].lower() and r["name"] not in found:
                        found.append(r["name"])
    return found


def parse_instruction(instruction: str, layout: dict) -> dict:
    lower = instruction.strip().lower()
    action = _detect_action(lower)

    # Only "add" and "replace" need a destination room *type* (e.g. the
    # "Balcony" in "add a balcony", or the "office" in "convert kitchen to
    # office"). Every other action — remove, merge, split, resize, move,
    # etc. — was running this same detection unconditionally, which
    # silently stripped an EXISTING room's own name out of the sentence
    # whenever it happened to match a NEW_ROOM_KEYWORDS phrase (Pooja
    # Room, Balcony, Dining, Guest Room, Attached Bathroom, Study Room/
    # Area, Office, Terrace, Store Room). That meant "remove the pooja
    # room" or "delete balcony" left nothing for room-matching to find.
    new_room_name = _detect_new_room_name(lower) if action in ("add_named", "replace") else None
    room_scan_text = lower
    if new_room_name:
        # Strip the new-room keyword phrase before matching anchor rooms,
        # so e.g. "attached bathroom" (the room being added) doesn't get
        # mistaken for an existing room simply named "Bathroom".
        for kw in NEW_ROOM_KEYWORDS:
            if kw in lower:
                room_scan_text = lower.replace(kw, " ")
                break
    return {
        "action": action,
        "direction": _detect_direction(lower),
        "rooms": _detect_rooms(room_scan_text, layout),
        "new_room_name": new_room_name,
        "target_floor": _detect_target_floor(lower),
        "raw": instruction.strip(),
    }


# ---------------------------------------------------------------- helpers

def _floor_of(layout: dict, name: str):
    # Prefer an exact name match across every floor first — otherwise a
    # query for e.g. "Bathroom" can fuzzy-match "Attached Bathroom" on an
    # earlier floor before ever reaching the actual "Bathroom" room.
    for floor_num, rooms in layout["floors"].items():
        for r in rooms:
            if r["name"].lower() == name.lower():
                return floor_num
    for floor_num, rooms in layout["floors"].items():
        if layout_agent._find_room(rooms, name):
            return floor_num
    return None


def _touches_exterior(room: dict, plot_w: float, plot_h: float, eps: float = 0.75) -> bool:
    return (room["x"] <= eps or room["y"] <= eps
            or room["x"] + room["width"] >= plot_w - eps
            or room["y"] + room["height"] >= plot_h - eps)


def _sync_plan_from_layout(plan: dict, layout: dict, floor_num: int):
    """After a structural change (add/remove/merge/split) the room *set*
    on `floor_num` may no longer match plan['rooms'] — rebuild just that
    floor's entries from the layout's current room list so downstream
    agents (analysis, PDF, revise-again) stay consistent."""
    plan["rooms"] = [r for r in plan["rooms"] if r.get("floor") != floor_num]
    for room in layout["floors"][floor_num]:
        plan["rooms"].append({
            "name": room["name"], "priority": len(plan["rooms"]) + 1,
            "adjacent": [], "preferred_direction": "Center", "floor": floor_num,
        })


def _retile_floor(plan: dict, layout: dict, floor_num: int) -> dict:
    """Regenerates ONLY `floor_num` (using the layout's original seed),
    leaving every other floor's geometry untouched."""
    fresh = layout_agent.generate_layout(plan, seed=layout.get("seed", 0))
    layout["floors"][floor_num] = fresh["floors"].get(floor_num, [])
    return layout


def _remove_room(layout: dict, floor_num: int, name: str) -> bool:
    """Absorbs the room's footprint into a cleanly-adjacent neighbor
    (same technique layout_agent._resize_room uses), so the tiling stays
    gap-free without retiling the whole floor. Returns False if no clean
    single neighbor exists (caller should fall back to a full retile)."""
    rooms = layout["floors"][floor_num]
    non_stair = [r for r in rooms if r["name"] != "Staircase"]
    room = layout_agent._find_room(non_stair, name)
    if not room:
        return False
    candidates = [(layout_agent._clean_shared_edge(room, other), other)
                  for other in non_stair if other is not room]
    candidates = [(e, o) for e, o in candidates if e]
    if not candidates:
        return False
    edge, neighbor = candidates[0]
    if edge == "vertical":
        neighbor["x"] = min(room["x"], neighbor["x"])
        neighbor["width"] = round(room["width"] + neighbor["width"], 2)
    else:
        neighbor["y"] = min(room["y"], neighbor["y"])
        neighbor["height"] = round(room["height"] + neighbor["height"], 2)
    neighbor["area"] = round(neighbor["width"] * neighbor["height"], 2)
    rooms.remove(room)
    return True


def _merge_rooms(layout: dict, floor_num: int, a_name: str, b_name: str):
    rooms = layout["floors"][floor_num]
    non_stair = [r for r in rooms if r["name"] != "Staircase"]
    a = layout_agent._find_room(non_stair, a_name)
    b = layout_agent._find_room(non_stair, b_name)
    if not a or not b or a is b:
        return False, None
    edge = layout_agent._clean_shared_edge(a, b)
    if not edge:
        return False, None
    merged_name = f"{a['name']} + {b['name']}"
    if edge == "vertical":
        a["x"] = min(a["x"], b["x"])
        a["width"] = round(a["width"] + b["width"], 2)
    else:
        a["y"] = min(a["y"], b["y"])
        a["height"] = round(a["height"] + b["height"], 2)
    a["area"] = round(a["width"] * a["height"], 2)
    a["name"] = merged_name
    rooms.remove(b)
    return True, merged_name


def _split_room(layout: dict, floor_num: int, name: str):
    rooms = layout["floors"][floor_num]
    room = layout_agent._find_room([r for r in rooms if r["name"] != "Staircase"], name)
    if not room:
        return False, None
    if room["width"] >= room["height"] and room["width"] >= 2 * MIN_ROOM_DIM:
        half = round(room["width"] / 2, 2)
        b = dict(room)
        room["width"] = half
        b["x"] = round(room["x"] + half, 2)
        b["width"] = round(b["width"] - half, 2)
    elif room["height"] >= 2 * MIN_ROOM_DIM:
        half = round(room["height"] / 2, 2)
        b = dict(room)
        room["height"] = half
        b["y"] = round(room["y"] + half, 2)
        b["height"] = round(b["height"] - half, 2)
    else:
        return False, None
    room["area"] = round(room["width"] * room["height"], 2)
    b["area"] = round(b["width"] * b["height"], 2)
    b["name"] = f"{name} 2"
    rooms.append(b)
    return True, b["name"]


def _swap_with_exterior_neighbor(layout: dict, floor_num: int, name: str) -> bool:
    rooms = layout["floors"][floor_num]
    non_stair = [r for r in rooms if r["name"] != "Staircase"]
    room = layout_agent._find_room(non_stair, name)
    if not room:
        return False
    plot_w, plot_h = layout["plot_width"], layout["plot_height"]
    candidates = [r for r in non_stair if r is not room and _touches_exterior(r, plot_w, plot_h)
                  and abs(r["width"] - room["width"]) < 3 and abs(r["height"] - room["height"]) < 3]
    if not candidates:
        return False
    target = min(candidates, key=lambda r: abs(r["area"] - room["area"]))
    for key in ("x", "y", "width", "height", "area"):
        room[key], target[key] = target[key], room[key]
    return True


# ---------------------------------------------------------------- main entry

def apply(plan: dict, layout: dict, instruction: str):
    """
    Returns (new_layout, new_plan, message). `plan`/`layout` are never
    mutated in place — callers get fresh objects back.
    """
    layout = copy.deepcopy(layout)
    plan = copy.deepcopy(plan)

    # People naturally type several instructions in one box, e.g. "move the
    # bathroom to floor 1, move kitchen to east". Parsing that as a SINGLE
    # instruction let room names from the second half leak into the first
    # half's action (both "Bathroom" and "Kitchen" would be detected as
    # `rooms` for one combined instruction), producing a misleading
    # success message with no matching geometry change. Splitting into
    # clauses first and applying each independently keeps every action
    # honest about which room(s) it actually touched.
    clauses = [c.strip() for c in re.split(r",|;|\band then\b|\bthen\b", instruction, flags=re.I) if c.strip()]
    if len(clauses) > 1:
        messages = []
        for clause in clauses:
            layout, plan, msg = apply(plan, layout, clause)
            messages.append(msg)
        return layout, plan, " ".join(messages)

    parsed = parse_instruction(instruction, layout)
    action, direction, rooms = parsed["action"], parsed["direction"], parsed["rooms"]
    target_floor = parsed["target_floor"]

    if action == "unknown":
        # Fall back to the original English-only regex engine (handles
        # "Swap X and Y" / "Make X bigger" / "Move X near Y" phrasing
        # this parser's keyword list might not have caught).
        fallback = layout_agent.revise_layout(layout, instruction)
        return fallback, plan, (
            "Applied using the general revision engine — for best Tanglish "
            "support, mention the action word in English (add/remove/move/"
            "bigger/smaller/merge/split) alongside the room name."
        )

    if not rooms:
        return layout, plan, (
            f"Understood the action ('{action.replace('_', ' ')}') but couldn't match a room "
            "name from the current layout in that sentence — try including the exact room "
            "name shown on the blueprint."
        )

    target = rooms[0]
    secondary = rooms[1] if len(rooms) > 1 else None
    floor_num = _floor_of(layout, target)
    if floor_num is None:
        return layout, plan, f"Couldn't locate '{target}' in the current layout."

    if action in ("increase", "decrease"):
        ok = layout_agent._resize_room(layout["floors"][floor_num], target, grow=(action == "increase"))
        msg = (f"{target} made {'bigger' if action == 'increase' else 'smaller'}." if ok else
               f"Couldn't resize {target} — no adjacent room has spare space to give up without breaking the tiling.")
        return layout, plan, msg

    if action == "move":
        if target_floor is not None:
            if target_floor not in layout["floors"]:
                return layout, plan, (
                    f"This plan only has Floor(s) {sorted(layout['floors'].keys())} — "
                    f"Floor {target_floor} doesn't exist in the current plan."
                )
            if target_floor == floor_num:
                return layout, plan, f"{target} is already on Floor {floor_num}."

            moved_entry = False
            for r in plan["rooms"]:
                if r["name"] == target and r.get("floor") == floor_num:
                    r["floor"] = target_floor
                    moved_entry = True
                    break
            if not moved_entry:
                return layout, plan, f"Couldn't locate '{target}' in the plan to move it across floors."

            # Re-tile the floor it left (closing the gap) and the floor it
            # joined (making room for it) — every other floor is untouched.
            layout = _retile_floor(plan, layout, floor_num)
            layout = _retile_floor(plan, layout, target_floor)
            _sync_plan_from_layout(plan, layout, floor_num)
            _sync_plan_from_layout(plan, layout, target_floor)
            return layout, plan, (
                f"Moved {target} from Floor {floor_num} to Floor {target_floor} and re-tiled both floors."
            )

        if secondary:
            secondary_floor = _floor_of(layout, secondary)
            if secondary_floor is None:
                return layout, plan, f"Couldn't locate '{secondary}' in the current layout."
            if secondary_floor != floor_num:
                return layout, plan, (
                    f"{target} is on Floor {floor_num} and {secondary} is on Floor {secondary_floor} — "
                    "say 'move X to floor N' to move a room across floors, or name a same-floor room to "
                    "move it next to."
                )
            layout = layout_agent._revise_move(layout, target, secondary)
            room_after = layout_agent._find_room(layout["floors"][floor_num], target)
            neighbor_after = layout_agent._find_room(layout["floors"][floor_num], secondary)
            if layout_agent._rooms_adjacent(room_after, neighbor_after):
                return layout, plan, f"Moved {target} near {secondary}."
            return layout, plan, (
                f"Couldn't find a way to move {target} next to {secondary} without disturbing other "
                "rooms in the current tiling — try Regenerate layout instead."
            )
        if direction:
            for r in plan["rooms"]:
                if r["name"] == target:
                    r["preferred_direction"] = direction
            return layout, plan, (
                f"Noted — {target}'s preferred direction is now {direction}. Repositioning it in the "
                "current layout without disturbing every other room isn't safely possible in one step; "
                "the new preference will apply next time you Regenerate the layout."
            )
        return layout, plan, f"To move {target}, say which room to move it near, which floor to move it to, or which direction (e.g. 'move Kitchen to East')."

    if action == "swap":
        if not secondary:
            return layout, plan, "Swap needs two room names."
        fb = _floor_of(layout, secondary)
        ra = layout_agent._find_room(layout["floors"][floor_num], target)
        rb = layout_agent._find_room(layout["floors"][fb], secondary) if fb is not None else None
        if not rb:
            return layout, plan, f"Couldn't locate '{secondary}' in the current layout."
        for key in ("x", "y", "width", "height", "area"):
            ra[key], rb[key] = rb[key], ra[key]
        return layout, plan, f"Swapped {target} and {secondary}."

    if action == "remove":
        removed_cleanly = _remove_room(layout, floor_num, target)
        plan["rooms"] = [r for r in plan["rooms"] if r["name"] != target]
        if not removed_cleanly:
            layout = _retile_floor(plan, layout, floor_num)
            _sync_plan_from_layout(plan, layout, floor_num)
            return layout, plan, f"Removed {target} and re-tiled floor {floor_num} to close the gap."
        return layout, plan, f"Removed {target}; its space was absorbed by the adjacent room."

    if action == "add_named":
        new_name = parsed["new_room_name"] or "New Room"
        existing = {r["name"] for fr in layout["floors"].values() for r in fr}
        if new_name in existing:
            i = 2
            while f"{new_name} {i}" in existing:
                i += 1
            new_name = f"{new_name} {i}"
        plan["rooms"].append({
            "name": new_name, "priority": len(plan["rooms"]) + 1,
            "adjacent": [target], "preferred_direction": "Center", "floor": floor_num,
        })
        layout = _retile_floor(plan, layout, floor_num)
        _sync_plan_from_layout(plan, layout, floor_num)
        return layout, plan, f"Added {new_name} near {target} and re-tiled floor {floor_num}."

    if action == "merge":
        if not secondary:
            return layout, plan, f"Found only one matching room ('{target}') — need two rooms of the same type next to each other to merge."
        ok, merged_name = _merge_rooms(layout, floor_num, target, secondary)
        if not ok:
            return layout, plan, f"{target} and {secondary} don't share a clean straight boundary, so they can't be merged without disturbing other rooms."
        _sync_plan_from_layout(plan, layout, floor_num)
        return layout, plan, f"Merged {target} and {secondary} into {merged_name}."

    if action == "split":
        ok, new_name = _split_room(layout, floor_num, target)
        if not ok:
            return layout, plan, f"{target} is too small to split into two usable rooms."
        _sync_plan_from_layout(plan, layout, floor_num)
        return layout, plan, f"Split {target} into {target} and {new_name}."

    if action == "replace":
        new_name = parsed["new_room_name"] or "Study Room"
        for fr in layout["floors"].values():
            room = layout_agent._find_room(fr, target)
            if room:
                room["name"] = new_name
        for r in plan["rooms"]:
            if r["name"] == target:
                r["name"] = new_name
        return layout, plan, f"Converted {target} to {new_name} (footprint unchanged)."

    if action == "rotate":
        room = layout_agent._find_room(layout["floors"][floor_num], target)
        old_w, old_h = room["width"], room["height"]
        room["width"], room["height"] = old_h, old_w
        v = validator.validate(layout)
        if not v["valid"]:
            room["width"], room["height"] = old_w, old_h
            return layout, plan, f"Rotating {target} would overlap its neighbors, so it was left unchanged."
        return layout, plan, f"Rotated {target}."

    if action in ("improve_ventilation", "improve_lighting"):
        room = layout_agent._find_room(layout["floors"][floor_num], target)
        plot_w, plot_h = layout["plot_width"], layout["plot_height"]
        label = "ventilation" if action == "improve_ventilation" else "natural lighting"
        if _touches_exterior(room, plot_w, plot_h):
            return layout, plan, f"{target} already sits on an outer wall, so it already has scope for {label}."
        swapped = _swap_with_exterior_neighbor(layout, floor_num, target)
        if swapped:
            return layout, plan, f"Swapped {target} with a similarly-sized exterior room to give it {label}."
        return layout, plan, f"Couldn't find a similarly-sized exterior room on the same floor to safely swap {target} with."

    return layout, plan, "Instruction understood but no matching operation was applied."