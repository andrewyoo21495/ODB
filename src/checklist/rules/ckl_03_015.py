"""CKL-03-015: PCB outline clearance check.

Components and routing must be placed with a clearance of at least
0.65mm from the inner PCB outline.
"""

from __future__ import annotations

from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    build_board_polygon,
    build_inset_boundary,
    components_in_clearance_zone,
)
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


_CLEARANCE_MM = 0.65


@register_rule
class CKL03015(ChecklistRule):
    rule_id = "CKL-03-015"
    description = (
        "Components must have at least 0.65mm clearance from the PCB outline"
    )
    category = "Clearance"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        profile = job_data.get("profile")
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        board_poly = build_board_polygon(profile)
        if board_poly is None:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                category=self.category,
                passed=True,
                message="No board profile available for clearance check.",
            )

        inset_poly = build_inset_boundary(board_poly, _CLEARANCE_MM)
        if inset_poly is None:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                category=self.category,
                passed=True,
                message="Could not generate inset boundary for clearance check.",
            )

        columns = ["comp", "part_name", "cmp_layer", "distance", "status"]
        rows: list[dict] = []

        for comps, layer_name in [
            (components_top, "Top"),
            (components_bot, "Bottom"),
        ]:
            violations = components_in_clearance_zone(
                comps, board_poly, inset_poly, packages
            )
            for comp, dist in violations:
                status = "PASS" if dist >= _CLEARANCE_MM else "FAIL"
                rows.append({
                    "comp": comp.comp_name,
                    "part_name": comp.part_name or "",
                    "cmp_layer": layer_name,
                    "distance": f"{dist:.3f}",
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
                f"{fail_count} component(s) within {_CLEARANCE_MM}mm of PCB outline."
                if not passed
                else f"All components meet the {_CLEARANCE_MM}mm clearance requirement."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
