"""
Agent 2 — Layout Agent (Deterministic)
---------------------------------------
Pure Python, no AI. Converts the Planning Agent's room list into actual
room geometries (x, y, width, height, area) using recursive spatial
partitioning.

Multiple layout variations are produced by changing the recursive
partitioning order (controlled by `seed`), while always respecting each
room's relative area weight and floor.
"""

import math
import random

from planning_agent import DEFAULT_ROOM_WEIGHTS

MIN_ROOM_DIM = 6.0  # feet, floor for any room's width/height


def _plot_dimensions(plot_area_sqft: float):
    """Derive a plot width/height (feet) from total area, ~1.2:1 ratio."""
    width = math.sqrt(plot_area_sqft * 1.2)
    height = plot_area_sqft / width
    return round(width, 2), round(height, 2)


def _room_weight(name: str) -> float:
    if name in DEFAULT_ROOM_WEIGHTS:
        return DEFAULT_ROOM_WEIGHTS[name]
    if name.startswith("Bedroom"):
        return DEFAULT_ROOM_WEIGHTS["Bedroom"]
    return 0.08  # fallback weight for unknown room types


def _split_rect(rect, rooms, seed_rng):
    """
    Recursively split `rect` (x, y, w, h) among `rooms` (list of dicts),
    proportional to each room's weight, alternating split axis based on
    the rectangle's own aspect ratio for natural-looking layouts.
    """
    x, y, w, h = rect

    if len(rooms) == 1:
        room = rooms[0]
        room["x"] = round(x, 2)
        room["y"] = round(y, 2)
        # We intentionally do NOT clamp to MIN_ROOM_DIM here, since forcing
        # a minimum size would break the exclusive-rectangle partition
        # invariant and cause overlaps with neighboring rooms.
        room["width"] = round(w, 2)
        room["height"] = round(h, 2)
        room["area"] = round(room["width"] * room["height"], 2)
        return [room]

    # Keep the priority order intact (it encodes the Public -> Semi-Private
    # -> Private -> Service zoning hierarchy, and adjacency pairs like
    # Master Bedroom + Attached Bathroom). A full shuffle would scatter
    # rooms across zones randomly, so only an occasional full reversal is
    # used for seed-to-seed variation — it still keeps every room's
    # neighbors from the original order intact, just mirrored.
    ordered = rooms[:]
    if seed_rng.random() > 0.5:
        ordered = ordered[::-1]

    # Split the room list into two contiguous groups by index, with a
    # small random jitter on the split point (still balanced, but not
    # always exactly half) so different seeds produce different shapes.
    base_mid = len(ordered) // 2
    jitter = seed_rng.choice([-1, 0, 0, 1]) if len(ordered) > 3 else 0
    mid = max(1, min(len(ordered) - 1, base_mid + jitter))
    group_a = ordered[:mid]
    group_b = ordered[mid:]

    weight_a = sum(_room_weight(r["name"]) for r in group_a)
    weight_b = sum(_room_weight(r["name"]) for r in group_b)
    ratio = weight_a / (weight_a + weight_b) if (weight_a + weight_b) > 0 else 0.5

    # Usually split along the longer axis for natural proportions, but
    # occasionally split the other way to diversify the layout shape.
    natural_vertical = w >= h
    split_vertically = natural_vertical if seed_rng.random() > 0.25 else not natural_vertical

    results = []
    if split_vertically:
        w_a = round(w * ratio, 2)
        results += _split_rect((x, y, w_a, h), group_a, seed_rng)
        results += _split_rect((x + w_a, y, w - w_a, h), group_b, seed_rng)
    else:
        h_a = round(h * ratio, 2)
        results += _split_rect((x, y, w, h_a), group_a, seed_rng)
        results += _split_rect((x, y + h_a, w, h - h_a), group_b, seed_rng)

    return results


def _place_staircase(rooms, plot_w, plot_h, side="right"):
    """Staircase is attached outside the main layout rectangle, next to
    the Living Room, exactly one per floor-group, reused across floors."""
    staircase = next((r for r in rooms if r["name"] == "Staircase"), None)
    if not staircase:
        return rooms

    stair_w, stair_h = 6.0, plot_h

    if side == "right":
        staircase["x"] = round(plot_w, 2)
        staircase["y"] = 0
    else:
        staircase["x"] = round(-stair_w, 2)
        staircase["y"] = 0

    staircase["width"] = stair_w
    staircase["height"] = stair_h
    staircase["area"] = round(stair_w * stair_h, 2)
    return rooms


def generate_layout(plan: dict, seed: int = 0) -> dict:
    """
    Generates one full layout variation (all floors) for the given plan.
    Returns {"plot_width", "plot_height", "floors": {1: [...], 2: [...]}}
    """
    seed_rng = random.Random(seed)
    plot_area = plan["plot_area_sqft"]
    plot_w, plot_h = _plot_dimensions(plot_area)

    rooms = plan["rooms"]
    floors_present = sorted(set(r.get("floor", 1) for r in rooms))

    floor_layouts = {}
    for floor_num in floors_present:
        floor_rooms = [dict(r) for r in rooms if r.get("floor", 1) == floor_num
                        and r["name"] != "Staircase"]
        if not floor_rooms:
            continue
        # Sort by priority so recursive split roughly respects intended order
        floor_rooms.sort(key=lambda r: r["priority"])
        placed = _split_rect((0, 0, plot_w, plot_h), floor_rooms, seed_rng)

        # Re-attach staircase reference to this floor (reused position)
        staircase_template = next((r for r in rooms if r["name"] == "Staircase"), None)
        if staircase_template:
            stair_copy = dict(staircase_template)
            placed = _place_staircase(placed + [stair_copy], plot_w, plot_h,
                                       side="right" if seed % 2 == 0 else "left")
            # ensure staircase included once
            if not any(r["name"] == "Staircase" for r in placed):
                placed.append(stair_copy)

        floor_layouts[floor_num] = placed

    return {
        "plot_width": plot_w,
        "plot_height": plot_h,
        "floors": floor_layouts,
        "seed": seed,
    }


def _clean_room_phrase(phrase: str) -> str:
    """Strips leading articles ('the', 'a', 'an') and extra whitespace so
    'the kitchen' matches the room named 'Kitchen'."""
    phrase = phrase.strip().lower()
    for article in ("the ", "a ", "an "):
        if phrase.startswith(article):
            phrase = phrase[len(article):]
    return phrase.strip()


def _find_room(rooms, phrase: str):
    """Fuzzy, case-insensitive room lookup: matches on exact name first,
    then falls back to substring matching either direction (so 'bedroom'
    can match 'Bedroom 1', and 'master bed' can match 'Master Bedroom')."""
    phrase = _clean_room_phrase(phrase)
    for r in rooms:
        if r["name"].lower() == phrase:
            return r
    for r in rooms:
        name = r["name"].lower()
        if phrase in name or name in phrase:
            return r
    return None


def _rects_overlap(a, b):
    return not (a["x"] + a["width"] <= b["x"] or
                b["x"] + b["width"] <= a["x"] or
                a["y"] + a["height"] <= b["y"] or
                b["y"] + b["height"] <= a["y"])


def _rooms_adjacent(a, b):
    """True if two room rectangles share an edge (touching, not overlapping)."""
    touching_vertically = (abs((a["x"] + a["width"]) - b["x"]) < 0.05 or
                            abs((b["x"] + b["width"]) - a["x"]) < 0.05)
    touching_horizontally = (abs((a["y"] + a["height"]) - b["y"]) < 0.05 or
                              abs((b["y"] + b["height"]) - a["y"]) < 0.05)
    y_overlap = not (a["y"] + a["height"] <= b["y"] or b["y"] + b["height"] <= a["y"])
    x_overlap = not (a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"])
    return (touching_vertically and y_overlap) or (touching_horizontally and x_overlap)


def _clean_shared_edge(a, b):
    """
    Returns 'vertical' if `a` and `b` sit side-by-side (share a vertical
    boundary) and that boundary spans BOTH rooms' full height, or
    'horizontal' if they're stacked and the boundary spans both rooms'
    full width. In either case, shifting the shared boundary only
    affects these two rooms — no other room touches that edge, so the
    tiling stays gap-free and overlap-free. Returns None if the rooms
    don't share a full, clean edge (resizing would risk disturbing a
    third room).
    """
    eps = 0.05
    same_y_span = abs(a["y"] - b["y"]) < eps and abs(a["height"] - b["height"]) < eps
    same_x_span = abs(a["x"] - b["x"]) < eps and abs(a["width"] - b["width"]) < eps

    if same_y_span and (abs((a["x"] + a["width"]) - b["x"]) < eps or
                         abs((b["x"] + b["width"]) - a["x"]) < eps):
        return "vertical"
    if same_x_span and (abs((a["y"] + a["height"]) - b["y"]) < eps or
                         abs((b["y"] + b["height"]) - a["y"]) < eps):
        return "horizontal"
    return None


def _resize_room(rooms, room_name, grow: bool):
    """
    Grows or shrinks `room_name` by ~15%, by moving the boundary it
    shares with a cleanly-adjacent neighbor (see _clean_shared_edge).
    Picks the neighbor with the most spare room to give up. No-op if no
    such neighbor exists, or if the neighbor would drop below the
    minimum usable room dimension.
    """
    non_stair = [r for r in rooms if r["name"] != "Staircase"]
    room = _find_room(non_stair, room_name)
    if not room:
        return False

    candidates = []
    for other in non_stair:
        if other is room:
            continue
        edge = _clean_shared_edge(room, other)
        if edge:
            candidates.append((edge, other))
    if not candidates:
        return False

    # Prefer the neighbor with the larger spare dimension along the
    # relevant axis, so shrinking it is least disruptive.
    def spare(item):
        edge, other = item
        return other["width"] if edge == "vertical" else other["height"]

    edge, neighbor = max(candidates, key=spare)

    if edge == "vertical":
        delta = round(room["width"] * 0.15, 2) if grow else -round(room["width"] * 0.15, 2)
        # Shrinking `room` or growing it eats into `neighbor`'s width.
        new_room_w = room["width"] + delta
        new_neighbor_w = neighbor["width"] - delta
        if min(new_room_w, new_neighbor_w) < MIN_ROOM_DIM:
            return False
        if room["x"] <= neighbor["x"]:
            # room is left of neighbor: room's right edge moves
            room["width"] = round(new_room_w, 2)
            neighbor["x"] = round(neighbor["x"] + delta, 2)
            neighbor["width"] = round(new_neighbor_w, 2)
        else:
            # room is right of neighbor: room's left edge moves
            room["x"] = round(room["x"] - delta, 2)
            room["width"] = round(new_room_w, 2)
            neighbor["width"] = round(new_neighbor_w, 2)
    else:
        delta = round(room["height"] * 0.15, 2) if grow else -round(room["height"] * 0.15, 2)
        new_room_h = room["height"] + delta
        new_neighbor_h = neighbor["height"] - delta
        if min(new_room_h, new_neighbor_h) < MIN_ROOM_DIM:
            return False
        if room["y"] <= neighbor["y"]:
            room["height"] = round(new_room_h, 2)
            neighbor["y"] = round(neighbor["y"] + delta, 2)
            neighbor["height"] = round(new_neighbor_h, 2)
        else:
            room["y"] = round(room["y"] - delta, 2)
            room["height"] = round(new_room_h, 2)
            neighbor["height"] = round(new_neighbor_h, 2)

    room["area"] = round(room["width"] * room["height"], 2)
    neighbor["area"] = round(neighbor["width"] * neighbor["height"], 2)
    return True


def revise_layout(layout: dict, instruction: str) -> dict:
    """
    Small rule-based revision engine. Supports:
      - "Move <Room A> near <Room B>"
      - "Swap <Room A> and <Room B>" (works across floors too)
      - "Make <Room> bigger/larger" or "Make <Room> smaller"

    Because the Layout Agent fully tiles the plot (no gaps between rooms),
    simply repositioning or resizing one room's coordinates would overlap
    or leave a gap next to whichever room already occupies that space.
    Each supported instruction is implemented as a geometry-preserving
    operation (swap, or shift a shared boundary) so the tiling stays
    valid — zero overlap, zero gaps — after every revision.
    """
    import re

    swap_m = re.search(r"swap\s+(.+?)\s+(?:and|with)\s+(.+)", instruction, re.I)
    resize_m = re.search(r"make\s+(?:the\s+)?(.+?)\s+(bigger|larger|smaller)", instruction, re.I)
    move_m = re.search(r"move\s+(.+?)\s+near\s+(.+)", instruction, re.I)

    if swap_m:
        room_a_phrase, room_b_phrase = swap_m.group(1), swap_m.group(2)
        all_rooms = [(fnum, r) for fnum, rs in layout["floors"].items()
                     for r in rs if r["name"] != "Staircase"]
        entry_a = next((e for e in all_rooms if _find_room([e[1]], room_a_phrase)), None)
        entry_b = next((e for e in all_rooms if _find_room([e[1]], room_b_phrase)), None)
        if entry_a and entry_b and entry_a[1] is not entry_b[1]:
            room_a, room_b = entry_a[1], entry_b[1]
            for key in ("x", "y", "width", "height", "area"):
                room_a[key], room_b[key] = room_b[key], room_a[key]
        return layout

    if resize_m:
        room_phrase, direction = resize_m.group(1), resize_m.group(2).lower()
        grow = direction in ("bigger", "larger")
        for rooms in layout["floors"].values():
            if _find_room([r for r in rooms if r["name"] != "Staircase"], room_phrase):
                _resize_room(rooms, room_phrase, grow)
                break
        return layout

    if move_m:
        return _revise_move(layout, move_m.group(1), move_m.group(2))

    return layout  # no recognizable instruction; leave layout unchanged


def _revise_move(layout: dict, room_a_phrase: str, room_b_phrase: str) -> dict:
    """Original 'move A near B' behavior, extracted unchanged."""

    for floor_num, rooms in layout["floors"].items():
        non_stair = [r for r in rooms if r["name"] != "Staircase"]
        room_a = _find_room(non_stair, room_a_phrase)
        room_b = _find_room(non_stair, room_b_phrase)

        if not room_a or not room_b or room_a is room_b:
            continue

        if _rooms_adjacent(room_a, room_b):
            continue  # already satisfies the instruction, nothing to do

        # Find a neighbor of room_b (not room_a itself) to swap places with
        neighbor = next(
            (r for r in non_stair
             if r is not room_a and r is not room_b and _rooms_adjacent(r, room_b)),
            None
        )
        if neighbor is None:
            continue  # no valid swap target found; leave layout unchanged

        room_a["x"], neighbor["x"] = neighbor["x"], room_a["x"]
        room_a["y"], neighbor["y"] = neighbor["y"], room_a["y"]
        room_a["width"], neighbor["width"] = neighbor["width"], room_a["width"]
        room_a["height"], neighbor["height"] = neighbor["height"], room_a["height"]
        room_a["area"], neighbor["area"] = neighbor["area"], room_a["area"]

    return layout


# ======================================================================
# Merged in from blueprint_agent.py (SVG floor plan rendering)
# ======================================================================

"""
Agent 3 — Blueprint Generation Agent
-------------------------------------
Deterministic. Converts validated room geometry into an SVG floor plan.
No LLM is involved.
"""

SCALE = 12  # pixels per foot
MARGIN = 60


def room_color(name: str) -> str:
    palette = {
        "Living Room": "#FDEBD0",
        "Kitchen": "#D6EAF8",
        "Master Bedroom": "#E8DAEF",
        "Bathroom": "#D5F5E3",
        "Attached Bathroom": "#D5F5E3",
        "Common Bathroom": "#D5F5E3",
        "Pooja Room": "#FCF3CF",
        "Parking": "#EAECEE",
        "Dining": "#FADBD8",
        "Family Hall": "#D0ECE7",
        "Open Terrace": "#F5EEF8",
        "Staircase": "#D7DBDD",
    }
    if name in palette:
        return palette[name]
    if name.startswith("Bedroom"):
        return "#E8DAEF"
    return "#F2F3F4"


# Backwards-compatible alias (old internal name).
_room_color = room_color


def compute_entrance(rooms: list, plot_w: float, plot_h: float, facing: str = "South"):
    """
    Works out which exterior wall the Main Entrance should sit on, and
    its position in feet, for a single floor's room list. The entrance
    must always open into the Living Room, so it's placed on one of the
    Living Room's own exterior edges (an edge that lies on the plot
    boundary) — never on a wall the Living Room doesn't actually touch.
    Among the Living Room's exterior edges, the user's requested facing
    is preferred; otherwise the first exterior edge found is used.

    Returns {"wall": "North"|"South"|"East"|"West", "x_ft": float, "y_ft": float}
    or None if there's no Living Room to anchor the entrance to.
    """
    living_room = next((r for r in rooms if r["name"] == "Living Room"), None)
    if not living_room:
        return None

    preferred = (facing or "South").split("-")[0].strip().title()
    if preferred not in ("North", "South", "East", "West"):
        preferred = "South"

    eps = 0.05
    exterior_walls = []
    if living_room["y"] <= eps:
        exterior_walls.append("North")
    if living_room["y"] + living_room["height"] >= plot_h - eps:
        exterior_walls.append("South")
    if living_room["x"] <= eps:
        exterior_walls.append("West")
    if living_room["x"] + living_room["width"] >= plot_w - eps:
        exterior_walls.append("East")

    if not exterior_walls:
        return None
    wall = preferred if preferred in exterior_walls else exterior_walls[0]

    if wall in ("South", "North"):
        x_ft = living_room["x"] + living_room["width"] / 2
        y_ft = plot_h if wall == "South" else 0
    else:
        y_ft = living_room["y"] + living_room["height"] / 2
        x_ft = plot_w if wall == "East" else 0

    return {"wall": wall, "x_ft": x_ft, "y_ft": y_ft}


def render_svg(layout: dict, floor_num: int, house_title: str = "Preliminary Floor Plan",
                facing: str = "South") -> str:
    plot_w = layout["plot_width"]
    plot_h = layout["plot_height"]
    rooms = layout["floors"].get(floor_num, [])

    svg_w = int(plot_w * SCALE) + MARGIN * 2 + 80  # extra room for staircase outside
    svg_h = int(plot_h * SCALE) + MARGIN * 2 + 40

    def to_px_x(ft):
        return MARGIN + ft * SCALE + 40

    def to_px_y(ft):
        return MARGIN + ft * SCALE + 30

    parts = [f'<svg viewBox="0 0 {svg_w} {svg_h}" xmlns="http://www.w3.org/2000/svg" font-family="Helvetica, Arial, sans-serif">']
    parts.append(f'<rect x="0" y="0" width="{svg_w}" height="{svg_h}" fill="#ffffff"/>')
    parts.append(f'<text x="{svg_w/2}" y="28" text-anchor="middle" font-size="18" font-weight="bold" fill="#2C3E50">{house_title} — Floor {floor_num}</text>')

    # Plot boundary
    px, py = to_px_x(0), to_px_y(0)
    pw, ph = plot_w * SCALE, plot_h * SCALE
    parts.append(f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" fill="none" stroke="#2C3E50" stroke-width="3"/>')

    for room in rooms:
        rx, ry = to_px_x(room["x"]), to_px_y(room["y"])
        rw, rh = room["width"] * SCALE, room["height"] * SCALE
        color = _room_color(room["name"])
        stroke = "#7F8C8D" if room["name"] != "Staircase" else "#5D6D7E"

        parts.append(f'<rect x="{rx}" y="{ry}" width="{rw}" height="{rh}" fill="{color}" stroke="{stroke}" stroke-width="2"/>')

        # Door tick: small gap marker on the room's bottom edge
        door_x = rx + rw * 0.3
        parts.append(f'<rect x="{door_x}" y="{ry+rh-3}" width="{rw*0.18}" height="6" fill="#ffffff" stroke="#B03A2E" stroke-width="1"/>')

        # Window tick: small marker on the room's top edge (skip staircase)
        if room["name"] != "Staircase":
            win_x = rx + rw * 0.6
            parts.append(f'<rect x="{win_x}" y="{ry-3}" width="{rw*0.2}" height="6" fill="#AED6F1" stroke="#2874A6" stroke-width="1"/>')

        # Room label + dimensions
        label_y = ry + rh / 2 - 6
        parts.append(f'<text x="{rx+rw/2}" y="{label_y}" text-anchor="middle" font-size="12" font-weight="600" fill="#1C2833">{room["name"]}</text>')
        parts.append(f'<text x="{rx+rw/2}" y="{label_y+16}" text-anchor="middle" font-size="10" fill="#566573">{room["width"]:.1f}ft x {room["height"]:.1f}ft</text>')

    # Main entrance marker — drawn AFTER the rooms so it always renders on
    # top instead of being partly covered by a room's fill. Only applies
    # to the ground floor (Floor 1), since upper floors are accessed via
    # the internal staircase, not a street-facing entrance. The entrance
    # must always open into the Living Room, so it's placed on one of the
    # Living Room's own exterior edges (an edge that lies on the plot
    # boundary) — never on a wall the Living Room doesn't actually touch,
    # which previously could land the marker next to a different room.
    # Among the Living Room's exterior edges, the user's requested facing
    # is preferred; otherwise the first exterior edge found is used.
    if floor_num == 1:
        living_room = next((r for r in rooms if r["name"] == "Living Room"), None)
        preferred = (facing or "South").split("-")[0].strip().title()
        if preferred not in ("North", "South", "East", "West"):
            preferred = "South"

        wall = None
        if living_room:
            eps = 0.05
            exterior_walls = []
            if living_room["y"] <= eps:
                exterior_walls.append("North")
            if living_room["y"] + living_room["height"] >= plot_h - eps:
                exterior_walls.append("South")
            if living_room["x"] <= eps:
                exterior_walls.append("West")
            if living_room["x"] + living_room["width"] >= plot_w - eps:
                exterior_walls.append("East")
            if preferred in exterior_walls:
                wall = preferred
            elif exterior_walls:
                wall = exterior_walls[0]

        if wall and living_room:
            if wall in ("South", "North"):
                entrance_x_ft = living_room["x"] + living_room["width"] / 2
                entrance_x = to_px_x(entrance_x_ft)
                entrance_y = py + ph if wall == "South" else py
                label_x, label_y = entrance_x, (entrance_y + 20 if wall == "South" else entrance_y - 12)
                text_anchor = "middle"
            else:
                entrance_y_ft = living_room["y"] + living_room["height"] / 2
                entrance_y = to_px_y(entrance_y_ft)
                entrance_x = px + pw if wall == "East" else px
                # Push the label outward (away from the plot/rooms) instead
                # of centering it on the wall line, so it never overlaps a room.
                label_x = entrance_x + 10 if wall == "East" else entrance_x - 10
                label_y = entrance_y + 4
                text_anchor = "start" if wall == "East" else "end"

            parts.append(f'<circle cx="{entrance_x}" cy="{entrance_y}" r="6" fill="#E74C3C"/>')
            parts.append(f'<text x="{label_x}" y="{label_y}" text-anchor="{text_anchor}" font-size="11" fill="#E74C3C">Main Entrance</text>')

    # Plot dimensions label
    parts.append(f'<text x="{px+pw/2}" y="{py+ph+40}" text-anchor="middle" font-size="12" fill="#2C3E50">Plot: {plot_w:.1f} ft x {plot_h:.1f} ft ({plot_w*plot_h:.0f} sqft)</text>')

    parts.append('</svg>')
    return "".join(parts)


def render_all_floors(layout: dict, house_title: str = "Preliminary Floor Plan",
                       facing: str = "South") -> dict:
    """Returns {floor_num: svg_string} for every floor in the layout."""
    return {
        floor_num: render_svg(layout, floor_num, house_title, facing=facing)
        for floor_num in layout["floors"].keys()
    }