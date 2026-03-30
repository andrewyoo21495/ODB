"""CKL-02-004: Managed capacitors (41 types) vs LED Flash / RF components.

Do not place any of the 41 managed capacitor types on the opposite side of
LED Flash components.  Maintain a clearance of at least 0.5mm when placing
them on the opposite side of RF components.
"""

from __future__ import annotations

from src.checklist.component_classifier import find_leds, find_rf_components
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    edge_distance,
    find_overlapping_components,
)
from src.checklist.reference_loader import get_managed_part_names
from src.checklist.rule_base import ChecklistRule
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

        columns = [
            "comp", "cmp_layer", "overlapping_cmp", "part_name",
            "distance", "status",
        ]
        rows: list[dict] = []

        for layer_comps, layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
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
                for cap in overlaps:
                    rows.append({
                        "comp": led.comp_name,
                        "cmp_layer": layer,
                        "overlapping_cmp": cap.comp_name,
                        "part_name": cap.part_name or "",
                        "distance": "-",
                        "status": "FAIL",
                    })

            # --- RF: overlap or distance < 0.5mm is FAIL ---
            for rf in rfs:
                overlaps = find_overlapping_components(
                    rf, opp_managed_caps, packages,
                )
                for cap in overlaps:
                    dist = edge_distance(rf, cap, packages)
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
        )
