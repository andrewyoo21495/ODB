"""CKL-02-008: 2S Inductors (>=2012) vs connectors and shield cans — edge/orientation check.

Verify placement and alignment between 2S Inductors (from
inductors_2s_list.csv) of size 2012 or larger and connectors / shield cans
on the opposite side.

Connector criteria (PASS when ALL true):
  - NOT on edge
  - Horizontal orientation

Shield Can criteria (PASS when ALL true):
  - NOT on corner/diagonal of the SC outline
  - Horizontal orientation relative to the nearest SC wall
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import (
    find_connectors, find_inductors, find_shield_cans,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    filter_by_size,
    find_pad_overlapping_components,
    get_orientation_relative_to_shield_can,
    get_pair_orientation,
    is_on_corner_or_diagonal,
    is_on_edge,
)
from src.checklist.reference_loader import (
    get_managed_part_names,
    get_part_size_map,
    matches_any_reference_part,
)
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import RuleResult


@register_rule
class CKL02008(ChecklistRule):
    rule_id = "CKL-02-008"
    description = (
        "반대면 커넥터 또는 쉴드캔과 중첩되는 2012 이상 2S 인덕터: "
        "엣지 및 방향 검사"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []
        user_symbols: dict = job_data.get("user_symbols") or {}

        ind_2s_parts = get_managed_part_names("inductors_2s_list")
        ind_size_map = get_part_size_map("inductors_2s_list")
        size_maps = [ind_size_map]

        columns = [
            "comp", "comp_type", "cmp_layer", "overlapping_ind", "part_name",
            "edge", "hori/verti", "status",
        ]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_02_008_"))

        for ref_comps, ref_layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            ref_is_bottom = (ref_layer == "Bottom")
            opp_is_bottom = not ref_is_bottom

            # 2S inductors on opposite side (partial match)
            opp_all_ind = find_inductors(opp_comps)
            opp_2s_ind = [
                c for c in opp_all_ind
                if matches_any_reference_part(c.part_name or "", ind_2s_parts)
            ]
            if not opp_2s_ind:
                continue

            # ── Connector check ───────────────────────────────────────────
            connectors = find_connectors(ref_comps)
            for conn in connectors:
                overlaps = find_pad_overlapping_components(
                    conn, opp_2s_ind, packages,
                    is_bottom_primary=ref_is_bottom,
                    is_bottom_candidates=opp_is_bottom,
                    user_symbols=user_symbols,
                )
                # Filter to size >= 2012
                filtered = filter_by_size(overlaps, 2012, size_maps, packages,
                                         desc_index=2)

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
                        "comp_type": "Connector",
                        "cmp_layer": ref_layer,
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
                    img_path = image_dir / f"{safe}_{ref_layer}.png"
                    render_overlap_image(
                        conn, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="2S inductor alignment (Connector)",
                        layer_name=ref_layer,
                        primary_label="Connector",
                        overlap_label="2S Inductor",
                        primary_is_bottom=ref_is_bottom,
                        overlap_is_bottom=opp_is_bottom,
                        user_symbols=user_symbols,
                    )
                    images.append({"path": img_path,
                                   "title": f"{conn.comp_name} ({ref_layer})",
                                   "width": 500})

            # ── Shield Can check ──────────────────────────────────────────
            shield_cans = find_shield_cans(ref_comps)
            for sc in shield_cans:
                overlaps = find_pad_overlapping_components(
                    sc, opp_2s_ind, packages,
                    is_bottom_primary=ref_is_bottom,
                    is_bottom_candidates=opp_is_bottom,
                    user_symbols=user_symbols,
                )
                filtered = filter_by_size(overlaps, 2012, size_maps, packages,
                                         desc_index=2)

                overlap_items = []
                for ind, sz in filtered:
                    on_diag = is_on_corner_or_diagonal(
                        ind, sc, packages,
                        cap_is_bottom=opp_is_bottom,
                        sc_is_bottom=ref_is_bottom,
                    )
                    orientation = get_orientation_relative_to_shield_can(
                        ind, sc, packages,
                        cap_is_bottom=opp_is_bottom,
                        sc_is_bottom=ref_is_bottom,
                    )
                    diag_str = "TRUE" if on_diag else "FALSE"
                    status = (
                        "PASS"
                        if (not on_diag and orientation == "Horizontal")
                        else "FAIL"
                    )
                    rows.append({
                        "comp": sc.comp_name,
                        "comp_type": "Shield_Can",
                        "cmp_layer": ref_layer,
                        "overlapping_ind": ind.comp_name,
                        "part_name": ind.part_name or "",
                        "edge": diag_str,
                        "hori/verti": orientation,
                        "status": status,
                    })
                    detail_parts = [orientation]
                    if on_diag:
                        detail_parts.append("Diagonal/Corner")
                    overlap_items.append({
                        "comp": ind, "status": status,
                        "detail": ", ".join(detail_parts),
                    })

                if overlap_items:
                    safe = sc.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{ref_layer}_sc.png"
                    render_overlap_image(
                        sc, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="2S inductor alignment (Shield Can)",
                        layer_name=ref_layer,
                        primary_label="Shield Can",
                        overlap_label="2S Inductor",
                        primary_is_bottom=ref_is_bottom,
                        overlap_is_bottom=opp_is_bottom,
                        user_symbols=user_symbols,
                    )
                    images.append({"path": img_path,
                                   "title": f"{sc.comp_name} ({ref_layer})",
                                   "width": 500})

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"커넥터/쉴드캔 인근 2S 인덕터 배치 문제가 {fail_count}건 발견되었습니다."
                if not passed
                else "커넥터 및 쉴드캔 인근 모든 2S 인덕터가 적절히 배치되어 있습니다."
            ),
            affected_components=[
                r["overlapping_ind"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
