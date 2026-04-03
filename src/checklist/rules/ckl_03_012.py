"""CKL-03-012: OSC components — PCB edge, BOTHHOLE clearance, and Shield Can check.

Ensure Oscillator (OSC) component pads are placed at least 1mm away from
the PCB edge and BOTHHOLE components.  Distances are measured from the
actual pad geometry of the OSC component (not from its outline or centre).

Additionally, record whether each OSC component is located inside a
Shield Can region (inSC column: TRUE / FALSE).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import (
    find_bothholes, find_oscillators, find_shield_cans,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    build_board_polygon,
    find_components_inside_outline,
    pad_distance_to_component,
    pad_distance_to_outline,
)
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.clearance_viz import render_clearance_image
from src.models import RuleResult


_MIN_CLEARANCE_MM = 1.0


@register_rule
class CKL03012(ChecklistRule):
    rule_id = "CKL-03-012"
    description = (
        "OSC components must be at least 1mm from PCB edge and BOTHHOLE components"
    )
    category = "Clearance"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        profile = job_data.get("profile")
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        board_poly = build_board_polygon(profile)

        # Collect all BOTHHOLE components from both sides
        all_bothholes = find_bothholes(components_top) + find_bothholes(components_bot)

        # Collect all Shield Can components from both sides
        all_shield_cans = find_shield_cans(components_top) + find_shield_cans(components_bot)

        columns = ["comp", "cmp_layer", "to_pcb", "to_BTH", "inSC", "status"]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_03_012_"))

        for comps, layer_name in [
            (components_top, "Top"),
            (components_bot, "Bottom"),
        ]:
            oscs = find_oscillators(comps)

            for osc in oscs:
                # Distance from OSC pads to PCB outline
                if board_poly is not None:
                    dist_pcb = pad_distance_to_outline(osc, board_poly, packages)
                else:
                    dist_pcb = float("inf")

                # Distance from OSC pads to nearest BOTHHOLE
                dist_bth = float("inf")
                nearest_bth = None
                for bth in all_bothholes:
                    d = pad_distance_to_component(osc, bth, packages)
                    if d < dist_bth:
                        dist_bth = d
                        nearest_bth = bth

                # Check if OSC is inside any Shield Can outline
                in_sc = False
                for sc in all_shield_cans:
                    inside = find_components_inside_outline(sc, [osc], packages)
                    if inside:
                        in_sc = True
                        break

                pcb_str = f"{dist_pcb:.3f}" if dist_pcb < float("inf") else "N/A"
                bth_str = f"{dist_bth:.3f}" if dist_bth < float("inf") else "N/A"

                status = (
                    "PASS"
                    if dist_pcb >= _MIN_CLEARANCE_MM and dist_bth >= _MIN_CLEARANCE_MM
                    else "FAIL"
                )

                rows.append({
                    "comp": osc.comp_name,
                    "cmp_layer": layer_name,
                    "to_pcb": pcb_str,
                    "to_BTH": bth_str,
                    "inSC": "TRUE" if in_sc else "FALSE",
                    "status": status,
                })

                # Generate visualisation image for this OSC
                safe_name = osc.comp_name.replace("/", "_")
                img_path = image_dir / f"{safe_name}_{layer_name}.png"

                # Build distance entries for clearance viz
                viz_distances: list[dict] = []
                if board_poly is not None and dist_pcb < float("inf"):
                    viz_distances.append({
                        "label": "PCB edge",
                        "value": dist_pcb,
                        "target_geom": board_poly.boundary,
                        "target_comp": None,
                    })
                if nearest_bth is not None and dist_bth < float("inf"):
                    viz_distances.append({
                        "label": "BOTHHOLE",
                        "value": dist_bth,
                        "target_geom": None,
                        "target_comp": nearest_bth,
                    })

                render_clearance_image(
                    osc, packages, board_poly, all_bothholes,
                    viz_distances, img_path,
                    rule_id=self.rule_id,
                    title="PCB edge & BOTHHOLE clearance",
                    layer_name=layer_name,
                    comp_label="OSC",
                    ref_label="BOTHHOLE",
                    min_clearance=_MIN_CLEARANCE_MM,
                )
                images.append({
                    "path": img_path,
                    "title": f"{osc.comp_name} ({layer_name})",
                    "width": 500,
                })

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"{fail_count} OSC component(s) too close to PCB edge or BOTHHOLE."
                if not passed
                else "All OSC components meet the 1mm clearance requirement."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
