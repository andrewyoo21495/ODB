"""CKL-03-016: No INP/SC/SIM/Connector on the opposite side of OSC.

Interposers, Shield Cans, SIM Sockets, and Connectors must not have
pad-level overlap with Oscillator components on the opposite side.

- Outline-only overlap (no pad contact) → PASS
- Pad-to-pad overlap → FAIL
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import (
    find_connectors,
    find_interposers,
    find_oscillators,
    find_shield_cans,
    find_simsockets,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    find_overlapping_components,
    find_pad_overlapping_components,
)
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import RuleResult


@register_rule
class CKL03016(ChecklistRule):
    rule_id = "CKL-03-016"
    description = (
        "인터포저, 쉴드캔, SIM 소켓, 커넥터는 OSC 부품의 "
        "반대면과 패드 중첩이 없어야 합니다"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []
        user_symbols: dict = job_data.get("user_symbols") or {}

        columns = [
            "comp", "cmp_layer", "overlapping_cmp", "part_name",
            "overlap_type", "status",
        ]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_03_016_"))

        for oscs, osc_layer, opp_comps in [
            (find_oscillators(components_top), "Top", components_bot),
            (find_oscillators(components_bot), "Bottom", components_top),
        ]:
            osc_is_bottom = (osc_layer == "Bottom")
            opp_is_bottom = not osc_is_bottom

            opp_interposers = find_interposers(opp_comps)
            opp_shield_cans = find_shield_cans(opp_comps)
            opp_simsockets = find_simsockets(opp_comps)
            opp_connectors = find_connectors(opp_comps)
            opp_targets = (
                opp_interposers + opp_shield_cans
                + opp_simsockets + opp_connectors
            )

            if not opp_targets:
                continue

            for osc in oscs:
                # Step 1: Check pad-level overlap (FAIL)
                pad_overlaps = find_pad_overlapping_components(
                    osc, opp_targets, packages,
                    is_bottom_primary=osc_is_bottom,
                    is_bottom_candidates=opp_is_bottom,
                    user_symbols=user_symbols,
                )
                pad_overlap_ids = {id(c) for c in pad_overlaps}

                # Step 2: Check outline-only overlap (PASS)
                outline_overlaps = find_overlapping_components(
                    osc, opp_targets, packages,
                    is_bottom_primary=osc_is_bottom,
                    is_bottom_candidates=opp_is_bottom,
                )

                overlap_items: list[dict] = []

                # Pad overlaps → FAIL
                for ovl in pad_overlaps:
                    rows.append({
                        "comp": osc.comp_name,
                        "cmp_layer": osc_layer,
                        "overlapping_cmp": ovl.comp_name,
                        "part_name": ovl.part_name or "",
                        "overlap_type": "PAD",
                        "status": "FAIL",
                    })
                    overlap_items.append({"comp": ovl, "status": "FAIL"})

                # Outline-only overlaps (not pad) → PASS
                for ovl in outline_overlaps:
                    if id(ovl) in pad_overlap_ids:
                        continue  # Already reported as FAIL
                    rows.append({
                        "comp": osc.comp_name,
                        "cmp_layer": osc_layer,
                        "overlapping_cmp": ovl.comp_name,
                        "part_name": ovl.part_name or "",
                        "overlap_type": "OUTLINE_ONLY",
                        "status": "PASS",
                    })
                    overlap_items.append({"comp": ovl, "status": "PASS"})

                if overlap_items and any(i["status"] == "FAIL" for i in overlap_items):
                    safe = osc.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{osc_layer}.png"
                    render_overlap_image(
                        osc, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="Opposite-side overlap on OSC",
                        layer_name=osc_layer,
                        primary_label="OSC",
                        primary_is_bottom=osc_is_bottom,
                        overlap_is_bottom=opp_is_bottom,
                        user_symbols=user_symbols,
                    )
                    images.append({"path": img_path,
                                   "title": f"{osc.comp_name} ({osc_layer})",
                                   "width": 500})

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"OSC 반대면과 패드 중첩되는 부품이 {fail_count}건 발견되었습니다."
                if not passed
                else "OSC 반대면과 패드 중첩되는 금지 부품이 없습니다."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={
                "columns": columns,
                "rows": [r for r in rows if r["status"] != "PASS"],
            },
            images=images,
        )
