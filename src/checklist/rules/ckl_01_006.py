"""CKL-01-006: RF Receptacle pad vs 5-pin filter pad overlap on opposite layer.

Verify that RF Receptacle pads do not overlap with 5-pin filter pads on the
opposite layer of the PCB.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import find_filters, find_rf_components
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import find_pad_overlapping_components
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import RuleResult


@register_rule
class CKL01006(ChecklistRule):
    rule_id = "CKL-01-006"
    description = (
        "RF 리셉터클 패드는 반대면 5핀 필터 패드와 "
        "중첩되지 않아야 합니다"
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
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_01_006_"))

        for rf_comps, rf_layer, opp_comps in [
            (find_rf_components(components_top), "Top", components_bot),
            (find_rf_components(components_bot), "Bottom", components_top),
        ]:
            opp_filters = find_filters(opp_comps, packages, pin_count=5)
            if not opp_filters:
                for rf in rf_comps:
                    rows.append({
                        "comp": rf.comp_name,
                        "cmp_layer": rf_layer,
                        "overlapping_cmp": "-",
                        "status": "PASS",
                    })
                continue

            for rf in rf_comps:
                pad_overlaps = find_pad_overlapping_components(
                    rf, opp_filters, packages,
                )

                overlap_items: list[dict] = []
                if pad_overlaps:
                    for ovl in pad_overlaps:
                        rows.append({
                            "comp": rf.comp_name,
                            "cmp_layer": rf_layer,
                            "overlapping_cmp": ovl.comp_name,
                            "status": "FAIL",
                        })
                        overlap_items.append({"comp": ovl, "status": "FAIL"})
                else:
                    rows.append({
                        "comp": rf.comp_name,
                        "cmp_layer": rf_layer,
                        "overlapping_cmp": "-",
                        "status": "PASS",
                    })

                if overlap_items:
                    safe = rf.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{rf_layer}.png"
                    render_overlap_image(
                        rf, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="5-pin filter pad overlap",
                        layer_name=rf_layer,
                        primary_label="RF Receptacle",
                        overlap_label="5-pin Filter",
                    )
                    images.append({"path": img_path,
                                   "title": f"{rf.comp_name} ({rf_layer})",
                                   "width": 500})

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"RF 리셉터클 패드와 반대면 5핀 필터 패드의 중첩이 "
                f"{fail_count}건 발견되었습니다."
                if not passed
                else "RF 리셉터클 패드와 반대면 5핀 필터의 중첩이 없습니다."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
