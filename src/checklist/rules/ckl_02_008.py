"""CKL-02-008: 2S Inductors (>=2012) vs connectors — edge/orientation check.

Verify placement and alignment between 2S Inductors (from
inductors_2s_list.csv) of size 2012 or larger and connectors on the
opposite side.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import find_connectors, find_inductors
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    filter_by_size,
    find_pad_overlapping_components,
    get_pair_orientation,
    is_on_edge,
)
from src.checklist.reference_loader import get_managed_part_names, get_part_size_map
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import RuleResult


@register_rule
class CKL02008(ChecklistRule):
    rule_id = "CKL-02-008"
    description = (
        "반대면 커넥터와 중첩되는 2012 이상 2S 인덕터: "
        "엣지 및 방향 검사"
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
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_02_008_"))

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
                overlaps = find_pad_overlapping_components(
                    conn, opp_2s_ind, packages
                )
                # Filter to size >= 2012
                filtered = filter_by_size(overlaps, 2012, size_maps, packages)

                overlap_items: list[dict] = []
                for ind, sz in filtered:
                    on_edge = is_on_edge(ind, conn, packages)
                    orientation = get_pair_orientation(ind, conn, packages)
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
                    detail_parts = [orientation]
                    if on_edge:
                        detail_parts.append("Edge")
                    overlap_items.append({
                        "comp": ind, "status": status,
                        "detail": ", ".join(detail_parts),
                    })

                if overlap_items:
                    safe = conn.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{conn_layer}.png"
                    render_overlap_image(
                        conn, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="2S inductor alignment",
                        layer_name=conn_layer,
                        primary_label="Connector",
                        overlap_label="2S Inductor",
                    )
                    images.append({"path": img_path,
                                   "title": f"{conn.comp_name} ({conn_layer})",
                                   "width": 500})

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"커넥터 인근 2S 인덕터 배치 문제가 {fail_count}건 발견되었습니다."
                if not passed
                else "커넥터 인근 모든 2S 인덕터가 적절히 배치되어 있습니다."
            ),
            affected_components=[
                r["overlapping_ind"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
