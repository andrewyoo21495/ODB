"""CKL-02-007: Shield Can inner wall detection and visualisation.

For each Shield Can component on Top and Bottom layers, detect inner wall
segments (pads that lie inside the outer boundary) and render them in
fluorescent yellow-green so their location can be verified visually.

This is a debugging / verification step before the full clearance check
against adjacent capacitors and inductors is enabled.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import find_shield_cans
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import detect_inner_walls
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import RuleResult


@register_rule
class CKL02007(ChecklistRule):
    rule_id = "CKL-02-007"
    description = (
        "Shield Can inner wall detection: verify that inner wall segments "
        "are correctly identified (fluorescent highlight in result images)"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        columns = ["comp", "cmp_layer", "inner_wall_count", "status"]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_02_007_"))

        for sc_comps, sc_layer in [
            (components_top, "Top"),
            (components_bot, "Bottom"),
        ]:
            sc_is_bottom = sc_layer == "Bottom"
            shield_cans = find_shield_cans(sc_comps)
            if not shield_cans:
                continue

            for sc in shield_cans:
                inner_walls = detect_inner_walls(
                    sc, packages, is_bottom=sc_is_bottom
                )
                wall_count = len(inner_walls)

                rows.append({
                    "comp": sc.comp_name,
                    "cmp_layer": sc_layer,
                    "inner_wall_count": wall_count,
                    "status": "Found" if wall_count > 0 else "Not found",
                })

                if not inner_walls:
                    continue

                safe = sc.comp_name.replace("/", "_")
                img_path = image_dir / f"{safe}_{sc_layer}.png"
                render_overlap_image(
                    sc, packages, [], sc_comps, img_path,
                    rule_id=self.rule_id,
                    title="Inner wall detection",
                    layer_name=sc_layer,
                    primary_label="Shield Can",
                    overlap_label="",
                    primary_is_bottom=sc_is_bottom,
                    overlap_is_bottom=sc_is_bottom,
                    inner_walls=inner_walls,
                )
                images.append({
                    "path": img_path,
                    "title": f"{sc.comp_name} ({sc_layer}) — {wall_count} inner wall(s)",
                    "width": 500,
                })

        found_count = sum(1 for r in rows if r["status"] == "Found")

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=True,
            message=(
                f"{found_count} shield can(s) with inner walls detected "
                f"(out of {len(rows)} total). See images for verification."
                if rows
                else "No Shield Can components found."
            ),
            affected_components=[],
            details={"columns": columns, "rows": rows},
            images=images,
            recommended=True,
        )
