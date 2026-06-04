"""CKL-02-002: Managed capacitors (41 types) vs connectors — alignment check.

Verify placement between specific capacitor components (41 managed types)
and connector components on the opposite side.

Decision logic for each capacitor:
  1. No overlap with connector outline AND no PAD-PAD overlap → PASS
  2. No outline overlap but PAD-PAD overlap (cap inside connector) →
     check hori/verti vs connector; Horizontal → PASS, Vertical → FAIL
  3. Outline overlap + PAD-PAD overlap → check hori/verti vs the nearest
     outline edge; Vertical → FAIL.  Also FAIL if on connector's short edge.
  4. Outline overlap but no PAD-PAD overlap → cap is on the connector
     boundary; check if on short edge → FAIL.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import find_connectors
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    find_pad_overlapping_components,
    get_pair_orientation,
    does_pad_overlap_outline,
    get_nearest_outline_edge_angle,
    is_on_outline_edge,
)
from src.checklist.geometry_utils.orientation import (
    get_major_axis_angle,
    get_pair_orientation_vs_edge,
)
from src.checklist.reference_loader import get_managed_part_names
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import RuleResult


def _orientation_vs_edge(cap, conn, packages, cap_is_bottom, conn_is_bottom):
    """Determine cap orientation relative to the nearest connector outline edge."""
    edge_angle = get_nearest_outline_edge_angle(
        cap, conn, packages,
        is_bottom_a=cap_is_bottom, is_bottom_b=conn_is_bottom,
    )
    if edge_angle is not None:
        return get_pair_orientation_vs_edge(
            cap, conn, packages, edge_angle=edge_angle,
        )
    return get_pair_orientation(cap, conn, packages)


@register_rule
class CKL02002(ChecklistRule):
    rule_id = "CKL-02-002"
    description = (
        "41종 관리 캐패시터가 반대면 커넥터와 중첩될 경우 "
        "수평으로 정렬되어야 합니다"
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
            "overlapping_cap", "part_name", "comp", "cmp_layer",
            "outline_overlap", "pad_overlap", "edge", "hori/verti", "status",
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
            opp_managed_caps = [
                c for c in opp_comps
                if (c.part_name or "") in managed_41
            ]
            if not connectors or not opp_managed_caps:
                continue

            for conn in connectors:
                # Find caps with PAD-PAD overlap.
                # Use min_overlap_area to avoid false positives from
                # boundary-only touches (pads barely touching edges).
                pad_overlaps = find_pad_overlapping_components(
                    conn, opp_managed_caps, packages,
                    is_bottom_primary=conn_is_bottom,
                    is_bottom_candidates=cap_is_bottom,
                    user_symbols=user_symbols,
                    min_overlap_area=0.001,
                )
                pad_overlap_ids = {id(c) for c in pad_overlaps}

                overlap_items: list[dict] = []

                for cap in opp_managed_caps:
                    has_pad_overlap = id(cap) in pad_overlap_ids
                    has_outline_overlap = does_pad_overlap_outline(
                        cap, conn, packages,
                        is_bottom_a=cap_is_bottom,
                        is_bottom_b=conn_is_bottom,
                        user_symbols=user_symbols,
                    )

                    if not has_outline_overlap and not has_pad_overlap:
                        # Case 1: no overlap at all → PASS (skip)
                        continue

                    if not has_outline_overlap and has_pad_overlap:
                        # Case 2: inside connector, no outline contact
                        orientation = get_pair_orientation(
                            cap, conn, packages)
                        status = ("PASS" if orientation == "Horizontal"
                                  else "FAIL")
                        edge_str = "FALSE"
                    elif has_outline_overlap and has_pad_overlap:
                        # Case 3: overlaps outline AND pad
                        on_edge = is_on_outline_edge(
                            cap, conn, packages,
                            is_bottom_a=cap_is_bottom,
                            is_bottom_b=conn_is_bottom,
                        )
                        orientation = _orientation_vs_edge(
                            cap, conn, packages,
                            cap_is_bottom, conn_is_bottom,
                        )
                        edge_str = "TRUE" if on_edge else "FALSE"
                        if on_edge:
                            status = "FAIL"
                        elif orientation == "Vertical":
                            status = "FAIL"
                        else:
                            status = "PASS"
                    else:
                        # Case 4: outline overlap but no pad overlap
                        # → cap sits on connector boundary
                        on_edge = is_on_outline_edge(
                            cap, conn, packages,
                            is_bottom_a=cap_is_bottom,
                            is_bottom_b=conn_is_bottom,
                        )
                        orientation = _orientation_vs_edge(
                            cap, conn, packages,
                            cap_is_bottom, conn_is_bottom,
                        )
                        edge_str = "TRUE" if on_edge else "FALSE"
                        if on_edge:
                            status = "FAIL"
                        elif orientation == "Vertical":
                            status = "FAIL"
                        else:
                            status = "PASS"

                    rows.append({
                        "comp": conn.comp_name,
                        "cmp_layer": conn_layer,
                        "overlapping_cap": cap.comp_name,
                        "part_name": cap.part_name or "",
                        "outline_overlap": "TRUE" if has_outline_overlap else "FALSE",
                        "pad_overlap": "TRUE" if has_pad_overlap else "FALSE",
                        "edge": edge_str,
                        "hori/verti": orientation,
                        "status": status,
                    })
                    detail_parts = [orientation]
                    if edge_str == "TRUE":
                        detail_parts.append("Edge")
                    overlap_items.append({
                        "comp": cap,
                        "status": status,
                        "detail": ", ".join(detail_parts),
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
                f"반대면 커넥터와 수평 정렬되지 않은 관리 캐패시터가 "
                f"{fail_count}건 발견되었습니다."
                if not passed
                else "커넥터 인근 모든 관리 캐패시터가 수평으로 정렬되어 있습니다."
            ),
            affected_components=[
                r["overlapping_cap"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns,
                     "rows": [r for r in rows if r["status"] == "FAIL"]},
            images=images,
        )
