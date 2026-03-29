"""CKL-02-002: Managed capacitors (41 types) vs connectors — alignment check.

Verify placement between specific capacitor components (41 managed types)
and connector components.  Managed capacitors overlapping on the opposite
side of a connector must be aligned horizontally.
"""

from __future__ import annotations

from src.checklist.component_classifier import find_connectors
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    find_overlapping_components,
    get_pair_orientation,
    is_on_edge,
)
from src.checklist.reference_loader import get_managed_part_names
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


@register_rule
class CKL02002(ChecklistRule):
    rule_id = "CKL-02-002"
    description = (
        "Managed capacitors (41 types) overlapping connectors on the "
        "opposite side must be aligned horizontally"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        managed_41 = get_managed_part_names("capacitors_41_list")

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
            # Filter opposite-side capacitors to managed 41 types
            opp_managed_caps = [
                c for c in opp_comps
                if (c.part_name or "") in managed_41
            ]
            if not connectors or not opp_managed_caps:
                continue

            for conn in connectors:
                overlaps = find_overlapping_components(
                    conn, opp_managed_caps, packages
                )
                for cap in overlaps:
                    on_edge = is_on_edge(cap, conn, packages)
                    orientation = get_pair_orientation(cap, conn, packages)
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
                f"{fail_count} managed capacitor(s) not horizontally aligned "
                f"with opposite-side connector."
                if not passed
                else "All managed capacitors near connectors are horizontally aligned."
            ),
            affected_components=[
                r["overlapping_cap"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
