"""CKL-03-002: BGA-type ICs with no internal pads (empty centre).

Identify BGA-type IC components whose pad layout has an empty centre
(no balls/pads in the interior).  These components require resin filling
to ensure structural integrity during assembly.
"""

from __future__ import annotations

from src.checklist.component_classifier import find_bga_ics
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import has_empty_center
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


@register_rule
class CKL03002(ChecklistRule):
    rule_id = "CKL-03-002"
    description = (
        "BGA-type IC components with no internal pads require resin filling"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        packages = job_data.get("eda_data").packages if job_data.get("eda_data") else []

        columns = ["comp", "cmp_layer", "status", "comment"]
        rows: list[dict] = []

        for comps, layer_name in [
            (components_top, "Top"),
            (components_bot, "Bottom"),
        ]:
            bga_ics = find_bga_ics(comps, packages)

            for comp in bga_ics:
                empty = has_empty_center(comp, packages)
                status = "FAIL" if empty else "PASS"

                row = {
                    "comp": comp.comp_name,
                    "cmp_layer": layer_name,
                    "status": status,
                    "comment": "Resin filling required." if empty else "",
                }
                rows.append(row)

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"{fail_count} BGA IC(s) with empty centre detected."
                if not passed
                else "No BGA ICs with empty centre found."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
