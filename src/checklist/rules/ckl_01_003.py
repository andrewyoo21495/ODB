"""CKL-01-003: QUALCOMM PMIC opposite-side component containment check.

QUALCOMM PMICs must be placed such that components on the opposite side
do NOT overlap with the PMIC's component outline.  Any opposite-side
component whose footprint intersects the PMIC outline is flagged FAIL.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.engine import register_rule
from src.checklist.geometry_utils import overlaps_component_outline
from src.checklist.reference_loader import load_reference_csv
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import RuleResult


def _get_qualcomm_pmic_part_names() -> set[str]:
    """Return part_names of QUALCOMM PMICs from the reference CSV."""
    rows = load_reference_csv("pmic_list")
    return {
        r["part_name"]
        for r in rows
        if r.get("part_name") and r.get("maker", "").upper().startswith("QUALCO")
    }


@register_rule
class CKL01003(ChecklistRule):
    rule_id = "CKL-01-003"
    description = (
        "QUALCOMM PMIC는 반대면 부품이 PMIC 외곽선 내에 "
        "포함되도록 배치해야 합니다"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        qualcomm_parts = _get_qualcomm_pmic_part_names()

        columns = ["comp", "cmp_layer", "overlapping_cmp", "outline", "status"]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_01_003_"))

        for comps, layer_name, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            pmic_comps = [
                c for c in comps
                if (c.part_name or "") in qualcomm_parts
            ]

            for pmic in pmic_comps:
                if pmic.pkg_ref < 0 or pmic.pkg_ref >= len(packages):
                    continue

                overlap_items: list[dict] = []
                for opp in opp_comps:
                    if opp.pkg_ref < 0 or opp.pkg_ref >= len(packages):
                        continue
                    overlaps = overlaps_component_outline(
                        opp, pmic, packages,
                    )
                    if overlaps:
                        rows.append({
                            "comp": pmic.comp_name,
                            "cmp_layer": layer_name,
                            "overlapping_cmp": opp.comp_name,
                            "outline": "TRUE",
                            "status": "FAIL",
                        })
                        overlap_items.append({
                            "comp": opp, "status": "FAIL",
                        })

                if not overlap_items:
                    rows.append({
                        "comp": pmic.comp_name,
                        "cmp_layer": layer_name,
                        "overlapping_cmp": "-",
                        "outline": "FALSE",
                        "status": "PASS",
                    })

                if overlap_items:
                    safe = pmic.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{layer_name}.png"
                    render_overlap_image(
                        pmic, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="PMIC outline containment",
                        layer_name=layer_name,
                        primary_label="PMIC",
                    )
                    images.append({"path": img_path,
                                   "title": f"{pmic.comp_name} ({layer_name})",
                                   "width": 500})

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"QUALCOMM PMIC 외곽선을 벗어나는 반대면 부품이 "
                f"{fail_count}건 감지되었습니다."
                if not passed
                else "반대면 부품이 QUALCOMM PMIC 외곽선을 벗어나지 않습니다."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
