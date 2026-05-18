"""CKL-02-009: General Inductors (>=2012) vs connectors/shield cans — edge/orientation/avoidance check.

Verify placement between General Inductors (those NOT in
inductors_2s_list.csv) of size 2012 or larger and:
  1. Connectors on the opposite side (edge/orientation check).
  2. Shield Cans on the opposite side (avoidance — any overlap is FAIL).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import (
    find_connectors,
    find_inductors,
    find_shield_cans,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    filter_by_size,
    find_pad_overlapping_components,
    get_component_orientation,
    is_on_edge,
)
from src.checklist.reference_loader import get_managed_part_names, get_part_size_map
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import RuleResult


@register_rule
class CKL02009(ChecklistRule):
    rule_id = "CKL-02-009"
    description = (
        "2012 이상 일반 인덕터(2S 제외): 반대면 커넥터 대비 엣지/방향 검사, "
        "반대면 쉴드캔 대비 회피 검사"
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
            "check_type", "comp", "cmp_layer", "overlapping_ind", "part_name",
            "edge", "hori/verti", "status",
        ]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_02_009_"))

        # ── 1. Connector check (edge / orientation) ──────────────────────────
        for conn_comps, conn_layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            connectors = find_connectors(conn_comps)
            opp_all_ind = find_inductors(opp_comps)
            opp_general_ind = [
                c for c in opp_all_ind
                if (c.part_name or "") not in ind_2s_parts
            ]
            if not connectors or not opp_general_ind:
                continue

            for conn in connectors:
                overlaps = find_pad_overlapping_components(
                    conn, opp_general_ind, packages,
                    user_symbols=user_symbols,
                )
                filtered = filter_by_size(overlaps, 2012, size_maps, packages)

                overlap_items: list[dict] = []
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
                        "check_type": "Connector",
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
                    img_path = image_dir / f"{safe}_{conn_layer}_conn.png"
                    render_overlap_image(
                        conn, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="General inductor alignment (connector)",
                        layer_name=conn_layer,
                        primary_label="Connector",
                        overlap_label="General Inductor",
                        user_symbols=user_symbols,
                    )
                    images.append({"path": img_path,
                                   "title": f"{conn.comp_name} ({conn_layer}) – Connector",
                                   "width": 500})

        # ── 2. Shield Can avoidance check ─────────────────────────────────────
        for sc_comps, sc_layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            sc_is_bottom = (sc_layer == "Bottom")
            ind_is_bottom = not sc_is_bottom

            shield_cans = find_shield_cans(sc_comps)
            opp_all_ind = find_inductors(opp_comps)
            opp_general_ind = [
                c for c in opp_all_ind
                if (c.part_name or "") not in ind_2s_parts
            ]
            if not shield_cans or not opp_general_ind:
                continue

            for sc in shield_cans:
                overlaps = find_pad_overlapping_components(
                    sc, opp_general_ind, packages,
                    is_bottom_primary=sc_is_bottom,
                    is_bottom_candidates=ind_is_bottom,
                    user_symbols=user_symbols,
                )
                filtered = filter_by_size(overlaps, 2012, size_maps, packages)

                overlap_items: list[dict] = []
                for ind, sz in filtered:
                    rows.append({
                        "check_type": "Shield Can",
                        "comp": sc.comp_name,
                        "cmp_layer": sc_layer,
                        "overlapping_ind": ind.comp_name,
                        "part_name": ind.part_name or "",
                        "edge": "-",
                        "hori/verti": "-",
                        "status": "FAIL",
                    })
                    overlap_items.append({
                        "comp": ind, "status": "FAIL",
                        "detail": "Avoidance",
                    })

                if overlap_items:
                    safe = sc.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{sc_layer}_sc.png"
                    render_overlap_image(
                        sc, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="General inductor avoidance (shield can)",
                        layer_name=sc_layer,
                        primary_label="Shield Can",
                        overlap_label="General Inductor",
                        primary_is_bottom=sc_is_bottom,
                        overlap_is_bottom=ind_is_bottom,
                        user_symbols=user_symbols,
                    )
                    images.append({"path": img_path,
                                   "title": f"{sc.comp_name} ({sc_layer}) – Shield Can",
                                   "width": 500})

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"일반 인덕터 배치 문제(커넥터 엣지/방향 또는 쉴드캔 회피)가 "
                f"{fail_count}건 발견되었습니다."
                if not passed
                else "커넥터/쉴드캔 인근 모든 일반 인덕터가 적절히 배치되어 있습니다."
            ),
            affected_components=[
                r["overlapping_ind"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
