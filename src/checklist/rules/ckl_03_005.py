"""CKL-03-005: VIA presence check for 3-axis/6-axis sensor pads.

For axis sensor components (identified by part_name in
references/axis_sensors.csv), every pad must have at least one VIA.
A pad with zero VIAs is flagged FAIL.
"""

from __future__ import annotations

from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    build_toeprint_lookup,
    build_via_position_set,
    count_vias_at_pad,
)
from src.checklist.reference_loader import get_managed_part_names
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


@register_rule
class CKL03005(ChecklistRule):
    rule_id = "CKL-03-005"
    description = (
        "Axis sensor pads must each have at least one VIA"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        layers_data = job_data.get("layers_data", {})
        packages = eda.packages if eda else []

        sensor_parts = get_managed_part_names("axis_sensors")

        # Build VIA position sets per layer
        via_top: set[tuple[float, float]] = set()
        via_bot: set[tuple[float, float]] = set()
        if eda and layers_data:
            via_top = build_via_position_set(eda, layers_data, is_bottom=False)
            via_bot = build_via_position_set(eda, layers_data, is_bottom=True)

        columns = ["comp", "cmp_layer", "pad", "via", "status"]
        rows: list[dict] = []

        for comps, layer_name, is_bottom in [
            (components_top, "Top", False),
            (components_bot, "Bottom", True),
        ]:
            via_positions = via_bot if is_bottom else via_top
            sensors = [c for c in comps if (c.part_name or "") in sensor_parts]

            for comp in sensors:
                if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
                    continue
                pkg = packages[comp.pkg_ref]

                toep_by_pin = build_toeprint_lookup(comp, pkg)

                for pin_idx, pin in enumerate(pkg.pins):
                    tp = toep_by_pin.get(pin_idx)
                    via_count = count_vias_at_pad(
                        comp, pin.center.x, pin.center.y,
                        via_positions, is_bottom=is_bottom,
                        toeprint=tp, pin=pin,
                    )
                    rows.append({
                        "comp": comp.comp_name,
                        "cmp_layer": layer_name,
                        "pad": pin.name,
                        "via": str(via_count),
                        "status": "PASS" if via_count > 0 else "FAIL",
                    })

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"{fail_count} axis sensor pad(s) without a VIA detected."
                if not passed
                else "All axis sensor pads have at least one VIA."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
