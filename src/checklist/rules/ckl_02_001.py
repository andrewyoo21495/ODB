"""CKL-02-001: Managed capacitors vs connectors — distance check.

Verify placement and distance between 10 managed capacitor types and
connector components on the opposite side.  Distance must be >= 1.5mm.
"""

from __future__ import annotations

from src.checklist.component_classifier import find_connectors
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    edge_distance,
    find_overlapping_components,
)
from src.checklist.reference_loader import get_managed_part_names
from src.checklist.rule_base import ChecklistRule
from src.models import Component, RuleResult


_MIN_DISTANCE_MM = 1.5


@register_rule
class CKL02001(ChecklistRule):
    rule_id = "CKL-02-001"
    description = (
        "10 managed capacitor types must be at least 1.5mm from "
        "connectors on the opposite side"
    )
    category = "Spacing"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        managed_parts = get_managed_part_names("capacitors_10_list")

        columns = [
            "comp", "cmp_layer", "part_name",
            "overlapping_con", "distance", "status",
        ]
        rows: list[dict] = []

        for caps_layer_comps, cap_layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            # Filter to managed capacitors
            managed_caps = [
                c for c in caps_layer_comps
                if (c.part_name or "") in managed_parts
            ]
            opp_connectors = find_connectors(opp_comps)
            if not managed_caps or not opp_connectors:
                continue

            for cap in managed_caps:
                # Find connectors overlapping on opposite side
                overlaps = find_overlapping_components(
                    cap, opp_connectors, packages
                )
                if overlaps:
                    for conn in overlaps:
                        dist = edge_distance(cap, conn, packages)
                        dist_str = f"{dist:.3f}" if dist < float("inf") else "N/A"
                        status = "PASS" if dist >= _MIN_DISTANCE_MM else "FAIL"
                        rows.append({
                            "comp": cap.comp_name,
                            "cmp_layer": cap_layer,
                            "part_name": cap.part_name or "",
                            "overlapping_con": conn.comp_name,
                            "distance": dist_str,
                            "status": status,
                        })
                else:
                    rows.append({
                        "comp": cap.comp_name,
                        "cmp_layer": cap_layer,
                        "part_name": cap.part_name or "",
                        "overlapping_con": "-",
                        "distance": "-",
                        "status": "PASS",
                    })

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"{fail_count} capacitor(s) too close to opposite-side connector."
                if not passed
                else "All managed capacitors meet the 1.5mm distance requirement."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
