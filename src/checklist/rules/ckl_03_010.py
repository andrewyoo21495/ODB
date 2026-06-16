"""CKL-03-010: 보강판(SUS) GND 패드는 FLOOD/GND 연결 및 VIA 4개 이상 적용.

보강판 패드는 강성 보강을 위해 FLOOD 처리하여 GND와 연결하고, VIA를 4개
이상 적용해야 한다.  각 SUS 부품(부품명이 ``SUS``로 시작)의 모든 패드 중
ground 네트에 연결된 패드만 검사하며, 해당 GND 패드에 VIA가 4개 미만이면
FAIL 처리한다.
"""

from __future__ import annotations

import tempfile
from collections import defaultdict
from pathlib import Path

from src.checklist.component_classifier import find_washers
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    build_toeprint_lookup,
    build_via_position_set,
    count_vias_at_pad,
    lookup_resolved_pads_for_pin,
)
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.via_check_viz import render_via_check_image
from src.models import EdaData, RuleResult, Toeprint
from src.visualizer.fid_lookup import (
    _find_top_bottom_signal_layers,
    build_fid_map,
    resolve_fid_features,
)

_MIN_VIA = 4

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


def _get_net_name(toeprint: Toeprint | None, eda_data: EdaData | None) -> str:
    """Resolve net name for a toeprint from EDA data."""
    if eda_data is None or toeprint is None:
        return ""
    if toeprint.net_num < 0 or toeprint.net_num >= len(eda_data.nets):
        return ""
    return eda_data.nets[toeprint.net_num].name or ""


@register_rule
class CKL03010(ChecklistRule):
    rule_id = "CKL-03-010"
    description = (
        "보강판(SUS) 패드는 강성 보강을 위해 FLOOD 처리하여 GND와 연결하고, "
        "GND 패드에는 최소 4개의 VIA를 적용해야 합니다"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        layers_data = job_data.get("layers_data", {})
        packages = eda.packages if eda else []

        # Build VIA position sets per surface
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
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_03_010_"))

        # comp_name -> list of failing pad names (for grouped message)
        fail_pads_by_comp: dict[str, list[str]] = defaultdict(list)

        for comps, layer_name, is_bottom in [
            (components_top, "Top", False),
            (components_bot, "Bottom", True),
        ]:
            via_positions = via_bot if is_bottom else via_top
            sig_name = bot_sig_name if is_bottom else top_sig_name
            washers = find_washers(comps)

            for comp in washers:
                if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
                    continue
                pkg = packages[comp.pkg_ref]
                if not pkg.pins:
                    continue

                toep_by_pin = build_toeprint_lookup(comp, pkg)

                # Collect ground-connected pin indices (check all pads)
                gnd_indices: set[int] = set()
                for pin_idx in range(len(pkg.pins)):
                    tp = toep_by_pin.get(pin_idx)
                    net_name = _get_net_name(tp, eda)
                    if _is_ground_net(net_name):
                        gnd_indices.add(pin_idx)

                for pin_idx in sorted(gnd_indices):
                    pin = pkg.pins[pin_idx]
                    tp = toep_by_pin.get(pin_idx)
                    net_name = _get_net_name(tp, eda)
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
                    status = "PASS" if via_count >= _MIN_VIA else "FAIL"
                    if status == "FAIL":
                        fail_pads_by_comp[comp.comp_name].append(pin.name)
                    rows.append({
                        "comp": comp.comp_name,
                        "cmp_layer": layer_name,
                        "pad": pin.name,
                        "signal": net_name,
                        "via": str(via_count),
                        "status": status,
                    })

                # Visualisation – highlight ground pads
                if gnd_indices:
                    safe_name = comp.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe_name}_{layer_name}.png"
                    render_via_check_image(
                        comp, pkg, via_positions, is_bottom, img_path,
                        rule_id=self.rule_id,
                        comp_type="SUS (보강판)",
                        fid_resolved=fid_resolved,
                        signal_layer_name=sig_name,
                        pin_indices=gnd_indices,
                        min_via_count=_MIN_VIA,
                    )
                    images.append({
                        "path": img_path,
                        "title": f"{comp.comp_name} ({layer_name})",
                        "width": 500,
                    })

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        if passed:
            message = "모든 보강판(SUS) GND 패드에 최소 4개의 VIA가 적용되어 있습니다."
        else:
            sentences = [
                f"{comp} 의 GND 패드 {', '.join(pads)} 는 via 4개 이상 설계할 것."
                for comp, pads in fail_pads_by_comp.items()
            ]
            message = " ".join(sentences)

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=message,
            affected_components=list(fail_pads_by_comp.keys()),
            details={"columns": columns, "rows": rows},
            images=images,
        )
