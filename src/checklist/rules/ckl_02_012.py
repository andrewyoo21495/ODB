"""CKL-02-012: Inductors >=2012 overlapping AP/Memory and Shield Can.

Inductors of size 2012 or larger that overlap with both a Shield Can and
an AP/Memory component on opposite sides must be avoided.
"""

from __future__ import annotations

from src.checklist.component_classifier import (
    find_inductors,
    find_shield_cans,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    filter_by_size,
    find_pad_overlapping_components,
)
from src.checklist.reference_loader import get_managed_part_names, get_part_size_map
from src.checklist.rule_base import ChecklistRule
from src.models import Component, RuleResult


def _find_ap_memory(components: list[Component]) -> list[Component]:
    """Return components whose part_name is listed in ap_memory.csv."""
    ap_parts = get_managed_part_names("ap_memory")
    return [c for c in components if (c.part_name or "") in ap_parts]


@register_rule
class CKL02012(ChecklistRule):
    rule_id = "CKL-02-012"
    description = (
        "Inductors >=2012 overlapping both AP/Memory and Shield Can "
        "on opposite sides must be avoided"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        ind_size_map = get_part_size_map("inductors_2s_list")
        size_maps = [ind_size_map]

        columns = [
            "comp", "cmp_layer", "part_name", "overlapping_ap", "status",
        ]
        rows: list[dict] = []

        for ap_layer_comps, ap_layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            ap_comps = _find_ap_memory(ap_layer_comps)
            if not ap_comps:
                continue

            # Find inductors on the opposite side
            opp_inductors = find_inductors(opp_comps)
            if not opp_inductors:
                continue

            for ap in ap_comps:
                # Find inductors overlapping opposite side of AP/Memory
                overlapping_inds = find_pad_overlapping_components(
                    ap, opp_inductors, packages
                )
                # Filter to size >= 2012
                filtered = filter_by_size(
                    overlapping_inds, 2012, size_maps, packages
                )

                for ind, sz in filtered:
                    # Check if a Shield Can also overlaps on the opposite
                    # side of this inductor (i.e. same side as the AP/Memory)
                    same_side_shield_cans = find_shield_cans(ap_layer_comps)
                    sc_overlaps = find_pad_overlapping_components(
                        ind, same_side_shield_cans, packages
                    )

                    if sc_overlaps:
                        rows.append({
                            "comp": ind.comp_name,
                            "cmp_layer": "Bottom" if ap_layer == "Top" else "Top",
                            "part_name": ind.part_name or "",
                            "overlapping_ap": ap.comp_name,
                            "status": "FAIL",
                        })

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"{fail_count} inductor(s) overlap both AP/Memory and Shield Can."
                if not passed
                else "No inductors >=2012 overlap both AP/Memory and Shield Can."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
