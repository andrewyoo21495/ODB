"""CKL-02-001: Managed capacitors vs connectors/interposers/shield cans — distance check.

Verify placement and distance between 10 managed capacitor types and
connector, interposer, and shield can components on the opposite side.
Distance must be >= 1.5mm.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import (
    find_connectors,
    find_interposers,
    find_shield_cans,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    find_overlapping_components,
    pad_to_pad_distance,
)
from src.checklist.reference_loader import get_managed_part_names
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import Component, RuleResult


_MIN_DISTANCE_MM = 1.5


@register_rule
class CKL02001(ChecklistRule):
    rule_id = "CKL-02-001"
    description = (
        "10종 관리 캐패시터는 반대면 커넥터, 인터포저, "
        "쉴드캔과 최소 1.5mm 이격되어야 합니다"
    )
    category = "Spacing"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []
        user_symbols: dict = job_data.get("user_symbols") or {}

        managed_parts = get_managed_part_names("capacitors_10_list")

        columns = [
            "comp", "cmp_layer", "part_name",
            "overlapping_cmp", "opp_type", "distance", "status",
        ]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_02_001_"))

        for caps_layer_comps, cap_layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            cap_is_bottom = (cap_layer == "Bottom")
            opp_is_bottom = not cap_is_bottom

            # Filter to managed capacitors
            managed_caps = [
                c for c in caps_layer_comps
                if (c.part_name or "") in managed_parts
            ]

            # Collect opposite-side targets: connectors, interposers, shield cans
            opp_targets: list[tuple[Component, str]] = [
                (c, "Connector") for c in find_connectors(opp_comps)
            ] + [
                (c, "Interposer") for c in find_interposers(opp_comps)
            ] + [
                (c, "Shield Can") for c in find_shield_cans(opp_comps)
            ]

            if not managed_caps or not opp_targets:
                continue

            opp_all = [c for c, _ in opp_targets]
            opp_type_map = {id(c): t for c, t in opp_targets}

            for cap in managed_caps:
                # Use footprint overlap to find spatially nearby candidates first
                overlaps = find_overlapping_components(
                    cap, opp_all, packages,
                    is_bottom_primary=cap_is_bottom,
                    is_bottom_candidates=opp_is_bottom,
                )
                overlap_items: list[dict] = []
                if overlaps:
                    for opp in overlaps:
                        # Measure actual pad-to-pad distance (not footprint distance,
                        # which returns 0 when SC footprint covers the cap area)
                        dist = pad_to_pad_distance(
                            cap, opp, packages,
                            is_bottom_a=cap_is_bottom,
                            is_bottom_b=opp_is_bottom,
                            user_symbols=user_symbols,
                        )
                        dist_str = f"{dist:.3f}" if dist < float("inf") else "N/A"
                        status = "PASS" if dist >= _MIN_DISTANCE_MM else "FAIL"
                        opp_type = opp_type_map.get(id(opp), "Unknown")
                        rows.append({
                            "comp": cap.comp_name,
                            "cmp_layer": cap_layer,
                            "part_name": cap.part_name or "",
                            "overlapping_cmp": opp.comp_name,
                            "opp_type": opp_type,
                            "distance": dist_str,
                            "status": status,
                        })
                        overlap_items.append({
                            "comp": opp, "status": status,
                            "distance": dist if dist < float("inf") else None,
                            "min_distance": _MIN_DISTANCE_MM,
                        })
                else:
                    rows.append({
                        "comp": cap.comp_name,
                        "cmp_layer": cap_layer,
                        "part_name": cap.part_name or "",
                        "overlapping_cmp": "-",
                        "opp_type": "-",
                        "distance": "-",
                        "status": "PASS",
                    })

                if overlap_items:
                    safe = cap.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{cap_layer}.png"
                    render_overlap_image(
                        cap, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="Capacitor clearance (connector/interposer/shield can)",
                        layer_name=cap_layer,
                        primary_label="Capacitor",
                        overlap_label="Opp. Component",
                        primary_is_bottom=cap_is_bottom,
                        overlap_is_bottom=opp_is_bottom,
                        user_symbols=user_symbols,
                    )
                    images.append({"path": img_path,
                                   "title": f"{cap.comp_name} ({cap_layer})",
                                   "width": 500})

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"반대면 커넥터/인터포저/쉴드캔과 너무 가까운 캐패시터가 "
                f"{fail_count}건 발견되었습니다."
                if not passed
                else "모든 관리 캐패시터가 1.5mm 이격 요건을 충족합니다."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
