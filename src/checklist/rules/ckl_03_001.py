"""CKL-03-001: MCP IC — opposite-side connector overlap and corner via check.

For each MCP (Multi-Chip Package) IC:
  1. Connector Overlap – no connectors may overlap the opposite side.
  2. Corner Via       – vias must be applied to the corner pins (the two
                        outermost pads at each of the four corner sections).
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

from src.checklist.component_classifier import find_connectors, find_ics
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    build_toeprint_lookup,
    build_via_position_set,
    count_vias_at_pad,
    find_pad_overlapping_components,
    lookup_resolved_pads_for_pin,
)
from src.checklist.reference_loader import get_part_category_map
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.checklist.visualizers.via_check_viz import render_via_check_image
from src.models import Component, Pin, RuleResult
from src.visualizer.fid_lookup import (
    _find_top_bottom_signal_layers,
    build_fid_map,
    resolve_fid_features,
)


def _find_mcp_ics(components: list[Component]) -> list[Component]:
    """Return IC components whose part_name maps to category 'MCP' in ap_memory.csv."""
    category_map = get_part_category_map("ap_memory")
    ics = find_ics(components)
    return [
        ic for ic in ics
        if category_map.get(ic.part_name or "") == "MCP"
    ]


def _find_corner_pin_indices(pins: list[Pin], n_per_corner: int = 2) -> set[int]:
    """Return indices of the corner pins of the pad array.

    For each of the four bounding-box corners (top-left, top-right,
    bottom-left, bottom-right) the *n_per_corner* nearest pins by
    Euclidean distance are selected.  This matches the two outermost pads
    visible at each physical corner in the MCP layout (as illustrated in
    data/mcp2.png).

    For packages with <= n_per_corner * 4 pins, all pins are returned.
    """
    if not pins:
        return set()
    if len(pins) <= n_per_corner * 4:
        return set(range(len(pins)))

    centers = [(pin.center.x, pin.center.y) for pin in pins]
    xs = [c[0] for c in centers]
    ys = [c[1] for c in centers]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    bbox_corners = [
        (min_x, min_y),
        (max_x, min_y),
        (min_x, max_y),
        (max_x, max_y),
    ]

    result: set[int] = set()
    for cx, cy in bbox_corners:
        dists = sorted(
            (math.hypot(px - cx, py - cy), idx)
            for idx, (px, py) in enumerate(centers)
        )
        for _, idx in dists[:n_per_corner]:
            result.add(idx)

    return result


@register_rule
class CKL03001(ChecklistRule):
    rule_id = "CKL-03-001"
    description = (
        "MCP ICs: no connector overlap on opposite side, "
        "and corner pins must each have at least one VIA"
    )
    category = "Clearance"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        layers_data = job_data.get("layers_data", {})
        packages = eda.packages if eda else []

        # Build VIA position sets for both layers
        via_top: set[tuple[float, float]] = set()
        via_bot: set[tuple[float, float]] = set()
        fid_resolved: dict = {}
        top_sig_name, bot_sig_name = None, None
        if eda and layers_data:
            via_top = build_via_position_set(eda, layers_data, is_bottom=False)
            via_bot = build_via_position_set(eda, layers_data, is_bottom=True)
            fid_map = build_fid_map(eda)
            fid_resolved = resolve_fid_features(
                fid_map, eda.layer_names, layers_data
            )
            top_sig_name, bot_sig_name = _find_top_bottom_signal_layers(
                layers_data
            )

        columns = [
            "check_type", "comp", "cmp_layer",
            "overlapping_cmp", "part_name", "corner_pin", "via_count", "status",
        ]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_03_001_"))

        for ic_layer_comps, ic_layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            is_bottom = (ic_layer == "Bottom")
            via_positions = via_bot if is_bottom else via_top
            sig_name = bot_sig_name if is_bottom else top_sig_name

            mcp_ics = _find_mcp_ics(ic_layer_comps)
            if not mcp_ics:
                continue

            opp_connectors = find_connectors(opp_comps)

            for mcp in mcp_ics:
                safe = mcp.comp_name.replace("/", "_")

                # ── 1. Connector overlap check ────────────────────────────
                if opp_connectors:
                    overlaps = find_pad_overlapping_components(
                        mcp, opp_connectors, packages
                    )
                    overlap_items: list[dict] = []
                    for conn in overlaps:
                        rows.append({
                            "check_type": "Connector Overlap",
                            "comp": mcp.comp_name,
                            "cmp_layer": ic_layer,
                            "overlapping_cmp": conn.comp_name,
                            "part_name": conn.part_name or "",
                            "corner_pin": "-",
                            "via_count": "-",
                            "status": "FAIL",
                        })
                        overlap_items.append({"comp": conn, "status": "FAIL"})

                    if overlap_items:
                        img_path = image_dir / f"{safe}_{ic_layer}_opp.png"
                        render_overlap_image(
                            mcp, packages, overlap_items, opp_comps, img_path,
                            rule_id=self.rule_id,
                            title="Connector overlap on MCP",
                            layer_name=ic_layer,
                            primary_label="MCP IC",
                            overlap_label="Connector",
                        )
                        images.append({
                            "path": img_path,
                            "title": f"{mcp.comp_name} ({ic_layer}) – Connector Overlap",
                            "width": 500,
                        })

                # ── 2. Corner via check ───────────────────────────────────
                if mcp.pkg_ref < 0 or mcp.pkg_ref >= len(packages):
                    continue
                pkg = packages[mcp.pkg_ref]
                if not pkg.pins:
                    continue

                corner_indices = _find_corner_pin_indices(pkg.pins)
                toep_by_pin = build_toeprint_lookup(mcp, pkg)
                has_via_fail = False

                for pin_idx in sorted(corner_indices):
                    pin = pkg.pins[pin_idx]
                    tp = toep_by_pin.get(pin_idx)
                    rpads = lookup_resolved_pads_for_pin(
                        fid_resolved, mcp, is_bottom,
                        pin_idx, signal_layer_name=sig_name,
                    )
                    via_count = count_vias_at_pad(
                        mcp, pin.center.x, pin.center.y,
                        via_positions, is_bottom=is_bottom,
                        toeprint=tp, pin=pin,
                        resolved_pads=rpads,
                    )
                    status = "PASS" if via_count > 0 else "FAIL"
                    if status == "FAIL":
                        has_via_fail = True
                    rows.append({
                        "check_type": "Corner Via",
                        "comp": mcp.comp_name,
                        "cmp_layer": ic_layer,
                        "overlapping_cmp": "-",
                        "part_name": "-",
                        "corner_pin": pin.name,
                        "via_count": str(via_count),
                        "status": status,
                    })

                # Generate via visualisation image
                img_path = image_dir / f"{safe}_{ic_layer}_via.png"
                render_via_check_image(
                    mcp, pkg, via_positions, is_bottom, img_path,
                    rule_id=self.rule_id,
                    comp_type="MCP IC",
                    fid_resolved=fid_resolved,
                    signal_layer_name=sig_name,
                )
                images.append({
                    "path": img_path,
                    "title": f"{mcp.comp_name} ({ic_layer}) – Corner Vias",
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
                f"{fail_count} issue(s) found: connector overlap or missing corner via on MCP IC."
                if not passed
                else "All MCP ICs pass: no connector overlap, all corner pins have vias."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
