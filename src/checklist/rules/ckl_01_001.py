"""CKL-01-001: IC/Filter/OSC vs opposite-side component overlap check.

ICs and OSCs are checked for pad overlaps against:
  - Interposers (outer + inner border pads only — fill pads are safe)
  - Connectors, SIM sockets, Shield Cans (all pads)

Filters are checked for pad overlaps against:
  - Interposers (outer + inner border pads only)
  - Connectors, SIM sockets (all pads)

Interposer border logic
-----------------------
An interposer has a ring-shaped pad layout with an outer perimeter ring
and an inner ring surrounding the central empty region.  Only pads on
these two border rings are structurally critical:

  * IC pads overlapping **outer or inner border pads** → FAIL
  * IC pads overlapping **fill pads** (between borders) → PASS
  * IC overlapping interposer outline only (no pad contact) → PASS
  * No overlap at all → excluded from results

Images show dashed outlines for both the outer and inner border rings
of each interposer to aid visual inspection.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import (
    find_connectors, find_filters, find_ics, find_oscillators,
    find_interposers, find_shield_cans, find_simsockets,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    find_overlapping_components,
    find_pad_overlapping_components,
)
from src.checklist.geometry_utils.overlap import (
    _get_pad_union,
    _get_pad_union_for_indices,
    find_outer_inner_border_indices,
    get_border_outline_polygon,
)
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import RuleResult

try:
    from shapely.geometry import Point as ShapelyPoint
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False


def _classify_opp_type(c, interposers, simsockets, shield_cans):
    if c in interposers:
        return "Interposer"
    if c in simsockets:
        return "SIM_Socket"
    if c in shield_cans:
        return "Shield_Can"
    return "Connector"


# ---------------------------------------------------------------------------
# Interposer border-pad overlap helpers
# ---------------------------------------------------------------------------

def _get_interposer_border_unions(comp, packages, *, is_bottom=False,
                                  user_symbols=None):
    """Return (outer_pad_union, inner_pad_union) for an interposer component.

    Each is a Shapely geometry (or None) representing the pads on the
    outer and inner border rings respectively.
    """
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return None, None
    pkg = packages[comp.pkg_ref]
    if not pkg.pins:
        return None, None

    outer_idx, inner_idx = find_outer_inner_border_indices(pkg.pins)

    outer_union = _get_pad_union_for_indices(
        comp, pkg, outer_idx, is_bottom=is_bottom,
        user_symbols=user_symbols,
    ) if outer_idx else None

    inner_union = _get_pad_union_for_indices(
        comp, pkg, inner_idx, is_bottom=is_bottom,
        user_symbols=user_symbols,
    ) if inner_idx else None

    return outer_union, inner_union


def _get_interposer_outline_polygons(comp, packages, *, is_bottom=False):
    """Return (outer_outline, inner_outline) polygons for visualization.

    These are convex hulls of pin centres on each border ring,
    suitable for drawing as dashed boundary lines.
    """
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return None, None
    pkg = packages[comp.pkg_ref]
    if not pkg.pins:
        return None, None

    outer_idx, inner_idx = find_outer_inner_border_indices(pkg.pins)

    outer_poly = get_border_outline_polygon(
        comp, pkg, outer_idx, is_bottom=is_bottom,
    ) if outer_idx else None

    inner_poly = get_border_outline_polygon(
        comp, pkg, inner_idx, is_bottom=is_bottom,
    ) if inner_idx else None

    return outer_poly, inner_poly


def _find_interposer_border_overlapping(
    comp, interposers, packages, *,
    comp_is_bottom=False, opp_is_bottom=False,
    user_symbols=None,
):
    """Check comp's pads against each interposer's border pads.

    Returns list of (interposer, status) tuples:
      - FAIL if comp pads intersect outer or inner border pads
      - PASS if comp overlaps interposer footprint but not border pads
      - omitted if no overlap at all
    """
    if not _HAS_SHAPELY:
        return []

    pad_union_comp = _get_pad_union(
        comp, packages, is_bottom=comp_is_bottom,
        user_symbols=user_symbols,
    )
    if pad_union_comp is None:
        pad_union_comp = ShapelyPoint(comp.x, comp.y).buffer(0.05)

    # Check footprint-level overlap first to filter quickly
    outline_overlaps = set(
        id(c) for c in find_overlapping_components(
            comp, interposers, packages,
            is_bottom_primary=comp_is_bottom,
            is_bottom_candidates=opp_is_bottom,
        )
    )

    results = []
    for inp in interposers:
        if id(inp) not in outline_overlaps:
            continue

        outer_union, inner_union = _get_interposer_border_unions(
            inp, packages, is_bottom=opp_is_bottom,
            user_symbols=user_symbols,
        )

        hit_outer = (outer_union is not None
                     and pad_union_comp.intersects(outer_union))
        hit_inner = (inner_union is not None
                     and pad_union_comp.intersects(inner_union))

        if hit_outer or hit_inner:
            results.append((inp, "FAIL"))
        else:
            results.append((inp, "PASS"))

    return results


# ---------------------------------------------------------------------------
# Generic overlap check
# ---------------------------------------------------------------------------

def _check_overlaps(comp, comp_layer, interposers, full_pad_targets,
                    opp_type_fn, packages, rows,
                    *, comp_is_bottom=False, opp_is_bottom=False,
                    user_symbols=None):
    """Run overlap checks for a single component against opposite-side targets.

    - Interposers: only outer/inner border pads trigger FAIL
    - full_pad_targets (connectors, SIM sockets, shield cans): all pads

    Returns a list of overlap_item dicts for grouping by overlapping_cmp.
    """
    overlap_items: list[dict] = []

    # --- Interposer checks (border pads only) ---
    if interposers:
        inp_results = _find_interposer_border_overlapping(
            comp, interposers, packages,
            comp_is_bottom=comp_is_bottom,
            opp_is_bottom=opp_is_bottom,
            user_symbols=user_symbols,
        )
        for ovl, status in inp_results:
            rows.append({
                "comp": comp.comp_name,
                "cmp_layer": comp_layer,
                "overlapping_cmp": ovl.comp_name,
                "opp_type": opp_type_fn(ovl),
                "status": status,
            })
            overlap_items.append({
                "comp": ovl, "status": status,
                "detail": opp_type_fn(ovl),
            })

    # --- Connector / SIM socket / Shield Can checks (all pads) ---
    if full_pad_targets:
        outline_ovl = find_overlapping_components(
            comp, full_pad_targets, packages,
            is_bottom_primary=comp_is_bottom,
            is_bottom_candidates=opp_is_bottom,
        )
        pad_ovl = find_pad_overlapping_components(
            comp, full_pad_targets, packages,
            is_bottom_primary=comp_is_bottom,
            is_bottom_candidates=opp_is_bottom,
            user_symbols=user_symbols,
        )

        pad_ovl_ids = {id(c) for c in pad_ovl}
        for ovl in pad_ovl:
            status = "FAIL"
            rows.append({
                "comp": comp.comp_name,
                "cmp_layer": comp_layer,
                "overlapping_cmp": ovl.comp_name,
                "opp_type": opp_type_fn(ovl),
                "status": status,
            })
            overlap_items.append({
                "comp": ovl, "status": status,
                "detail": opp_type_fn(ovl),
            })
        for ovl in outline_ovl:
            if id(ovl) in pad_ovl_ids:
                continue
            status = "PASS"
            rows.append({
                "comp": comp.comp_name,
                "cmp_layer": comp_layer,
                "overlapping_cmp": ovl.comp_name,
                "opp_type": opp_type_fn(ovl),
                "status": status,
            })
            overlap_items.append({
                "comp": ovl, "status": status,
                "detail": opp_type_fn(ovl),
            })

    return overlap_items


@register_rule
class CKL01001(ChecklistRule):
    rule_id = "CKL-01-001"
    description = (
        "IC, OSC 및 필터는 반대면의 인터포저, 커넥터, SIM 소켓, "
        "쉴드캔과 패드 간 중첩이 없어야 합니다"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []
        user_symbols: dict = job_data.get("user_symbols") or {}

        columns = ["comp", "cmp_layer", "overlapping_cmp", "opp_type", "status"]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_01_001_"))

        # Maps (ovl_comp_name, opp_layer) -> {
        #     "ovl_comp": Component,
        #     "opp_is_bottom": bool,
        #     "same_comps": list,
        #     "items": list[dict],
        # }
        ovl_image_map: dict[tuple[str, str], dict] = {}

        for same_comps, layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            comp_is_bottom = (layer == "Bottom")
            opp_is_bottom = not comp_is_bottom
            opp_layer = "Bottom" if comp_is_bottom else "Top"

            opp_interposers = find_interposers(opp_comps)
            opp_connectors = find_connectors(opp_comps)
            opp_simsockets = find_simsockets(opp_comps)
            opp_shield_cans = find_shield_cans(opp_comps)

            opp_type_fn = lambda c, _inp=opp_interposers, _sim=opp_simsockets, _sc=opp_shield_cans: (
                _classify_opp_type(c, _inp, _sim, _sc)
            )

            def _register_overlaps(primary_comp, primary_label, items):
                for item in items:
                    ovl = item["comp"]
                    key = (ovl.comp_name, opp_layer)
                    if key not in ovl_image_map:
                        ovl_image_map[key] = {
                            "ovl_comp": ovl,
                            "opp_is_bottom": opp_is_bottom,
                            "same_comps": same_comps,
                            "items": [],
                        }
                    ovl_image_map[key]["items"].append({
                        "comp": primary_comp,
                        "status": item["status"],
                        "detail": primary_label,
                    })

            # --- IC checks ---
            ics = find_ics(same_comps)
            ic_full_targets = opp_connectors + opp_simsockets + opp_shield_cans
            for ic in ics:
                items = _check_overlaps(
                    ic, layer, opp_interposers, ic_full_targets,
                    opp_type_fn, packages, rows,
                    comp_is_bottom=comp_is_bottom,
                    opp_is_bottom=opp_is_bottom,
                    user_symbols=user_symbols,
                )
                _register_overlaps(ic, "IC", items)

            # --- OSC checks (same targets as IC) ---
            oscs = find_oscillators(same_comps)
            for osc in oscs:
                items = _check_overlaps(
                    osc, layer, opp_interposers, ic_full_targets,
                    opp_type_fn, packages, rows,
                    comp_is_bottom=comp_is_bottom,
                    opp_is_bottom=opp_is_bottom,
                    user_symbols=user_symbols,
                )
                _register_overlaps(osc, "OSC", items)

            # --- Filter checks ---
            filters = find_filters(same_comps)
            filter_full_targets = opp_connectors + opp_simsockets
            for flt in filters:
                items = _check_overlaps(
                    flt, layer, opp_interposers, filter_full_targets,
                    opp_type_fn, packages, rows,
                    comp_is_bottom=comp_is_bottom,
                    opp_is_bottom=opp_is_bottom,
                    user_symbols=user_symbols,
                )
                _register_overlaps(flt, "Filter", items)

        # --- Generate one image per overlapping_cmp ---
        for (ovl_name, opp_layer), data in ovl_image_map.items():
            ovl_comp = data["ovl_comp"]
            opp_is_bottom = data["opp_is_bottom"]
            same_comps = data["same_comps"]
            items = data["items"]
            if not items:
                continue
            if not any(item["status"] == "FAIL" for item in items):
                continue

            # Build interposer outline polygons for visualization
            inp_outer_outline, inp_inner_outline = None, None
            opp_type = _classify_opp_type(
                ovl_comp,
                find_interposers(
                    [c for c in (components_top if opp_is_bottom else components_bot)]),
                find_simsockets(
                    [c for c in (components_top if opp_is_bottom else components_bot)]),
                find_shield_cans(
                    [c for c in (components_top if opp_is_bottom else components_bot)]),
            )
            if opp_type == "Interposer":
                inp_outer_outline, inp_inner_outline = (
                    _get_interposer_outline_polygons(
                        ovl_comp, packages, is_bottom=opp_is_bottom,
                    )
                )

            safe = ovl_name.replace("/", "_")
            img_path = image_dir / f"{safe}_{opp_layer}.png"
            render_overlap_image(
                ovl_comp, packages, items, same_comps, img_path,
                rule_id=self.rule_id,
                title="Opposite-side overlap",
                layer_name=opp_layer,
                primary_label="Overlapping cmp",
                primary_is_bottom=opp_is_bottom,
                overlap_is_bottom=not opp_is_bottom,
                user_symbols=user_symbols,
                interposer_outer_outline=inp_outer_outline,
                interposer_inner_outline=inp_inner_outline,
                annotate_pass=False,
            )
            images.append({"path": img_path,
                           "title": f"{ovl_name} ({opp_layer})",
                           "width": 500})

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"반대면 부품과의 패드 간 중첩이 {fail_count}건 발견되었습니다."
                if not passed
                else "반대면 부품과의 패드 간 중첩이 감지되지 않았습니다."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns,
                     "rows": sorted(
                         [r for r in rows if r["status"] != "PASS"],
                         key=lambda r: r.get("overlapping_cmp", ""),
                     )},
            images=images,
        )
