"""CKL-01-001: IC/Filter vs opposite-side component overlap check.

ICs are checked for pad overlaps against:
  - Interposers (outermost pads only)
  - Connectors, SIM sockets, Shield Cans (all pads)

Filters are checked for pad overlaps against:
  - Interposers (outermost pads only)
  - Connectors, SIM sockets (all pads)

Outline-only overlaps are acceptable and recorded as PASS.
Pad-to-pad contact is flagged as FAIL.
Items with no overlap are excluded from results.

Images are generated per overlapping_cmp (one image per connector /
shield can / interposer), showing all ICs and filters that overlap it.
"""

from __future__ import annotations

import tempfile
from collections import defaultdict
from pathlib import Path

from src.checklist.component_classifier import (
    find_connectors, find_filters, find_ics,
    find_interposers, find_shield_cans, find_simsockets,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    find_overlapping_components,
    find_outermost_pad_overlapping_components,
    find_pad_overlapping_components,
)
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import RuleResult


def _classify_opp_type(c, interposers, simsockets, shield_cans):
    if c in interposers:
        return "Interposer"
    if c in simsockets:
        return "SIM_Socket"
    if c in shield_cans:
        return "Shield_Can"
    return "Connector"


def _check_overlaps(comp, comp_layer, interposers, full_pad_targets,
                    opp_type_fn, packages, rows,
                    *, comp_is_bottom=False, opp_is_bottom=False):
    """Run overlap checks for a single component against opposite-side targets.

    - Interposers: checked against outermost pads only
    - full_pad_targets (connectors, SIM sockets, and optionally shield cans):
      checked against all pads

    Returns a list of overlap_item dicts for grouping by overlapping_cmp.
    Each item: {"comp": ovl_comp, "status": str, "detail": str}
    """
    overlap_items: list[dict] = []

    # --- Interposer checks (outermost pads) ---
    if interposers:
        outline_ovl = find_overlapping_components(
            comp, interposers, packages,
            is_bottom_primary=comp_is_bottom,
            is_bottom_candidates=opp_is_bottom,
        )
        pad_ovl = find_outermost_pad_overlapping_components(
            comp, interposers, packages,
            is_bottom_primary=comp_is_bottom,
            is_bottom_candidates=opp_is_bottom,
        )

        if pad_ovl:
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
        elif outline_ovl:
            for ovl in outline_ovl:
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
        )

        if pad_ovl:
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
        elif outline_ovl:
            for ovl in outline_ovl:
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
        "ICs and Filters must not have pad-to-pad overlaps with interposers, "
        "connectors, SIM sockets, or shield cans on the opposite side"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        columns = ["comp", "cmp_layer", "overlapping_cmp", "opp_type", "status"]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_01_001_"))

        # Maps (ovl_comp_name, opp_layer) -> {
        #     "ovl_comp": Component,
        #     "opp_is_bottom": bool,
        #     "same_comps": list,        # opposite-side component pool (for context)
        #     "items": list[dict],       # {"comp": primary, "status", "detail"}
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
                """Group overlap items by overlapping_cmp for image generation."""
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
                )
                _register_overlaps(ic, "IC", items)

            # --- Filter checks ---
            filters = find_filters(same_comps)
            filter_full_targets = opp_connectors + opp_simsockets
            for flt in filters:
                items = _check_overlaps(
                    flt, layer, opp_interposers, filter_full_targets,
                    opp_type_fn, packages, rows,
                    comp_is_bottom=comp_is_bottom,
                    opp_is_bottom=opp_is_bottom,
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
                f"{fail_count} pad-to-pad overlap(s) with opposite-side "
                f"components found."
                if not passed
                else "No pad-to-pad overlaps with opposite-side components detected."
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
