"""CKL-01-003: QUALCOMM PMIC opposite-side component containment check.

QUALCOMM PMICs must be placed such that IC components on the opposite side
satisfy one of:
  - No PAD-PAD overlap with the PMIC → PASS
  - PMIC pads are completely contained within the opposite-side IC → PASS
  - PMIC pads only partially overlap the opposite-side IC → FAIL
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import find_ics
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    find_outline_overlapping_components,
    find_pad_overlapping_components,
)
from src.checklist.geometry_utils.overlap import _get_pad_union
from src.checklist.geometry_utils.polygon import _resolve_footprint
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
        "QUALCOMM PMIC는 반대면 IC가 PMIC 외곽선 내에 "
        "포함되도록 배치해야 합니다"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        qualcomm_parts = _get_qualcomm_pmic_part_names()

        columns = [
            "comp", "cmp_layer", "overlapping_cmp",
            "pad_overlap", "containment", "status",
        ]
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

            # Only check IC components on the opposite side
            opp_ics = find_ics(opp_comps)

            for pmic in pmic_comps:
                if pmic.pkg_ref < 0 or pmic.pkg_ref >= len(packages):
                    continue

                pmic_is_bottom = (layer_name == "Bottom")
                opp_is_bottom = not pmic_is_bottom

                # Step 1: find ICs whose outline overlaps with PMIC
                hit_comps = find_outline_overlapping_components(
                    pmic, opp_ics, packages,
                    is_bottom_primary=pmic_is_bottom,
                    is_bottom_candidates=opp_is_bottom,
                )

                overlap_items: list[dict] = []
                for opp in hit_comps:
                    # Step 2: check PAD-PAD overlap
                    pad_hits = find_pad_overlapping_components(
                        pmic, [opp], packages,
                        is_bottom_primary=pmic_is_bottom,
                        is_bottom_candidates=opp_is_bottom,
                    )
                    if not pad_hits:
                        # No PAD overlap → PASS
                        rows.append({
                            "comp": pmic.comp_name,
                            "cmp_layer": layer_name,
                            "overlapping_cmp": opp.comp_name,
                            "pad_overlap": "FALSE",
                            "containment": "N/A",
                            "status": "PASS",
                        })
                        overlap_items.append({
                            "comp": opp, "status": "PASS",
                            "detail": "No pad overlap",
                        })
                        continue

                    # Step 3: PAD overlap exists — check containment
                    # FULL (PASS) when either side completely contains the
                    # other:
                    #   A) PMIC pads are fully inside the opp IC, OR
                    #   B) Opp IC pads are fully inside the PMIC outline
                    #      (opp IC is small enough to sit entirely within
                    #       the PMIC).
                    pmic_pads = _get_pad_union(
                        pmic, packages, is_bottom=pmic_is_bottom,
                    )
                    pmic_fp = _resolve_footprint(
                        pmic, packages, is_bottom=pmic_is_bottom,
                    )
                    opp_fp = _resolve_footprint(
                        opp, packages, is_bottom=opp_is_bottom,
                    )
                    opp_pads = _get_pad_union(
                        opp, packages, is_bottom=opp_is_bottom,
                    )

                    fully_contained = False
                    # A) PMIC inside opp IC
                    if pmic_pads is not None:
                        if opp_fp is not None and opp_fp.contains(pmic_pads):
                            fully_contained = True
                        elif opp_pads is not None and opp_pads.contains(pmic_pads):
                            fully_contained = True
                    # B) Opp IC inside PMIC
                    if not fully_contained and opp_pads is not None:
                        if pmic_fp is not None and pmic_fp.contains(opp_pads):
                            fully_contained = True
                        elif pmic_pads is not None and pmic_pads.contains(opp_pads):
                            fully_contained = True

                    if fully_contained:
                        status = "PASS"
                        containment = "FULL"
                    else:
                        status = "FAIL"
                        containment = "PARTIAL"

                    rows.append({
                        "comp": pmic.comp_name,
                        "cmp_layer": layer_name,
                        "overlapping_cmp": opp.comp_name,
                        "pad_overlap": "TRUE",
                        "containment": containment,
                        "status": status,
                    })
                    overlap_items.append({
                        "comp": opp, "status": status,
                        "detail": containment,
                    })

                if not hit_comps:
                    rows.append({
                        "comp": pmic.comp_name,
                        "cmp_layer": layer_name,
                        "overlapping_cmp": "-",
                        "pad_overlap": "FALSE",
                        "containment": "N/A",
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
                f"QUALCOMM PMIC 외곽선에 겹치는 반대면 IC가 "
                f"{fail_count}건 감지되었습니다."
                if not passed
                else "반대면 IC가 QUALCOMM PMIC 외곽선에 겹치지 않습니다."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns,
                     "rows": [r for r in rows if r["status"] == "FAIL"]},
            images=images,
        )
