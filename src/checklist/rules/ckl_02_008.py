"""CKL-02-008: 2S Inductors (>=2012) vs connectors — edge/orientation check.

Verify placement and alignment between 2S Inductors (from
inductors_2s_list.csv) of size 2012 or larger and connectors on the
opposite side.
"""

from __future__ import annotations

from src.checklist.component_classifier import find_connectors, find_inductors
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    filter_by_size,
    find_overlapping_components,
    get_component_orientation,
    is_on_edge,
)
from src.checklist.reference_loader import get_managed_part_names, get_part_size_map
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


@register_rule
class CKL02008(ChecklistRule):
    rule_id = "CKL-02-008"
    description = (
        "2S Inductors >=2012 overlapping connectors on the opposite side: "
        "edge and orientation check"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        ind_2s_parts = get_managed_part_names("inductors_2s_list")
        ind_size_map = get_part_size_map("inductors_2s_list")
        size_maps = [ind_size_map]

        columns = [
            "comp", "cmp_layer", "overlapping_ind", "part_name",
            "edge", "hori/verti", "status",
        ]
        rows: list[dict] = []

        for conn_comps, conn_layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            connectors = find_connectors(conn_comps)
            # 2S inductors on opposite side
            opp_all_ind = find_inductors(opp_comps)
            opp_2s_ind = [
                c for c in opp_all_ind
                if (c.part_name or "") in ind_2s_parts
            ]
            if not connectors or not opp_2s_ind:
                continue

            for conn in connectors:
                overlaps = find_overlapping_components(
                    conn, opp_2s_ind, packages
                )
                # Filter to size >= 2012
                filtered = filter_by_size(overlaps, 2012, size_maps, packages)

                for ind, sz in filtered:
                    on_edge = is_on_edge(ind, conn, packages)
                    orientation = get_component_orientation(ind, packages)
                    edge_str = "TRUE" if on_edge else "FALSE"
                    status = (
                        "PASS"
                        if (not on_edge and orientation == "Horizontal")
                        else "FAIL"
                    )
                    rows.append({
                        "comp": conn.comp_name,
                        "cmp_layer": conn_layer,
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
                f"{fail_count} 2S inductor placement issue(s) near connectors."
                if not passed
                else "All 2S inductors near connectors are properly placed."
            ),
            affected_components=[
                r["overlapping_ind"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
