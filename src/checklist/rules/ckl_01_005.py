"""CKL-01-005: Inductor (>=2012) vs AP/Memory overlap inspection.

For inductors of size 2012 or larger overlapping the opposite side of
AP or Memory components, review their corner placement and orientation.
"""

from __future__ import annotations

from src.checklist.component_classifier import find_inductors
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    filter_by_size,
    find_overlapping_components,
    get_component_orientation,
    is_on_edge,
    overlaps_component_outline,
)
from src.checklist.reference_loader import get_managed_part_names, get_part_size_map
from src.checklist.rule_base import ChecklistRule
from src.models import Component, RuleResult


def _find_ap_memory(components: list[Component]) -> list[Component]:
    """Return components whose part_name is listed in ap_memory.csv."""
    ap_parts = get_managed_part_names("ap_memory")
    return [c for c in components if (c.part_name or "") in ap_parts]


@register_rule
class CKL01005(ChecklistRule):
    rule_id = "CKL-01-005"
    description = (
        "Inductors >=2012 overlapping opposite side of AP/Memory: "
        "review corner placement and orientation"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        # Build size maps for inductors
        ind_size_map = get_part_size_map("inductors_2s_list")
        size_maps = [ind_size_map]

        columns = [
            "comp", "cmp_layer", "overlapping_ind", "part_name",
            "edge", "hori/verti", "status",
        ]
        rows: list[dict] = []

        for ap_comps, ap_layer, opp_comps in [
            (_find_ap_memory(components_top), "Top", components_bot),
            (_find_ap_memory(components_bot), "Bottom", components_top),
        ]:
            opp_inductors = find_inductors(opp_comps)
            if not opp_inductors:
                continue

            for ap in ap_comps:
                overlaps = find_overlapping_components(ap, opp_inductors, packages)
                # Filter to size >= 2012
                filtered = filter_by_size(overlaps, 2012, size_maps, packages)

                for ind, sz in filtered:
                    on_edge = is_on_edge(ind, ap, packages)
                    orientation = get_component_orientation(ind, packages)
                    edge_str = "TRUE" if on_edge else "FALSE"
                    hits_outline = overlaps_component_outline(ind, ap, packages)

                    # PASS if NOT on edge AND Horizontal
                    # Also PASS if Vertical but does NOT overlap the
                    # actual component outline of the AP/Memory
                    if not on_edge and orientation == "Horizontal":
                        status = "PASS"
                    elif orientation == "Vertical" and not hits_outline:
                        status = "PASS"
                    else:
                        status = "FAIL"

                    rows.append({
                        "comp": ap.comp_name,
                        "cmp_layer": ap_layer,
                        "overlapping_ind": ind.comp_name,
                        "part_name": ind.part_name or "",
                        "edge": edge_str,
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
                f"{fail_count} inductor placement issue(s) near AP/Memory."
                if not passed
                else "All inductors near AP/Memory are properly placed."
            ),
            affected_components=[
                r["overlapping_ind"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
