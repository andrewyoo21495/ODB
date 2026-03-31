"""CKL-01-004: Antenna C-Clip pad vs SIM socket pad overlap check.

Do not design C-Clip pads (ANT components) to overlap on the opposite
side of SIM socket pads.  For each SIM socket, antenna components on the
opposite layer are checked for pad-to-pad overlap.  Any overlap is FAIL.
"""

from __future__ import annotations

from src.checklist.component_classifier import find_antennas, find_simsockets
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import find_pad_overlapping_components
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


@register_rule
class CKL01004(ChecklistRule):
    rule_id = "CKL-01-004"
    description = (
        "Antenna (ANT) C-Clip pads must not overlap with SIM socket pads "
        "on the opposite side"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        columns = ["comp", "cmp_layer", "overlapping_cmp", "status"]
        rows: list[dict] = []

        for sim_comps, layer_name, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            simsockets = find_simsockets(sim_comps)
            opp_antennas = find_antennas(opp_comps)

            if not simsockets or not opp_antennas:
                continue

            for sim in simsockets:
                if sim.pkg_ref < 0 or sim.pkg_ref >= len(packages):
                    continue

                overlapping = find_pad_overlapping_components(
                    sim, opp_antennas, packages,
                )

                if overlapping:
                    for ant in overlapping:
                        rows.append({
                            "comp": sim.comp_name,
                            "cmp_layer": layer_name,
                            "overlapping_cmp": ant.comp_name,
                            "status": "FAIL",
                        })
                else:
                    rows.append({
                        "comp": sim.comp_name,
                        "cmp_layer": layer_name,
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
                f"{fail_count} antenna component(s) with C-Clip pads "
                f"overlapping SIM socket pads detected."
                if not passed
                else "No antenna C-Clip pad overlaps with SIM socket pads."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
