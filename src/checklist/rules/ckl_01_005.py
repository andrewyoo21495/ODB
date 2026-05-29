"""CKL-01-005: Inductor (>=2012) vs AP/Memory overlap inspection.

For inductors of size 2012 or larger overlapping the opposite side of
AP or Memory components, review their corner placement and orientation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import find_ap_memory, find_inductors
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    filter_by_size,
    find_outline_boundary_pad_overlapping_components,
    find_outline_overlapping_components,
    get_component_orientation,
    is_on_edge,
)
from src.checklist.reference_loader import get_part_size_map
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import RuleResult


@register_rule
class CKL01005(ChecklistRule):
    rule_id = "CKL-01-005"
    description = (
        "반대면 AP/메모리와 중첩되는 2012 이상 인덕터: "
        "코너 배치 및 방향 검토"
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
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_01_005_"))

        for ap_comps, ap_layer, opp_comps in [
            (find_ap_memory(components_top), "Top", components_bot),
            (find_ap_memory(components_bot), "Bottom", components_top),
        ]:
            opp_inductors = find_inductors(opp_comps)
            if not opp_inductors:
                continue

            ap_is_bottom = (ap_layer == "Bottom")
            opp_is_bottom = not ap_is_bottom

            for ap in ap_comps:
                # Inductors whose pads cross the AP/Memory outline boundary
                boundary_hits = find_outline_boundary_pad_overlapping_components(
                    ap, opp_inductors, packages,
                    is_bottom_primary=ap_is_bottom,
                    is_bottom_candidates=opp_is_bottom,
                )
                # Filter to size >= 2012
                filtered = filter_by_size(boundary_hits, 2012, size_maps, packages)
                boundary_ids = {id(ind) for ind, _ in filtered}

                # Inductors overlapping footprint but NOT touching boundary
                # → shown as PASS in image only (not added to result rows)
                footprint_hits = find_outline_overlapping_components(
                    ap, opp_inductors, packages,
                    is_bottom_primary=ap_is_bottom,
                    is_bottom_candidates=opp_is_bottom,
                )
                fp_filtered = filter_by_size(footprint_hits, 2012, size_maps, packages)

                overlap_items: list[dict] = []

                # Image-only PASS items (footprint overlap, no boundary contact)
                for ind, sz in fp_filtered:
                    if id(ind) not in boundary_ids:
                        overlap_items.append({
                            "comp": ind, "status": "PASS",
                            "detail": "No outline contact",
                        })

                # Boundary-touching items → evaluate and add to result rows
                for ind, sz in filtered:
                    on_edge = is_on_edge(ind, ap, packages)
                    orientation = get_component_orientation(ind, packages)
                    edge_str = "TRUE" if on_edge else "FALSE"

                    if not on_edge and orientation == "Horizontal":
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
                    detail_parts = [orientation]
                    if on_edge:
                        detail_parts.append("Edge")
                    overlap_items.append({
                        "comp": ind, "status": status,
                        "detail": ", ".join(detail_parts),
                    })

                if overlap_items:
                    safe = ap.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{ap_layer}.png"
                    render_overlap_image(
                        ap, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="Inductor overlap",
                        layer_name=ap_layer,
                        primary_label="AP/Memory",
                        overlap_label="Inductor",
                    )
                    images.append({"path": img_path,
                                   "title": f"{ap.comp_name} ({ap_layer})",
                                   "width": 500})

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"AP/메모리 인근 인덕터 배치 문제가 {fail_count}건 발견되었습니다."
                if not passed
                else "AP/메모리 인근 모든 인덕터가 적절히 배치되어 있습니다."
            ),
            affected_components=[
                r["overlapping_ind"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
