"""CKL-02-010: SIM socket vs capacitors/inductors (>=2012) on opposite side.

Inspect capacitors and inductors of size 2012 or larger overlapping
the opposite side of SIM socket components.  Check horizontal/vertical
orientation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import (
    find_capacitors, find_inductors, find_simsockets,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    filter_by_size,
    find_outline_boundary_pad_overlapping_components,
    get_orientation_relative_to_outline_edge,
)
from src.checklist.reference_loader import get_part_size_map
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import RuleResult


@register_rule
class CKL02010(ChecklistRule):
    rule_id = "CKL-02-010"
    description = (
        "SIM 소켓: 반대면의 2012 이상 캐패시터/인덕터는 "
        "수평 방향이어야 합니다"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        # Build size maps from reference CSVs
        cap_size_map = get_part_size_map("capacitors_10_list")
        ind_size_map = get_part_size_map("inductors_2s_list")
        size_maps = [cap_size_map, ind_size_map]

        columns = [
            "comp", "cmp_layer", "overlapping_cmp", "part_name",
            "hori/verti", "status",
        ]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_02_010_"))

        for sim_comps, sim_layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            sim_is_bottom = sim_layer == "Bottom"
            cap_is_bottom = not sim_is_bottom

            sims = find_simsockets(sim_comps)
            opp_caps = find_capacitors(opp_comps)
            opp_inds = find_inductors(opp_comps)
            opp_targets = opp_caps + opp_inds

            if not sims or not opp_targets:
                continue

            for sim in sims:
                # Check if cap/ind pads cross the SIM socket outline boundary
                overlaps = find_outline_boundary_pad_overlapping_components(
                    sim, opp_targets, packages,
                    is_bottom_primary=sim_is_bottom,
                    is_bottom_candidates=cap_is_bottom,
                )
                # Filter to size >= 2012
                filtered = filter_by_size(overlaps, 2012, size_maps, packages)

                overlap_items: list[dict] = []
                for comp, sz in filtered:
                    # Orientation relative to the nearest SIM socket outline edge
                    orientation = get_orientation_relative_to_outline_edge(
                        comp, sim, packages,
                        comp_is_bottom=cap_is_bottom,
                        outline_is_bottom=sim_is_bottom,
                    )
                    status = "PASS" if orientation == "Horizontal" else "FAIL"
                    rows.append({
                        "comp": sim.comp_name,
                        "cmp_layer": sim_layer,
                        "overlapping_cmp": comp.comp_name,
                        "part_name": comp.part_name or "",
                        "hori/verti": orientation,
                        "status": status,
                    })
                    overlap_items.append({
                        "comp": comp, "status": status,
                        "detail": orientation,
                    })

                if overlap_items:
                    safe = sim.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{sim_layer}.png"
                    render_overlap_image(
                        sim, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="Cap/inductor orientation",
                        layer_name=sim_layer,
                        primary_label="SIM Socket",
                        overlap_label="Cap/Inductor",
                    )
                    images.append({"path": img_path,
                                   "title": f"{sim.comp_name} ({sim_layer})",
                                   "width": 500})

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"SIM 소켓 인근에서 수평 방향이 아닌 부품이 {fail_count}건 발견되었습니다."
                if not passed
                else "SIM 소켓 인근 모든 부품이 적절한 방향으로 배치되어 있습니다."
            ),
            affected_components=[
                r["overlapping_cmp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
