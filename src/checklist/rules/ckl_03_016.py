"""CKL-03-016: No INP/SC/SIM/Connector on the opposite side of OSC.

Interposers, Shield Cans, SIM Sockets, and Connectors must not be placed
on the opposite side of Oscillator components (overlapping).
"""

from __future__ import annotations

from src.checklist.component_classifier import (
    find_connectors,
    find_interposers,
    find_oscillators,
    find_shield_cans,
    find_simsockets,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import find_overlapping_components
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


@register_rule
class CKL03016(ChecklistRule):
    rule_id = "CKL-03-016"
    description = (
        "Interposers, Shield Cans, SIM Sockets, and Connectors must not "
        "overlap the opposite side of OSC components"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        columns = ["comp", "cmp_layer", "overlapping_cmp", "part_name", "status"]
        rows: list[dict] = []

        for oscs, osc_layer, opp_comps in [
            (find_oscillators(components_top), "Top", components_bot),
            (find_oscillators(components_bot), "Bottom", components_top),
        ]:
            opp_interposers = find_interposers(opp_comps)
            opp_shield_cans = find_shield_cans(opp_comps)
            opp_simsockets = find_simsockets(opp_comps)
            opp_connectors = find_connectors(opp_comps)
            opp_targets = (
                opp_interposers + opp_shield_cans
                + opp_simsockets + opp_connectors
            )

            if not opp_targets:
                for osc in oscs:
                    rows.append({
                        "comp": osc.comp_name,
                        "cmp_layer": osc_layer,
                        "overlapping_cmp": "-",
                        "part_name": "-",
                        "status": "PASS",
                    })
                continue

            for osc in oscs:
                overlaps = find_overlapping_components(osc, opp_targets, packages)

                if overlaps:
                    for ovl in overlaps:
                        rows.append({
                            "comp": osc.comp_name,
                            "cmp_layer": osc_layer,
                            "overlapping_cmp": ovl.comp_name,
                            "part_name": ovl.part_name or "",
                            "status": "FAIL",
                        })
                else:
                    rows.append({
                        "comp": osc.comp_name,
                        "cmp_layer": osc_layer,
                        "overlapping_cmp": "-",
                        "part_name": "-",
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
                f"{fail_count} component(s) overlapping the opposite side of OSC."
                if not passed
                else "No prohibited components overlap the opposite side of OSC."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
