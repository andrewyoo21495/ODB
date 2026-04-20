"""CKL-03-009: SIM socket outermost pads must have at least 4 VIAs.

For each SIM socket component, only the outermost (perimeter) pads are checked.
Inner pads that have neighbors on all four cardinal sides are excluded.
Each perimeter pad must have at least 4 VIAs for robustness against tearing.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

from src.checklist.component_classifier import find_simsockets
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    build_toeprint_lookup,
    build_via_position_set,
    count_vias_at_pad,
    lookup_resolved_pads_for_pin,
)
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.via_check_viz import render_via_check_image
from src.models import Pin, RuleResult
from src.visualizer.fid_lookup import (
    _find_top_bottom_signal_layers,
    build_fid_map,
    resolve_fid_features,
)


def _find_outermost_pin_indices(pins: list[Pin]) -> set[int]:
    """Return indices of the outermost (bounding-box-edge) pins of a SIM socket.

    A pin is "outermost" when it lies at or very near the extreme minX, maxX,
    minY, or maxY of the pad-centre bounding box.  This identifies the isolated
    structural/mounting pads at the perimeter of the SIM socket (corner pads,
    side pads, bottom pads) while excluding the dense inner signal pad clusters
    and any intermediate rows/columns of pads.

    Tolerance is set to 40 % of the minimum inter-pin distance so that minor
    alignment variations within a column or row are tolerated without
    accidentally capturing interior pads.
    """
    if not pins:
        return set()

    n = len(pins)
    if n <= 1:
        return {0}

    centers = [(p.center.x, p.center.y) for p in pins]
    xs = [c[0] for c in centers]
    ys = [c[1] for c in centers]

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    # Alignment tolerance from the minimum inter-pin distance
    min_dist = float("inf")
    for i in range(n):
        for j in range(i + 1, n):
            d = math.hypot(centers[j][0] - centers[i][0],
                           centers[j][1] - centers[i][1])
            if d > 1e-6:
                min_dist = min(min_dist, d)

    tol = (min_dist * 0.4) if min_dist < float("inf") else 0.1

    outermost: set[int] = set()
    for i, (x, y) in enumerate(centers):
        if (x <= min_x + tol or x >= max_x - tol
                or y <= min_y + tol or y >= max_y - tol):
            outermost.add(i)

    return outermost


@register_rule
class CKL03009(ChecklistRule):
    rule_id = "CKL-03-009"
    description = (
        "SIM socket outermost pads must have at least 4 VIAs for tear resistance"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        layers_data = job_data.get("layers_data", {})
        packages = eda.packages if eda else []

        # Build VIA position sets per layer
        via_top: set[tuple[float, float]] = set()
        via_bot: set[tuple[float, float]] = set()
        if eda and layers_data:
            via_top = build_via_position_set(eda, layers_data, is_bottom=False)
            via_bot = build_via_position_set(eda, layers_data, is_bottom=True)

        # Build FID-resolved pad lookup for actual copper pad geometry
        fid_resolved: dict = {}
        top_sig_name, bot_sig_name = None, None
        if eda and layers_data:
            fid_map = build_fid_map(eda)
            fid_resolved = resolve_fid_features(
                fid_map, eda.layer_names, layers_data)
            top_sig_name, bot_sig_name = _find_top_bottom_signal_layers(
                layers_data)

        columns = ["comp", "cmp_layer", "pad", "via", "status"]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_03_009_"))

        for comps, layer_name, is_bottom in [
            (components_top, "Top", False),
            (components_bot, "Bottom", True),
        ]:
            via_positions = via_bot if is_bottom else via_top
            sig_name = bot_sig_name if is_bottom else top_sig_name
            sim_sockets = find_simsockets(comps)

            for comp in sim_sockets:
                if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
                    continue
                pkg = packages[comp.pkg_ref]
                if not pkg.pins:
                    continue

                perimeter_indices = _find_outermost_pin_indices(pkg.pins)
                toep_by_pin = build_toeprint_lookup(comp, pkg)

                for pin_idx in sorted(perimeter_indices):
                    pin = pkg.pins[pin_idx]
                    tp = toep_by_pin.get(pin_idx)
                    rpads = lookup_resolved_pads_for_pin(
                        fid_resolved, comp, is_bottom,
                        pin_idx, signal_layer_name=sig_name,
                    )
                    via_count = count_vias_at_pad(
                        comp, pin.center.x, pin.center.y,
                        via_positions, is_bottom=is_bottom,
                        toeprint=tp, pin=pin,
                        resolved_pads=rpads,
                    )
                    rows.append({
                        "comp": comp.comp_name,
                        "cmp_layer": layer_name,
                        "pad": pin.name,
                        "via": str(via_count),
                        "status": "PASS" if via_count >= 4 else "FAIL",
                    })

                # Generate visualisation image – highlight perimeter pins only
                safe_name = comp.comp_name.replace("/", "_")
                img_path = image_dir / f"{safe_name}_{layer_name}.png"
                render_via_check_image(
                    comp, pkg, via_positions, is_bottom, img_path,
                    rule_id=self.rule_id,
                    comp_type="SIM Socket",
                    fid_resolved=fid_resolved,
                    signal_layer_name=sig_name,
                    pin_indices=perimeter_indices,  # = outermost indices
                )
                images.append({
                    "path": img_path,
                    "title": f"{comp.comp_name} ({layer_name})",
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
                f"{fail_count} SIM socket perimeter pad(s) with fewer than 4 VIAs detected."
                if not passed
                else "All SIM socket perimeter pads have at least 4 VIAs."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
