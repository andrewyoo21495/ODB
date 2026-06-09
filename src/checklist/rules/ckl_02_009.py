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
    _get_pad_union,
    filter_by_size,
    find_pad_overlapping_components,
    get_component_orientation,
    is_on_edge,
)
from src.checklist.geometry_utils.overlap import (
    _symbol_to_shapely,
    _user_symbol_to_shapely,
)
from src.checklist.reference_loader import (
    get_managed_part_names,
    get_part_size_map,
    matches_any_reference_part,
)
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import Component, RuleResult

try:
    from shapely.geometry import Point as ShapelyPoint
    from shapely.ops import unary_union
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False

# Threshold: pads with area below this fraction of the median pad area
# are considered "small circle pads" and excluded from SC overlap checks.
_SMALL_PAD_AREA_RATIO = 0.15


def _get_sc_pad_union_no_small_circles(
    comp: Component,
    packages: list,
    *,
    is_bottom: bool = False,
    user_symbols: dict | None = None,
):
    """Build pad union for a shield can, excluding small circular pads.

    Small circular pads (mounting/anchor dots) are filtered out based on
    area comparison: pads whose area is less than *_SMALL_PAD_AREA_RATIO*
    of the median pad area are excluded.
    """
    if not _HAS_SHAPELY:
        return None
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return None

    user_symbols = user_symbols or {}

    # Build individual pad geometries from toeprint geom data
    pad_geoms: list = []
    for tp in comp.toeprints:
        if tp.geom is None:
            continue
        geom = tp.geom
        pad_rot = -geom.rotation if is_bottom else geom.rotation

        if geom.is_user_symbol and geom.symbol_name in user_symbols:
            g = _user_symbol_to_shapely(
                user_symbols[geom.symbol_name],
                geom.x, geom.y, pad_rot, geom.mirror,
            )
        else:
            g = _symbol_to_shapely(
                geom.symbol_name, geom.x, geom.y, pad_rot, geom.mirror,
                geom.units, geom.unit_override, geom.resize_factor,
            )

        if g is not None and not g.is_empty:
            pad_geoms.append(g)

    if not pad_geoms:
        # Fallback: use full pad union (no filtering possible)
        return _get_pad_union(comp, packages, is_bottom=is_bottom,
                              user_symbols=user_symbols)

    # Compute areas and filter small circular pads
    areas = [g.area for g in pad_geoms]
    areas_sorted = sorted(areas)
    median_area = areas_sorted[len(areas_sorted) // 2]

    if median_area <= 0:
        return unary_union(pad_geoms)

    threshold = median_area * _SMALL_PAD_AREA_RATIO
    large_pads = [g for g, a in zip(pad_geoms, areas) if a >= threshold]

    if not large_pads:
        return unary_union(pad_geoms)

    return unary_union(large_pads)


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
                if not matches_any_reference_part(c.part_name or "", ind_2s_parts)
            ]
            if not connectors or not opp_general_ind:
                continue

            for conn in connectors:
                overlaps = find_pad_overlapping_components(
                    conn, opp_general_ind, packages,
                    user_symbols=user_symbols,
                )
                filtered = filter_by_size(overlaps, 2012, size_maps, packages,
                                         desc_index=2)

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
                if not matches_any_reference_part(c.part_name or "", ind_2s_parts)
            ]
            if not shield_cans or not opp_general_ind:
                continue

            for sc in shield_cans:
                # Build SC pad union excluding small circular pads
                sc_pad_no_small = _get_sc_pad_union_no_small_circles(
                    sc, packages,
                    is_bottom=sc_is_bottom,
                    user_symbols=user_symbols,
                )

                overlaps = find_pad_overlapping_components(
                    sc, opp_general_ind, packages,
                    is_bottom_primary=sc_is_bottom,
                    is_bottom_candidates=ind_is_bottom,
                    user_symbols=user_symbols,
                )
                filtered = filter_by_size(overlaps, 2012, size_maps, packages,
                                         desc_index=2)

                overlap_items: list[dict] = []
                for ind, sz in filtered:
                    # Re-check overlap against SC pads without small circles
                    ind_pads = _get_pad_union(
                        ind, packages, is_bottom=ind_is_bottom,
                        user_symbols=user_symbols,
                    )
                    if (sc_pad_no_small is not None
                            and ind_pads is not None
                            and not sc_pad_no_small.intersects(ind_pads)):
                        # Inductor only overlaps small circular pads → PASS
                        rows.append({
                            "check_type": "Shield Can",
                            "comp": sc.comp_name,
                            "cmp_layer": sc_layer,
                            "overlapping_ind": ind.comp_name,
                            "part_name": ind.part_name or "",
                            "edge": "-",
                            "hori/verti": "-",
                            "status": "PASS",
                        })
                        overlap_items.append({
                            "comp": ind, "status": "PASS",
                            "detail": "Small circle pad only",
                        })
                        continue

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
