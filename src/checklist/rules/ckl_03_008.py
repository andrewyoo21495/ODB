"""CKL-03-008: Sensor component pads must each have at least one VIA.

For each sensor component identified by part_name in references/regular_sensors.csv,
every pad must have at least one VIA applied.  A pad with zero VIAs is flagged FAIL.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    build_toeprint_lookup,
    build_via_position_set,
    count_vias_at_pad,
    lookup_resolved_pads_for_pin,
)
from src.checklist.reference_loader import get_managed_part_names
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.via_check_viz import render_via_check_image
from src.models import RuleResult
from src.visualizer.fid_lookup import (
    _find_top_bottom_signal_layers,
    build_fid_map,
    resolve_fid_features,
)


@register_rule
class CKL03008(ChecklistRule):
    rule_id = "CKL-03-008"
    description = (
        "Sensor component pads must each have at least 4 VIAs applied"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        layers_data = job_data.get("layers_data", {})
        packages = eda.packages if eda else []

        sensor_parts = get_managed_part_names("regular_sensors")

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
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_03_008_"))

        for comps, layer_name, is_bottom in [
            (components_top, "Top", False),
            (components_bot, "Bottom", True),
        ]:
            via_positions = via_bot if is_bottom else via_top
            sig_name = bot_sig_name if is_bottom else top_sig_name
            sensors = [c for c in comps if (c.part_name or "") in sensor_parts]

            for comp in sensors:
                if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
                    continue
                pkg = packages[comp.pkg_ref]

                toep_by_pin = build_toeprint_lookup(comp, pkg)

                for pin_idx, pin in enumerate(pkg.pins):
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
                        "status": "PASS" if via_count >= 1 else "FAIL",
                    })

                # Generate visualisation image for this sensor
                safe_name = comp.comp_name.replace("/", "_")
                img_path = image_dir / f"{safe_name}_{layer_name}.png"
                render_via_check_image(
                    comp, pkg, via_positions, is_bottom, img_path,
                    rule_id=self.rule_id,
                    comp_type="Sensor",
                    fid_resolved=fid_resolved,
                    signal_layer_name=sig_name,
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
                f"{fail_count} sensor pad(s) without a VIA detected."
                if not passed
                else "All sensor component pads have at least one VIA."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
