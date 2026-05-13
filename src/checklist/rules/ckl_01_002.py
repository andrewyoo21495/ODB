"""CKL-01-002: VIA presence check for outermost NC pads on PMICs.

For PMIC components (identified by part_name in references/pmic_list.csv),
each outermost (outer perimeter) pad that is NC (Not Connected) must have
at least one VIA.  An NC pad is one with no traces, lines, or copper planes
on the component's signal layer.  Connected pads are excluded from the
check entirely.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import find_pmics
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    build_toeprint_lookup,
    build_via_position_set,
    count_vias_at_pad,
    find_outermost_pin_indices,
    is_pad_nc_by_signal_layer,
    lookup_resolved_pads_for_pin,
)
from src.checklist.reference_loader import get_managed_part_names
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.via_check_viz import render_via_check_image
from src.models import RuleResult
from src.visualizer.fid_lookup import (
    build_fid_map,
    resolve_fid_features,
    _find_top_bottom_signal_layers,
)


@register_rule
class CKL01002(ChecklistRule):
    rule_id = "CKL-01-002"
    description = (
        "PMIC 부품의 최외곽 패드에 VIA 설계가 적용되어야 합니다"
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

        columns = ["comp", "cmp_layer", "pad_name", "via", "status"]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_01_002_"))

        for comps, layer_name, is_bottom in [
            (components_top, "Top", False),
            (components_bot, "Bottom", True),
        ]:
            via_positions = via_bot if is_bottom else via_top
            sig_name = bot_sig_name if is_bottom else top_sig_name
            csv_pmics = [c for c in comps if (c.part_name or "") in pmic_parts]
            prop_pmics = find_pmics(comps)
            seen = set()
            pmic_comps = []
            for c in csv_pmics + prop_pmics:
                if c.comp_name not in seen:
                    seen.add(c.comp_name)
                    pmic_comps.append(c)

            for comp in pmic_comps:
                if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
                    continue
                pkg = packages[comp.pkg_ref]

                if not pkg.pins:
                    continue

                outermost_indices = find_outermost_pin_indices(pkg.pins)
                toep_by_pin = build_toeprint_lookup(comp, pkg)
                nc_map: dict[int, bool] = {}

                for pin_idx in sorted(outermost_indices):
                    pin = pkg.pins[pin_idx]
                    tp = toep_by_pin.get(pin_idx)
                    rpads = lookup_resolved_pads_for_pin(
                        fid_resolved, comp, is_bottom,
                        pin_idx, signal_layer_name=sig_name,
                    )

                    nc = is_pad_nc_by_signal_layer(
                        comp, pin, is_bottom, layers_data,
                        signal_layer_name=sig_name,
                        resolved_pads=rpads,
                        toeprint=tp,
                    )
                    nc_map[pin_idx] = nc

                    # Only NC pads are checked; connected pads are skipped.
                    if not nc:
                        continue

                    via_count = count_vias_at_pad(
                        comp, pin.center.x, pin.center.y,
                        via_positions, is_bottom=is_bottom,
                        toeprint=tp, pin=pin,
                        resolved_pads=rpads,
                    )
                    has_via = via_count > 0
                    status = "PASS" if has_via else "FAIL"

                    rows.append({
                        "comp": comp.comp_name,
                        "cmp_layer": layer_name,
                        "pad_name": pin.name,
                        "via": "TRUE" if has_via else "FALSE",
                        "status": status,
                    })

                # Generate visualisation image for this PMIC
                safe_name = comp.comp_name.replace("/", "_")
                img_path = image_dir / f"{safe_name}_{layer_name}.png"
                render_via_check_image(
                    comp, pkg, via_positions, is_bottom, img_path,
                    rule_id=self.rule_id,
                    comp_type="PMIC (outermost)",
                    fid_resolved=fid_resolved,
                    signal_layer_name=sig_name,
                    pin_indices=outermost_indices,
                    eda_data=eda,
                    layers_data=layers_data,
                    nc_map=nc_map,
                    nc_is_fail=True,
                )
                images.append({
                    "path": img_path,
                    "title": f"{comp.comp_name} ({layer_name})",
                    "width": 500,
                })

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        if not rows:
            msg = "PMIC 부품에서 NC 최외곽 패드가 발견되지 않았습니다."
        elif not passed:
            msg = (
                f"VIA가 없는 NC 최외곽 PMIC 패드가 {fail_count}건"
                f" 감지되었습니다."
            )
        else:
            msg = "모든 NC 최외곽 PMIC 패드에 VIA 설계가 적용되어 있습니다."

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
