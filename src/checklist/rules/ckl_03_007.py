"""CKL-03-007: 5-pin RF Filter GND pads must each have at least 1 VIA.

Check process
-------------
1. Find Filter components on top and bottom layers.
2. Filter to components with exactly 5 pins/pads.
3. For each pad, determine if the signal is GND (ground).
4. For GND pads, verify at least 1 VIA is applied.

Columns: comp, cmp_layer, pad, signal, via, status
- status: non-GND pads → PASS, GND pads with >=1 VIA → PASS, else FAIL.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import find_filters
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    build_toeprint_lookup,
    build_via_position_set,
    count_vias_at_pad,
    lookup_resolved_pads_for_pin,
)
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.via_check_viz import render_via_check_image
from src.models import RuleResult
from src.visualizer.fid_lookup import (
    _find_top_bottom_signal_layers,
    build_fid_map,
    resolve_fid_features,
)

# Net names considered as ground
_GND_PATTERNS = {
    "GND", "GROUND", "VSS", "VSSA", "VSSQ", "DGND", "AGND",
    "PGND", "SGND", "AVSS", "DVSS",
}


def _is_ground_net(net_name: str) -> bool:
    """Return True if *net_name* looks like a ground net."""
    if not net_name:
        return False
    upper = net_name.strip().upper()
    if upper in _GND_PATTERNS:
        return True
    if "GND" in upper or "GROUND" in upper or "VSS" in upper:
        return True
    return False


def _get_net_name(toeprint, eda_data) -> str:
    """Resolve net name for a toeprint from EDA data."""
    if eda_data is None or toeprint is None:
        return ""
    if toeprint.net_num < 0 or toeprint.net_num >= len(eda_data.nets):
        return ""
    return eda_data.nets[toeprint.net_num].name or ""


@register_rule
class CKL03007(ChecklistRule):
    rule_id = "CKL-03-007"
    description = (
        "5핀 RF Filter의 GND 패드 당 VIA 1개 이상 적용할 것"
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

        columns = ["comp", "cmp_layer", "pad", "signal", "via", "status"]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_03_007_"))

        for comps, layer_name, is_bottom in [
            (components_top, "Top", False),
            (components_bot, "Bottom", True),
        ]:
            via_positions = via_bot if is_bottom else via_top
            sig_name = bot_sig_name if is_bottom else top_sig_name

            # Find 5-pin filter components
            filters = find_filters(comps, packages, pin_count=5)

            for comp in filters:
                if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
                    continue
                pkg = packages[comp.pkg_ref]

                toep_by_pin = build_toeprint_lookup(comp, pkg)

                # Build nc_map for visualisation: non-GND pins → nc=True (blue),
                # GND pins → nc=False (red if no via, green if has via)
                nc_map: dict[int, bool] = {}

                for pin_idx, pin in enumerate(pkg.pins):
                    tp = toep_by_pin.get(pin_idx)
                    net_name = _get_net_name(tp, eda) if tp else ""
                    is_gnd = _is_ground_net(net_name)

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

                    # Mark non-GND pins as NC (informational) for visualisation
                    nc_map[pin_idx] = not is_gnd

                    if is_gnd:
                        status = "PASS" if via_count >= 1 else "FAIL"
                    else:
                        status = "PASS"

                    rows.append({
                        "comp": comp.comp_name,
                        "cmp_layer": layer_name,
                        "pad": pin.name,
                        "signal": net_name or "(none)",
                        "via": str(via_count),
                        "status": status,
                    })

                # Generate visualisation image for this filter
                safe_name = comp.comp_name.replace("/", "_")
                img_path = image_dir / f"{safe_name}_{layer_name}.png"
                render_via_check_image(
                    comp, pkg, via_positions, is_bottom, img_path,
                    rule_id=self.rule_id,
                    comp_type="5-pin RF Filter",
                    fid_resolved=fid_resolved,
                    signal_layer_name=sig_name,
                    min_via_count=1,
                    nc_map=nc_map,
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
                f"VIA가 없는 GND 패드가 {fail_count}건 감지되었습니다."
                if not passed
                else "모든 5핀 RF Filter GND 패드에 VIA가 적용되어 있습니다."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
