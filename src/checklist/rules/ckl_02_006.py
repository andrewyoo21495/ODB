"""CKL-02-006: General capacitors vs connectors — edge/orientation check.

Identify general capacitors (NOT in the 51 managed types) overlapping
connectors on the opposite side.  Check edge placement and orientation.
"""

from __future__ import annotations

from src.checklist.component_classifier import find_capacitors, find_connectors
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    find_overlapping_components,
    get_component_orientation,
    is_on_edge,
)
from src.checklist.reference_loader import get_managed_part_names
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


def _get_51_managed_part_names() -> set[str]:
    """Combine capacitors_41_list + capacitors_10_list into 51 managed types."""
    parts_41 = get_managed_part_names("capacitors_41_list")
    parts_10 = get_managed_part_names("capacitors_10_list")
    return parts_41 | parts_10


@register_rule
class CKL02006(ChecklistRule):
    rule_id = "CKL-02-006"
    description = (
        "General capacitors (not in 51 managed types) overlapping "
        "connectors on the opposite side: edge and orientation check"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        managed_51 = _get_51_managed_part_names()

        columns = [
            "comp", "cmp_layer", "overlapping_cap", "part_name",
            "edge", "hori/verti", "status",
        ]
        rows: list[dict] = []

        for conn_comps, conn_layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            connectors = find_connectors(conn_comps)
            opp_all_caps = find_capacitors(opp_comps)
            # General capacitors = not in managed 51
            opp_general_caps = [
                c for c in opp_all_caps
                if (c.part_name or "") not in managed_51
            ]
            if not connectors or not opp_general_caps:
                continue

            for conn in connectors:
                overlaps = find_overlapping_components(
                    conn, opp_general_caps, packages
                )
                for cap in overlaps:
                    on_edge = is_on_edge(cap, conn, packages)
                    orientation = get_component_orientation(cap, packages)
                    edge_str = "TRUE" if on_edge else "FALSE"
                    status = (
                        "PASS"
                        if (not on_edge and orientation == "Horizontal")
                        else "FAIL"
                    )
                    rows.append({
                        "comp": conn.comp_name,
                        "cmp_layer": conn_layer,
                        "overlapping_cap": cap.comp_name,
                        "part_name": cap.part_name or "",
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
                f"{fail_count} general capacitor placement issue(s) near connectors."
                if not passed
                else "All general capacitors near connectors are properly placed."
            ),
            affected_components=[
                r["overlapping_cap"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
