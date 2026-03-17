"""CKL-01-006: RF Receptacle pad vs 5-pin filter pad overlap on opposite layer.

Verify that RF Receptacle pads do not overlap with 5-pin filter pads on the
opposite layer of the PCB.
"""

from __future__ import annotations

from src.checklist.component_classifier import find_filters, find_rf_components
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import find_pad_overlapping_components
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


@register_rule
class CKL01006(ChecklistRule):
    rule_id = "CKL-01-006"
    description = (
        "RF Receptacle pads must not overlap with 5-pin filter pads "
        "on the opposite layer"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        columns = ["comp", "cmp_layer", "overlapping_cmp", "status"]
        rows: list[dict] = []

        for rf_comps, rf_layer, opp_comps in [
            (find_rf_components(components_top), "Top", components_bot),
            (find_rf_components(components_bot), "Bottom", components_top),
        ]:
            opp_filters = find_filters(opp_comps, packages, pin_count=5)
            if not opp_filters:
                for rf in rf_comps:
                    rows.append({
                        "comp": rf.comp_name,
                        "cmp_layer": rf_layer,
                        "overlapping_cmp": "-",
                        "status": "PASS",
                    })
                continue

            for rf in rf_comps:
                pad_overlaps = find_pad_overlapping_components(
                    rf, opp_filters, packages,
                )

                if pad_overlaps:
                    for ovl in pad_overlaps:
                        rows.append({
                            "comp": rf.comp_name,
                            "cmp_layer": rf_layer,
                            "overlapping_cmp": ovl.comp_name,
                            "status": "FAIL",
                        })
                else:
                    rows.append({
                        "comp": rf.comp_name,
                        "cmp_layer": rf_layer,
                        "overlapping_cmp": "-",
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
                f"{fail_count} RF Receptacle pad overlap(s) with opposite-layer "
                f"5-pin filter pad(s) found."
                if not passed
                else "No RF Receptacle pad overlaps with opposite-layer 5-pin filters."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
