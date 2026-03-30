"""CKL-02-010: SIM socket vs capacitors/inductors (>=2012) on opposite side.

Inspect capacitors and inductors of size 2012 or larger that overlap the
component outline of SIM sockets on the opposite side.  Check orientation
relative to the specific SIM socket outline edge being overlapped.
"""

from __future__ import annotations

from src.checklist.component_classifier import (
    find_capacitors, find_inductors, find_simsockets,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    filter_by_size,
    get_orientation_relative_to_edge,
    overlaps_component_outline,
)
from src.checklist.reference_loader import get_part_size_map
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


@register_rule
class CKL02010(ChecklistRule):
    rule_id = "CKL-02-010"
    description = (
        "SIM sockets: capacitors/inductors >=2012 overlapping the SIM "
        "outline on the opposite side must be aligned with the overlapped edge"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        # Build size maps from reference CSVs
        cap_size_map = get_part_size_map("capacitors_10_list")
        ind_size_map = get_part_size_map("inductors_2s_list")
        size_maps = [cap_size_map, ind_size_map]

        columns = [
            "comp", "cmp_layer", "overlapping_cmp", "part_name",
            "hori/verti", "status",
        ]
        rows: list[dict] = []

        for sim_comps, sim_layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            sims = find_simsockets(sim_comps)
            opp_caps = find_capacitors(opp_comps)
            opp_inds = find_inductors(opp_comps)
            opp_targets = opp_caps + opp_inds

            if not sims or not opp_targets:
                continue

            # Filter to size >= 2012
            filtered = filter_by_size(opp_targets, 2012, size_maps, packages)

            for sim in sims:
                for comp, sz in filtered:
                    # Only check components overlapping the SIM outline
                    if not overlaps_component_outline(comp, sim, packages):
                        continue

                    orientation = get_orientation_relative_to_edge(
                        comp, sim, packages,
                    )
                    status = "PASS" if orientation == "Horizontal" else "FAIL"
                    rows.append({
                        "comp": sim.comp_name,
                        "cmp_layer": sim_layer,
                        "overlapping_cmp": comp.comp_name,
                        "part_name": comp.part_name or "",
                        "hori/verti": orientation,
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
                f"{fail_count} component(s) near SIM socket not aligned with outline edge."
                if not passed
                else "All components near SIM sockets are properly oriented."
            ),
            affected_components=[
                r["overlapping_cmp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
