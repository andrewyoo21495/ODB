"""CKL-03-013: VIA presence check for MIC pads.

Each pad of every MIC component must have at least one VIA placed at its
location.  A pad with zero VIAs is flagged as FAIL.
"""

from __future__ import annotations

from src.checklist.component_classifier import find_mics
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    build_toeprint_lookup,
    build_via_position_set,
    count_vias_at_pad,
)
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


@register_rule
class CKL03013(ChecklistRule):
    rule_id = "CKL-03-013"
    description = "Each MIC pad must have at least one VIA"
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        layers_data = job_data.get("layers_data", {})
        packages = eda.packages if eda else []

        # Build VIA position set once
        via_positions: set[tuple[float, float]] = set()
        if eda and layers_data:
            via_positions = build_via_position_set(eda, layers_data)

        columns = ["comp", "cmp_layer", "pad", "via", "status"]
        rows: list[dict] = []

        for comps, layer_name, is_bottom in [
            (components_top, "Top", False),
            (components_bot, "Bottom", True),
        ]:
            mics = find_mics(comps)

            for mic in mics:
                if mic.pkg_ref < 0 or mic.pkg_ref >= len(packages):
                    continue
                pkg = packages[mic.pkg_ref]

                toep_by_pin = build_toeprint_lookup(mic, pkg)

                for pin_idx, pin in enumerate(pkg.pins):
                    tp = toep_by_pin.get(pin_idx)
                    via_count = count_vias_at_pad(
                        mic, pin.center.x, pin.center.y,
                        via_positions, is_bottom=is_bottom,
                        toeprint=tp,
                    )
                    rows.append({
                        "comp": mic.comp_name,
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
                f"{fail_count} MIC pad(s) without a VIA detected."
                if not passed
                else "All MIC pads have at least one VIA."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
