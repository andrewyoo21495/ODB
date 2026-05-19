"""CKL-02-007: Shield Can inner wall clearance check.

For each Shield Can on Top and Bottom layers:

1. Detect inner-wall pads — SC pads that do NOT follow the outer component
   outline (i.e. they run inward, subdividing the interior).
2. Find capacitors and inductors located inside the SC.
3. Verify that each such component maintains at least 0.3 mm clearance
   from the nearest inner wall pad.

Components closer than the threshold are reported as FAIL.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from shapely.geometry import Point as ShapelyPoint

from src.checklist.component_classifier import (
    find_capacitors, find_inductors, find_shield_cans,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    _resolve_container_interior,
    detect_inner_walls,
    find_nearest_inner_wall,
    _get_pad_centers,
)
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import RuleResult

MIN_CLEARANCE_MM = 0.3


def _min_distance_to_inner_walls(
    comp, packages, inner_walls, *, is_bottom: bool = False,
) -> float | None:
    """Return the minimum distance from *comp* (centre + pads) to inner walls.

    Returns None when inner_walls is empty.
    """
    if not inner_walls:
        return None

    result = find_nearest_inner_wall((comp.x, comp.y), inner_walls)
    best = result[1] if result else float("inf")

    pad_centers = _get_pad_centers(comp, packages, is_bottom=is_bottom)
    for px, py in pad_centers:
        r = find_nearest_inner_wall((px, py), inner_walls)
        if r is not None and r[1] < best:
            best = r[1]

    return best


@register_rule
class CKL02007(ChecklistRule):
    rule_id = "CKL-02-007"
    description = (
        "쉴드캔 내벽과 내부 캐패시터/인덕터 간 이격 거리가 "
        f"{MIN_CLEARANCE_MM} mm 이상이어야 합니다."
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        columns = [
            "comp", "comp_layer", "shield_can", "distance_mm", "status",
        ]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_02_007_"))

        for comps, layer_name, is_bottom in [
            (components_top, "Top", False),
            (components_bot, "Bottom", True),
        ]:
            if not comps:
                continue

            shield_cans = find_shield_cans(comps)
            if not shield_cans:
                continue

            targets = find_capacitors(comps) + find_inductors(comps)

            for sc in shield_cans:
                inner_walls = detect_inner_walls(
                    sc, packages, is_bottom=is_bottom,
                )

                # Check clearance for targets inside this SC (only if inner walls exist).
                fail_items: list[dict] = []
                if inner_walls and targets:
                    interior = _resolve_container_interior(
                        sc, packages, is_bottom=is_bottom,
                    )
                    if interior is not None and not interior.is_empty:
                        for t in targets:
                            t_pt = ShapelyPoint(t.x, t.y)
                            if not interior.contains(t_pt):
                                continue

                            dist = _min_distance_to_inner_walls(
                                t, packages, inner_walls,
                                is_bottom=is_bottom,
                            )
                            if dist is None:
                                continue

                            if dist >= MIN_CLEARANCE_MM:
                                continue

                            rows.append({
                                "comp": t.comp_name,
                                "comp_layer": layer_name,
                                "shield_can": sc.comp_name,
                                "distance_mm": round(dist, 3),
                                "status": "FAIL",
                            })
                            fail_items.append({
                                "comp": t,
                                "status": "FAIL",
                                "distance": dist,
                                "min_distance": MIN_CLEARANCE_MM,
                            })

                # Always render image for every SC.
                safe = sc.comp_name.replace("/", "_")
                img_path = image_dir / f"{safe}_{layer_name.lower()}.png"
                n_fail = len(fail_items)
                n_iw = len(inner_walls) if inner_walls else 0
                render_overlap_image(
                    sc, packages, fail_items, comps, img_path,
                    rule_id=self.rule_id,
                    title="Inner wall clearance",
                    layer_name=layer_name,
                    primary_label="Shield Can",
                    overlap_label="Cap/Ind",
                    primary_is_bottom=is_bottom,
                    overlap_is_bottom=is_bottom,
                    inner_walls=inner_walls or [],
                )
                images.append({
                    "path": img_path,
                    "title": (
                        f"{sc.comp_name} ({layer_name}) — "
                        f"{n_iw} inner wall(s), {n_fail} FAIL"
                    ),
                    "width": 500,
                })

        fail_count = len(rows)
        passed_all = fail_count == 0

        if passed_all:
            message = (
                "모든 캐패시터/인덕터가 쉴드캔 내벽과 "
                f"{MIN_CLEARANCE_MM} mm 이상 이격되어 있습니다."
            )
        else:
            message = (
                f"{fail_count}개의 부품이 쉴드캔 내벽과 "
                f"{MIN_CLEARANCE_MM} mm 미만으로 이격되어 있습니다."
            )

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed_all,
            message=message,
            affected_components=[r["comp"] for r in rows],
            details={"columns": columns, "rows": rows},
            images=images,
        )
