"""CKL-02-004: Managed capacitors (41 types) vs LED Flash / RF components.

Do not place any of the 41 managed capacitor types on the opposite side of
LED Flash components.  Maintain a clearance of at least 0.5mm when placing
them on the opposite side of RF components.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import find_leds, find_rf_components
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    find_overlapping_components,
    pad_to_pad_distance,
)
from src.checklist.reference_loader import get_managed_part_names
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import RuleResult


_MIN_DISTANCE_MM = 0.5


@register_rule
class CKL02004(ChecklistRule):
    rule_id = "CKL-02-004"
    description = (
        "Do not place 41 managed capacitor types on the opposite side of "
        "LED Flash components. Maintain >= 0.5mm clearance on the opposite "
        "side of RF components."
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        managed_41 = get_managed_part_names("capacitors_41_list")
        user_symbols: dict = job_data.get("user_symbols") or {}

        columns = [
            "comp", "cmp_layer", "overlapping_cmp", "part_name",
            "distance", "status",
        ]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_02_004_"))

        for layer_comps, layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            primary_is_bottom = (layer == "Bottom")
            overlap_is_bottom = not primary_is_bottom
            leds = find_leds(layer_comps)
            rfs = find_rf_components(layer_comps)

            # Filter opposite-side capacitors to managed 41 types
            opp_managed_caps = [
                c for c in opp_comps
                if (c.part_name or "") in managed_41
            ]
            if not opp_managed_caps:
                continue

            # --- LED Flash: any overlap is FAIL ---
            for led in leds:
                overlaps = find_overlapping_components(
                    led, opp_managed_caps, packages,
                )
                overlap_items: list[dict] = []
                for cap in overlaps:
                    rows.append({
                        "comp": led.comp_name,
                        "cmp_layer": layer,
                        "overlapping_cmp": cap.comp_name,
                        "part_name": cap.part_name or "",
                        "distance": "-",
                        "status": "FAIL",
                    })
                    overlap_items.append({"comp": cap, "status": "FAIL"})

                if overlap_items:
                    safe = led.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{layer}.png"
                    render_overlap_image(
                        led, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="LED Flash opposite-side cap",
                        layer_name=layer,
                        primary_label="LED Flash",
                        overlap_label="Managed cap",
                        primary_is_bottom=primary_is_bottom,
                        overlap_is_bottom=overlap_is_bottom,
                        user_symbols=user_symbols,
                    )
                    images.append({"path": img_path,
                                   "title": f"{led.comp_name} ({layer})",
                                   "width": 500})

            # --- RF: overlap or distance < 0.5mm is FAIL ---
            for rf in rfs:
                overlaps = find_overlapping_components(
                    rf, opp_managed_caps, packages,
                )
                overlap_items_rf: list[dict] = []
                for cap in overlaps:
                    dist = pad_to_pad_distance(
                        rf, cap, packages,
                        is_bottom_a=primary_is_bottom,
                        is_bottom_b=overlap_is_bottom,
                        user_symbols=user_symbols,
                    )
                    dist_str = f"{dist:.3f}" if dist < float("inf") else "0.000"
                    status = "FAIL" if dist < _MIN_DISTANCE_MM else "PASS"
                    rows.append({
                        "comp": rf.comp_name,
                        "cmp_layer": layer,
                        "overlapping_cmp": cap.comp_name,
                        "part_name": cap.part_name or "",
                        "distance": dist_str,
                        "status": status,
                    })
                    overlap_items_rf.append({
                        "comp": cap, "status": status,
                        "distance": dist if dist < float("inf") else None,
                        "min_distance": _MIN_DISTANCE_MM,
                    })

                if overlap_items_rf:
                    safe = rf.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{layer}.png"
                    render_overlap_image(
                        rf, packages, overlap_items_rf, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="RF opposite-side cap clearance",
                        layer_name=layer,
                        primary_label="RF",
                        overlap_label="Managed cap",
                        primary_is_bottom=primary_is_bottom,
                        overlap_is_bottom=overlap_is_bottom,
                        user_symbols=user_symbols,
                    )
                    images.append({"path": img_path,
                                   "title": f"{rf.comp_name} ({layer})",
                                   "width": 500})

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"{fail_count} managed capacitor(s) violating LED Flash / RF "
                f"opposite-side placement rule."
                if not passed
                else "All managed capacitors meet LED Flash / RF opposite-side requirements."
            ),
            affected_components=[
                r["overlapping_cmp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
