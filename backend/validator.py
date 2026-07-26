"""
Layout Validator
----------------
Rule-based validation that runs after the Layout Agent generates room
geometry, and before the Blueprint Agent renders SVG.

Checks:
  - Room overlap
  - Plot boundary violations
  - Invalid coordinates
  - Room dimensions
  - Area consistency
"""


def _rects_overlap(a, b):
    eps = 0.05  # feet — tolerance for floating point rounding at shared edges
    return not (a["x"] + a["width"] <= b["x"] + eps or
                b["x"] + b["width"] <= a["x"] + eps or
                a["y"] + a["height"] <= b["y"] + eps or
                b["y"] + b["height"] <= a["y"] + eps)


def validate(layout: dict) -> dict:
    """
    Returns {"valid": bool, "errors": [str, ...]} for the given layout
    (as produced by layout_agent.generate_layout).
    """
    errors = []
    plot_w = layout["plot_width"]
    plot_h = layout["plot_height"]

    for floor_num, rooms in layout["floors"].items():
        for room in rooms:
            if room["width"] <= 0 or room["height"] <= 0:
                errors.append(f"Floor {floor_num}: '{room['name']}' has invalid dimensions.")

            expected_area = round(room["width"] * room["height"], 2)
            if abs(expected_area - room["area"]) > 0.5:
                errors.append(f"Floor {floor_num}: '{room['name']}' area is inconsistent with its dimensions.")

            # Staircase is intentionally allowed to sit outside plot bounds
            if room["name"] != "Staircase":
                if room["x"] < -0.01 or room["y"] < -0.01:
                    errors.append(f"Floor {floor_num}: '{room['name']}' has invalid (negative) coordinates.")
                if room["x"] + room["width"] > plot_w + 0.5 or room["y"] + room["height"] > plot_h + 0.5:
                    errors.append(f"Floor {floor_num}: '{room['name']}' exceeds the plot boundary.")

        # Overlap check (O(n^2), fine for typical residential room counts)
        non_stair = [r for r in rooms if r["name"] != "Staircase"]
        for i in range(len(non_stair)):
            for j in range(i + 1, len(non_stair)):
                if _rects_overlap(non_stair[i], non_stair[j]):
                    errors.append(
                        f"Floor {floor_num}: '{non_stair[i]['name']}' overlaps with '{non_stair[j]['name']}'."
                    )

    return {"valid": len(errors) == 0, "errors": errors}
