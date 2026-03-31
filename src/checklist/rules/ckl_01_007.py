"""CKL-01-007: Air Pressure Sensor overlap with ICs/shield cans/connectors.

Verify that the sensing area of the Air Pressure Sensor (part_name 1209-002567)
does not overlap with IC outlines, shield can pads, or connector pads on the
opposite layer.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import (
    find_connectors,
    find_ics,
    find_shield_cans,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import find_overlapping_components
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import Component, RuleResult

_AIR_PRESSURE_SENSOR_PART = "1209-002567"


def _find_air_pressure_sensors(components: list[Component]) -> list[Component]:
    """Return Air Pressure Sensor components (part_name == 1209-002567)."""
    return [
        c for c in components
        if (c.part_name or "") == _AIR_PRESSURE_SENSOR_PART
    ]


@register_rule
class CKL01007(ChecklistRule):
    rule_id = "CKL-01-007"
    description = (
        "Air Pressure Sensor (1209-002567) sensing area must not overlap "
        "with IC outlines, shield can pads, or connector pads on the opposite layer"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        columns = ["comp", "cmp_layer", "overlapping_cmp", "status"]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_01_007_"))

        for sensors, sensor_layer, opp_comps in [
            (_find_air_pressure_sensors(components_top), "Top", components_bot),
            (_find_air_pressure_sensors(components_bot), "Bottom", components_top),
        ]:
            if not sensors:
                continue

            opp_ics = find_ics(opp_comps)
            opp_shield_cans = find_shield_cans(opp_comps)
            opp_connectors = find_connectors(opp_comps)
            opp_targets = opp_ics + opp_shield_cans + opp_connectors

            for sensor in sensors:
                overlaps = find_overlapping_components(
                    sensor, opp_targets, packages,
                )

                overlap_items: list[dict] = []
                if overlaps:
                    for ovl in overlaps:
                        rows.append({
                            "comp": sensor.comp_name,
                            "cmp_layer": sensor_layer,
                            "overlapping_cmp": ovl.comp_name,
                            "status": "FAIL",
                        })
                        overlap_items.append({"comp": ovl, "status": "FAIL"})
                else:
                    rows.append({
                        "comp": sensor.comp_name,
                        "cmp_layer": sensor_layer,
                        "overlapping_cmp": "-",
                        "status": "PASS",
                    })

                if overlap_items:
                    safe = sensor.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{sensor_layer}.png"
                    render_overlap_image(
                        sensor, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="Sensing area overlap",
                        layer_name=sensor_layer,
                        primary_label="Air Pressure Sensor",
                    )
                    images.append({"path": img_path,
                                   "title": f"{sensor.comp_name} ({sensor_layer})",
                                   "width": 500})

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"{fail_count} Air Pressure Sensor overlap(s) with opposite-layer "
                f"IC/shield can/connector found."
                if not passed
                else "No Air Pressure Sensor overlaps with opposite-layer components."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
