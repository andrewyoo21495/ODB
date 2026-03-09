"""CKL-01-001: IC vs interposer/connector overlap on opposite side.

ICs must be placed so they do not overlap with interposers or connectors
on the opposite side of the PCB.
"""

from __future__ import annotations

from src.checklist.component_classifier import (
    find_connectors, find_ics, find_interposers,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import find_overlapping_components
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


@register_rule
class CKL01001(ChecklistRule):
    rule_id = "CKL-01-001"
    description = (
        "ICs must not overlap with interposers or connectors on the opposite side"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        columns = ["comp", "cmp_layer", "overlapping_cmp", "status"]
        rows: list[dict] = []

        # Check ICs on both layers against interposers/connectors on opposite
        for ics, ic_layer, opp_comps in [
            (find_ics(components_top), "Top", components_bot),
            (find_ics(components_bot), "Bottom", components_top),
        ]:
            # Candidates on the opposite side: interposers + connectors
            opp_targets = find_interposers(opp_comps) + find_connectors(opp_comps)
            if not opp_targets:
                continue

            for ic in ics:
                overlaps = find_overlapping_components(ic, opp_targets, packages)
                if overlaps:
                    for ovl in overlaps:
                        rows.append({
                            "comp": ic.comp_name,
                            "cmp_layer": ic_layer,
                            "overlapping_cmp": ovl.comp_name,
                            "status": "FAIL",
                        })
                else:
                    rows.append({
                        "comp": ic.comp_name,
                        "cmp_layer": ic_layer,
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
                f"{fail_count} IC-interposer/connector overlap(s) found."
                if not passed
                else "No IC-interposer/connector overlaps detected."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
