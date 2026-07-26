"""
Agent 5 - PDF Export Module
-----------------------------
Deterministic. Builds a downloadable PDF report combining the room-by-room
floor plan summary and the full budget report (cost breakdown, material
estimate). No LLM is involved.

Note: this exports a text/table summary of the plan, not the SVG floor
plan drawing itself - kept intentionally simple so it has no extra
rendering dependencies beyond fpdf2.
"""

import io

from fpdf import FPDF


def _sanitize(text: str) -> str:
    """Core PDF fonts only support latin-1; swap out characters (like the
    rupee symbol) that budget_agent's free-text messages may contain."""
    return (text or "").replace("\u20b9", "Rs. ").encode("latin-1", "replace").decode("latin-1")


def _sanitize_svg(svg: str) -> str:
    """Same latin-1 constraint applies to text embedded inside the SVG
    (fpdf2 renders <text> nodes itself), plus swap characters that read
    fine as SVG but aren't valid latin-1, like the em/en dash used in
    blueprint_agent's title ("House — Floor 1")."""
    svg = (svg or "").replace("\u2014", "-").replace("\u2013", "-").replace("\u20b9", "Rs. ")
    return svg.encode("latin-1", "replace").decode("latin-1")


def _add_svg_blueprint(pdf: FPDF, svg: str, max_width: float = 190):
    """Embeds a blueprint_agent SVG floor plan directly (as vector, not a
    rasterized image) into the current page, sized to fit the margins."""
    svg_bytes = io.BytesIO(_sanitize_svg(svg).encode("latin-1"))
    svg_bytes.name = "blueprint.svg"  # fpdf2 image() needs a name to detect the SVG format
    pdf.image(svg_bytes, x=(pdf.w - max_width) / 2, w=max_width)


def _add_heading(pdf: FPDF, text: str):
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(44, 62, 80)
    pdf.cell(0, 10, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)


def _add_subheading(pdf: FPDF, text: str):
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(44, 62, 80)
    pdf.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)


def _add_row(pdf: FPDF, label: str, value: str, col_w=95):
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(col_w, 6, label)
    pdf.cell(0, 6, value, new_x="LMARGIN", new_y="NEXT")


def build_report_pdf(plan: dict, layout: dict, budget: dict, svg_by_floor: dict = None) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(44, 62, 80)
    pdf.cell(0, 12, "Preliminary Construction Plan Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 6, "Universal AI Residential Construction Planner", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0)

    # --- Plan summary ---
    _add_heading(pdf, "Plan Summary")
    _add_row(pdf, "Plot Area:", f"{plan.get('plot_area_sqft', '-')} sqft")
    _add_row(pdf, "Floors:", str(plan.get("floors", "-")))
    _add_row(pdf, "Facing:", str(plan.get("facing", "-")))
    _add_row(pdf, "Bedrooms Requested:", str(plan.get("bedrooms_requested", "-")))
    pdf.ln(4)

    # --- Floor plans (room-by-room) ---
    _add_heading(pdf, "Floor Plans - Room Summary")
    for floor_num in sorted(layout["floors"].keys()):
        _add_subheading(pdf, f"Floor {floor_num}")
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(70, 7, "Room", border=1, fill=True)
        pdf.cell(60, 7, "Dimensions (ft)", border=1, fill=True)
        pdf.cell(0, 7, "Area (sqft)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for room in layout["floors"][floor_num]:
            pdf.cell(70, 7, str(room["name"]), border=1)
            pdf.cell(60, 7, f'{room["width"]:.1f} x {room["height"]:.1f}', border=1)
            pdf.cell(0, 7, f'{room["area"]:.1f}', border=1, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    # --- Floor plan blueprints (the actual SVG drawings, not just the table) ---
    if svg_by_floor:
        for floor_num in sorted(layout["floors"].keys()):
            svg = svg_by_floor.get(floor_num) or svg_by_floor.get(str(floor_num))
            if not svg:
                continue
            pdf.add_page()
            _add_heading(pdf, f"Floor {floor_num} - Blueprint")
            _add_svg_blueprint(pdf, svg)

    # --- Budget report ---
    pdf.add_page()
    _add_heading(pdf, "Budget Report")
    _add_row(pdf, "Built-up Area:", f'{budget.get("built_up_area_sqft", "-")} sqft')
    region = budget.get("region", "default")
    if region and region != "default":
        _add_row(pdf, "Region:", f'{region.title()} (x{budget.get("region_multiplier", 1.0)})')
    _add_row(pdf, "Rate per sqft:", f'Rs. {budget.get("rate_per_sqft_inr", "-")}')
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(230, 126, 34)
    pdf.cell(0, 10, f'Estimated Total: Rs. {budget.get("estimated_total_cost_inr", 0):,}',
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    _add_subheading(pdf, "Cost Breakdown")
    pdf.set_font("Helvetica", "", 10)
    for label, value in budget.get("cost_breakdown_inr", {}).items():
        pdf.cell(130, 6, label)
        pdf.cell(0, 6, f"Rs. {value:,}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    if budget.get("material_estimate"):
        _add_subheading(pdf, "Material-wise Estimate (approximate)")
        pdf.set_font("Helvetica", "", 10)
        for label, qty in budget["material_estimate"].items():
            pdf.cell(130, 6, label)
            pdf.cell(0, 6, f"{qty:,}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    if budget.get("budget_fit"):
        fit = budget["budget_fit"]
        _add_subheading(pdf, "Budget Fit Analysis")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, _sanitize(fit.get("fit_message", "")))
        pdf.ln(2)

    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 5, _sanitize(budget.get("disclaimer", "")))

    return bytes(pdf.output())