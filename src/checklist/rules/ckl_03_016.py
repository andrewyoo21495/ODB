"""CKL-03-016: No INP/SC/SIM/Connector on the opposite side of OSC.

Interposers, Shield Cans, SIM Sockets, and Connectors must not have
pad-level overlap with Oscillator components on the opposite side.

- For non-interposer targets:
  - Pad-to-pad overlap → FAIL
  - Outline-only overlap (no pad contact) → PASS
- For interposers (special handling):
  - OSC pads intersect interposer pad-ring outline → FAIL
  - OSC pads overlap interposer pads only (no outline hit) → PASS
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from shapely.ops import unary_union

from src.checklist.component_classifier import (
    find_antennas,
    find_connectors,
    find_interposers,
    find_oscillators,
    find_shield_cans,
    find_simsockets,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    _get_pad_union,
    build_interposer_outline,
    find_overlapping_components,
    find_pad_overlapping_components,
)
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import RuleResult


@register_rule
class CKL03016(ChecklistRule):
    rule_id = "CKL-03-016"
    description = (
        "인터포저, 쉴드캔, SIM 소켓, 커넥터, 안테나는 OSC 부품의 "
        "반대면과 패드 중첩이 없어야 합니다"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []
        user_symbols: dict = job_data.get("user_symbols") or {}

        columns = [
            "comp", "cmp_layer", "overlapping_cmp", "part_name",
            "overlap_type", "status",
        ]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_03_016_"))

        for oscs, osc_layer, opp_comps in [
            (find_oscillators(components_top), "Top", components_bot),
            (find_oscillators(components_bot), "Bottom", components_top),
        ]:
            osc_is_bottom = (osc_layer == "Bottom")
            opp_is_bottom = not osc_is_bottom

            opp_interposers = find_interposers(opp_comps)
            opp_shield_cans = find_shield_cans(opp_comps)
            opp_simsockets = find_simsockets(opp_comps)
            opp_connectors = find_connectors(opp_comps)
            opp_antennas = find_antennas(opp_comps)

            # Non-interposer targets use existing pad/outline overlap logic
            opp_non_interposers = (
                opp_shield_cans + opp_simsockets
                + opp_connectors + opp_antennas
            )

            if not opp_non_interposers and not opp_interposers:
                continue

            for osc in oscs:
                overlap_items: list[dict] = []
                inp_outer_polys: list = []
                inp_inner_polys: list = []

                # -------------------------------------------------------
                # Non-interposer targets: existing logic
                # -------------------------------------------------------
                if opp_non_interposers:
                    pad_overlaps = find_pad_overlapping_components(
                        osc, opp_non_interposers, packages,
                        is_bottom_primary=osc_is_bottom,
                        is_bottom_candidates=opp_is_bottom,
                        user_symbols=user_symbols,
                    )
                    pad_overlap_ids = {id(c) for c in pad_overlaps}

                    outline_overlaps = find_overlapping_components(
                        osc, opp_non_interposers, packages,
                        is_bottom_primary=osc_is_bottom,
                        is_bottom_candidates=opp_is_bottom,
                    )

                    # Pad overlaps → FAIL
                    for ovl in pad_overlaps:
                        rows.append({
                            "comp": osc.comp_name,
                            "cmp_layer": osc_layer,
                            "overlapping_cmp": ovl.comp_name,
                            "part_name": ovl.part_name or "",
                            "overlap_type": "PAD",
                            "status": "FAIL",
                        })
                        overlap_items.append({"comp": ovl, "status": "FAIL"})

                    # Outline-only overlaps (not pad) → PASS
                    for ovl in outline_overlaps:
                        if id(ovl) in pad_overlap_ids:
                            continue
                        rows.append({
                            "comp": osc.comp_name,
                            "cmp_layer": osc_layer,
                            "overlapping_cmp": ovl.comp_name,
                            "part_name": ovl.part_name or "",
                            "overlap_type": "OUTLINE_ONLY",
                            "status": "PASS",
                        })
                        overlap_items.append({"comp": ovl, "status": "PASS"})

                # -------------------------------------------------------
                # Interposer targets: outline-based logic
                # -------------------------------------------------------
                for inp in opp_interposers:
                    outer_poly, inner_poly = build_interposer_outline(
                        inp, packages,
                        is_bottom=opp_is_bottom,
                        user_symbols=user_symbols,
                    )
                    if outer_poly is not None:
                        inp_outer_polys.append(outer_poly)
                    if inner_poly is not None:
                        inp_inner_polys.append(inner_poly)

                    pad_union_osc = _get_pad_union(
                        osc, packages,
                        is_bottom=osc_is_bottom,
                        user_symbols=user_symbols,
                    )
                    if pad_union_osc is None:
                        continue

                    if outer_poly is None:
                        # Fallback: no outline available → treat like
                        # non-interposer (pad overlap = FAIL)
                        pad_union_inp = _get_pad_union(
                            inp, packages,
                            is_bottom=opp_is_bottom,
                            user_symbols=user_symbols,
                        )
                        if (pad_union_inp is not None
                                and pad_union_osc.intersects(pad_union_inp)):
                            rows.append({
                                "comp": osc.comp_name,
                                "cmp_layer": osc_layer,
                                "overlapping_cmp": inp.comp_name,
                                "part_name": inp.part_name or "",
                                "overlap_type": "PAD",
                                "status": "FAIL",
                            })
                            overlap_items.append(
                                {"comp": inp, "status": "FAIL"})
                        continue

                    if pad_union_osc.intersects(outer_poly):
                        # OSC pads touch interposer outline → FAIL
                        rows.append({
                            "comp": osc.comp_name,
                            "cmp_layer": osc_layer,
                            "overlapping_cmp": inp.comp_name,
                            "part_name": inp.part_name or "",
                            "overlap_type": "PAD_VS_INP_OUTLINE",
                            "status": "FAIL",
                        })
                        overlap_items.append(
                            {"comp": inp, "status": "FAIL"})
                    else:
                        # No outline intersection — check pad-only overlap
                        pad_union_inp = _get_pad_union(
                            inp, packages,
                            is_bottom=opp_is_bottom,
                            user_symbols=user_symbols,
                        )
                        if (pad_union_inp is not None
                                and pad_union_osc.intersects(pad_union_inp)):
                            # Pad overlap but no outline intersection → PASS
                            rows.append({
                                "comp": osc.comp_name,
                                "cmp_layer": osc_layer,
                                "overlapping_cmp": inp.comp_name,
                                "part_name": inp.part_name or "",
                                "overlap_type": "PAD_ONLY_NO_OUTLINE",
                                "status": "PASS",
                            })
                            overlap_items.append(
                                {"comp": inp, "status": "PASS"})

                # -------------------------------------------------------
                # Visualization (shared for all target types)
                # -------------------------------------------------------
                if overlap_items and any(
                    i["status"] == "FAIL" for i in overlap_items
                ):
                    opp_targets = (
                        opp_interposers + opp_non_interposers
                    )
                    safe = osc.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{osc_layer}.png"
                    inp_outer = (unary_union(inp_outer_polys)
                                 if inp_outer_polys else None)
                    inp_inner = (unary_union(inp_inner_polys)
                                 if inp_inner_polys else None)
                    render_overlap_image(
                        osc, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="Opposite-side overlap on OSC",
                        layer_name=osc_layer,
                        primary_label="OSC",
                        primary_is_bottom=osc_is_bottom,
                        overlap_is_bottom=opp_is_bottom,
                        user_symbols=user_symbols,
                        interposer_outer_outline=inp_outer,
                        interposer_inner_outline=inp_inner,
                    )
                    images.append({"path": img_path,
                                   "title": f"{osc.comp_name} ({osc_layer})",
                                   "width": 500})

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"OSC 반대면과 패드 중첩되는 부품이 {fail_count}건 발견되었습니다."
                if not passed
                else "OSC 반대면과 패드 중첩되는 금지 부품이 없습니다."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={
                "columns": columns,
                "rows": [r for r in rows if r["status"] != "PASS"],
            },
            images=images,
        )
