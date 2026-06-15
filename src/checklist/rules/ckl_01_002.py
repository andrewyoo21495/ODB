"""CKL-01-002: VIA presence check for outermost NC pads on PMICs.

This rule applies **only to PMIC components** (identified by part_name in
references/pmic_list.csv or FNC/SSHEET properties).  Non-PMIC ICs are not
evaluated.

For each PMIC, every outermost (outer perimeter) pad that is NC
(Not Connected) must have at least one VIA.  Additionally, the four corner
balls of a PMIC must have VIA even if they are connected.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

from src.checklist.component_classifier import (
    find_ics,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    build_toeprint_lookup,
    build_via_position_set,
    count_vias_at_pad,
    find_outermost_pin_indices,
    is_pad_nc,
    is_pad_nc_by_signal_layer,
    lookup_resolved_pads_for_pin,
)
from src.checklist.reference_loader import (
    get_managed_part_names,
    matches_any_reference_part,
)
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.via_check_viz import render_via_check_image
from src.models import Component, Pin, RuleResult
from src.visualizer.fid_lookup import (
    build_fid_map,
    resolve_fid_features,
    _find_top_bottom_signal_layers,
)


def _get_ic_type(comp: Component) -> str:
    """Return a human-readable IC type from component properties.

    Checks DEVICE_TYPE first, then FNC, falling back to 'IC'.
    """
    props = comp.properties or {}
    device_type = props.get("DEVICE_TYPE", "").strip()
    if device_type:
        return device_type
    fnc = props.get("FNC", "").strip()
    if fnc:
        return fnc
    return "IC"


def _is_pmic(comp: Component, pmic_parts: set[str]) -> bool:
    """Return True if *comp* is classified as a PMIC."""
    if matches_any_reference_part(comp.part_name or "", pmic_parts):
        return True
    props = comp.properties or {}
    fnc = props.get("FNC", "").upper()
    ssheet = props.get("SSHEET", "").upper()
    return "POWER SUPERVISOR" in fnc or "PMIC" in ssheet


def _find_corner_pin_indices(pins: list[Pin]) -> set[int]:
    """Return index of the single nearest pin to each bounding-box corner.

    Identifies the 4 corner balls of a BGA-style PMIC.
    """
    if not pins:
        return set()
    if len(pins) <= 4:
        return set(range(len(pins)))

    centres = [(p.center.x, p.center.y) for p in pins]
    xs = [c[0] for c in centres]
    ys = [c[1] for c in centres]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)

    bbox_corners = [
        (x_min, y_min),
        (x_max, y_min),
        (x_min, y_max),
        (x_max, y_max),
    ]

    result: set[int] = set()
    for cx, cy in bbox_corners:
        best_idx = min(
            range(len(centres)),
            key=lambda i: math.hypot(centres[i][0] - cx, centres[i][1] - cy),
        )
        result.add(best_idx)
    return result


def _is_pad_nc_robust(
    comp, pin, is_bottom, layers_data,
    signal_layer_name, resolved_pads, toeprint,
    eda_data, via_positions,
):
    """Robust NC detection combining signal-layer and EDA-net checks.

    A pad is considered NC when:
      1. Signal-layer analysis says NC (no trace/arc/pour connects), AND
      2. There are zero VIAs at the pad.

    If the signal-layer says connected but there are 0 VIAs and the
    EDA net has no TRC/VIA/PLN subnets, override to NC.  This catches
    cases where SurfaceRecord copper-pour false-positives fool the
    signal-layer check.
    """
    sig_nc = is_pad_nc_by_signal_layer(
        comp, pin, is_bottom, layers_data,
        signal_layer_name=signal_layer_name,
        resolved_pads=resolved_pads,
        toeprint=toeprint,
    )

    if sig_nc:
        return True

    # Signal layer says connected — cross-check with EDA net data.
    via_count = count_vias_at_pad(
        comp, pin.center.x, pin.center.y,
        via_positions, is_bottom=is_bottom,
        toeprint=toeprint, pin=pin,
        resolved_pads=resolved_pads,
    )
    if via_count > 0:
        return False  # Truly connected: has VIA

    # No VIA — check EDA net subnets
    eda_nc = is_pad_nc(toeprint, eda_data)
    if eda_nc:
        return True  # EDA also says NC → NC

    # Signal says connected, EDA says connected, but 0 VIAs.
    # Still treat as connected (not NC) — the rule will catch
    # corner pins separately.
    return False


@register_rule
class CKL01002(ChecklistRule):
    rule_id = "CKL-01-002"
    description = (
        "PMIC 부품의 최외곽 NC 패드 및 4개 코너 볼에 VIA 설계가 "
        "적용되어야 합니다"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        layers_data = job_data.get("layers_data", {})
        packages = eda.packages if eda else []

        pmic_parts = get_managed_part_names("pmic_list")

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

        columns = [
            "comp", "IC_type", "cmp_layer", "pad_name",
            "pad_type", "corner", "via", "status",
        ]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_01_002_"))

        for comps, layer_name, is_bottom in [
            (components_top, "Top", False),
            (components_bot, "Bottom", True),
        ]:
            via_positions = via_bot if is_bottom else via_top
            sig_name = bot_sig_name if is_bottom else top_sig_name

            # Collect PMIC components on this side (PMIC-only rule)
            pmics = [
                c for c in find_ics(comps)
                if _is_pmic(c, pmic_parts)
            ]

            for comp in pmics:
                if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
                    continue
                pkg = packages[comp.pkg_ref]
                if not pkg.pins:
                    continue

                ic_type = _get_ic_type(comp)

                outermost_indices = find_outermost_pin_indices(pkg.pins)
                corner_indices = _find_corner_pin_indices(pkg.pins)
                toep_by_pin = build_toeprint_lookup(comp, pkg)
                nc_map: dict[int, bool] = {}
                processed: set[int] = set()

                # --- Phase 1: Outermost NC pad check ---
                for pin_idx in sorted(outermost_indices):
                    pin = pkg.pins[pin_idx]
                    tp = toep_by_pin.get(pin_idx)
                    rpads = lookup_resolved_pads_for_pin(
                        fid_resolved, comp, is_bottom,
                        pin_idx, signal_layer_name=sig_name,
                    )

                    nc = _is_pad_nc_robust(
                        comp, pin, is_bottom, layers_data,
                        signal_layer_name=sig_name,
                        resolved_pads=rpads,
                        toeprint=tp,
                        eda_data=eda,
                        via_positions=via_positions,
                    )
                    nc_map[pin_idx] = nc

                    if not nc:
                        continue

                    via_count = count_vias_at_pad(
                        comp, pin.center.x, pin.center.y,
                        via_positions, is_bottom=is_bottom,
                        toeprint=tp, pin=pin,
                        resolved_pads=rpads,
                    )
                    has_via = via_count > 0
                    is_corner = pin_idx in corner_indices

                    # Status determination (PMIC: NC pad must have VIA)
                    status = "PASS" if has_via else "FAIL"

                    rows.append({
                        "comp": comp.comp_name,
                        "IC_type": ic_type,
                        "cmp_layer": layer_name,
                        "pad_name": pin.name,
                        "pad_type": "NC",
                        "corner": "TRUE" if is_corner else "FALSE",
                        "via": "TRUE" if has_via else "FALSE",
                        "status": status,
                    })
                    processed.add(pin_idx)

                # --- Phase 2: Corner pin check ---
                for pin_idx in sorted(corner_indices):
                    if pin_idx in processed:
                        continue
                    processed.add(pin_idx)

                    pin = pkg.pins[pin_idx]
                    tp = toep_by_pin.get(pin_idx)
                    rpads = lookup_resolved_pads_for_pin(
                        fid_resolved, comp, is_bottom,
                        pin_idx, signal_layer_name=sig_name,
                    )

                    nc = _is_pad_nc_robust(
                        comp, pin, is_bottom, layers_data,
                        signal_layer_name=sig_name,
                        resolved_pads=rpads,
                        toeprint=tp,
                        eda_data=eda,
                        via_positions=via_positions,
                    )

                    via_count = count_vias_at_pad(
                        comp, pin.center.x, pin.center.y,
                        via_positions, is_bottom=is_bottom,
                        toeprint=tp, pin=pin,
                        resolved_pads=rpads,
                    )
                    has_via = via_count > 0
                    status = "PASS" if has_via else "FAIL"

                    if pin_idx not in nc_map:
                        nc_map[pin_idx] = True

                    rows.append({
                        "comp": comp.comp_name,
                        "IC_type": ic_type,
                        "cmp_layer": layer_name,
                        "pad_name": pin.name,
                        "pad_type": "NC" if nc else "Connected",
                        "corner": "TRUE",
                        "via": "TRUE" if has_via else "FALSE",
                        "status": status,
                    })

                # Generate visualisation image only when there is a FAIL
                comp_rows = [
                    r for r in rows
                    if r["comp"] == comp.comp_name
                    and r["cmp_layer"] == layer_name
                ]
                has_fail = any(r["status"] == "FAIL" for r in comp_rows)
                if has_fail:
                    all_check_indices = outermost_indices | corner_indices
                    safe_name = comp.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe_name}_{layer_name}.png"
                    comp_label = "PMIC (outermost NC + corner)"
                    render_via_check_image(
                        comp, pkg, via_positions, is_bottom, img_path,
                        rule_id=self.rule_id,
                        comp_type=comp_label,
                        fid_resolved=fid_resolved,
                        signal_layer_name=sig_name,
                        pin_indices=all_check_indices,
                        eda_data=eda,
                        layers_data=layers_data,
                        nc_map=nc_map,
                        nc_is_fail=True,
                    )
                    images.append({
                        "path": img_path,
                        "title": f"{comp.comp_name} ({layer_name}) — {ic_type}",
                        "width": 500,
                    })

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        if not rows:
            msg = "PMIC 부품에서 검사 대상 최외곽/코너 패드가 발견되지 않았습니다."
        elif not passed:
            msg = (
                f"VIA가 없는 최외곽/코너 PMIC 패드가 {fail_count}건"
                f" 감지되었습니다."
            )
        else:
            msg = "모든 최외곽 및 코너 PMIC 패드에 VIA 설계가 적용되어 있습니다."

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=msg,
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns,
                     "rows": [r for r in rows if r["status"] != "PASS"]},
            images=images,
        )
