"""CKL-02-002: Managed capacitors (41 types) vs connectors — alignment check.

Verify placement between specific capacitor components (41 managed types)
and connector components.  Managed capacitors overlapping on the opposite
side of a connector must be aligned horizontally.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import find_connectors
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    find_components_inside_outline,
    find_pad_overlapping_components,
    get_pair_orientation,
    is_on_edge,
)
from src.checklist.reference_loader import get_managed_part_names
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
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
        user_symbols: dict = job_data.get("user_symbols") or {}

        managed_41 = get_managed_part_names("capacitors_41_list")

        columns = [
            "comp", "cmp_layer", "overlapping_cap", "part_name",
            "edge", "hori/verti", "status",
        ]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_02_002_"))

        for conn_comps, conn_layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            conn_is_bottom = (conn_layer == "Bottom")
            cap_is_bottom = not conn_is_bottom

            connectors = find_connectors(conn_comps)
            # Filter opposite-side capacitors to managed 41 types
            opp_managed_caps = [
                c for c in opp_comps
                if (c.part_name or "") in managed_41
            ]
            if not connectors or not opp_managed_caps:
                continue

            for conn in connectors:
                overlaps = find_pad_overlapping_components(
                    conn, opp_managed_caps, packages,
                    is_bottom_primary=conn_is_bottom,
                    is_bottom_candidates=cap_is_bottom,
                    user_symbols=user_symbols,
                )
                # Caps inside connector outline but not pad-overlapping
                inside_caps = find_components_inside_outline(
                    conn, opp_managed_caps, packages,
                    is_bottom=conn_is_bottom,
                )
                inside_only = [
                    c for c in inside_caps
                    if c not in overlaps
                ]

                overlap_items: list[dict] = []

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
                    detail_parts = [orientation]
                    if on_edge:
                        detail_parts.append("Edge")
                    overlap_items.append({
                        "comp": cap,
                        "status": status,
                        "detail": ", ".join(detail_parts),
                    })

                for cap in inside_only:
                    orientation = get_pair_orientation(cap, conn, packages)
                    status = "FAIL" if orientation == "Vertical" else "PASS"
                    rows.append({
                        "comp": conn.comp_name,
                        "cmp_layer": conn_layer,
                        "overlapping_cap": cap.comp_name,
                        "part_name": cap.part_name or "",
                        "edge": "FALSE",
                        "hori/verti": orientation,
                        "status": status,
                    })
                    overlap_items.append({
                        "comp": cap,
                        "status": status,
                        "detail": orientation,
                    })

                # Generate visualisation image for this connector
                if overlap_items:
                    safe_name = conn.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe_name}_{conn_layer}.png"
                    render_overlap_image(
                        conn, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="Managed capacitor alignment",
                        layer_name=conn_layer,
                        primary_label="Connector",
                        overlap_label="Managed cap",
                        primary_is_bottom=conn_is_bottom,
                        overlap_is_bottom=cap_is_bottom,
                        user_symbols=user_symbols,
                    )
                    images.append({
                        "path": img_path,
                        "title": f"{conn.comp_name} ({conn_layer})",
                        "width": 500,
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
            details={"columns": columns,
                     "rows": [r for r in rows if r["status"] == "FAIL"]},
            images=images,
        )
