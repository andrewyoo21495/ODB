"""CKL-02-007: Capacitors/inductors near shield can inner walls — clearance check.

All capacitors or inductors located near the inner walls of a Shield Can must
be placed with a clearance of at least 0.3 mm from those inner walls.
"""

from __future__ import annotations

from src.checklist.component_classifier import (
    find_capacitors,
    find_inductors,
    find_shield_cans,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    _get_pad_centers,
    detect_inner_walls,
    find_nearest_inner_wall,
    is_near_inner_wall,
)
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult

_CLEARANCE_MM = 0.3   # FAIL threshold
_DETECTION_MM = 0.5   # Search radius for "near inner wall" candidates


def _min_dist_to_walls(
    comp,
    packages,
    inner_walls,
    *,
    is_bottom: bool = False,
) -> float:
    """Return the minimum distance (mm) from *comp* to any inner wall.

    Tests both the component board centre and all pad centres so that the
    reported distance reflects the closest point of the component footprint.
    """
    result = find_nearest_inner_wall((comp.x, comp.y), inner_walls)
    min_dist = result[1] if result is not None else float("inf")

    for px, py in _get_pad_centers(comp, packages, is_bottom=is_bottom):
        r = find_nearest_inner_wall((px, py), inner_walls)
        if r is not None:
            min_dist = min(min_dist, r[1])

    return min_dist


@register_rule
class CKL02007(ChecklistRule):
    rule_id = "CKL-02-007"
    description = (
        "All capacitors or inductors near the inner walls of a Shield Can "
        "must be placed with a clearance of at least 0.3 mm."
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        columns = [
            "comp", "cmp_layer", "neighbor_cmp", "part_name",
            "distance", "status",
        ]
        rows: list[dict] = []

        for sc_comps, sc_layer in [
            (components_top, "Top"),
            (components_bot, "Bottom"),
        ]:
            sc_is_bottom = sc_layer == "Bottom"

            shield_cans = find_shield_cans(sc_comps)
            if not shield_cans:
                continue

            # Capacitors and inductors on the same layer as the shield can
            candidates = find_capacitors(sc_comps) + find_inductors(sc_comps)
            if not candidates:
                continue

            for sc in shield_cans:
                inner_walls = detect_inner_walls(
                    sc, packages, is_bottom=sc_is_bottom
                )
                if not inner_walls:
                    continue  # Shield can has no inner walls — skip

                for comp in candidates:
                    if not is_near_inner_wall(
                        comp,
                        sc,
                        packages,
                        distance_threshold=_DETECTION_MM,
                        comp_is_bottom=sc_is_bottom,
                        sc_is_bottom=sc_is_bottom,
                        inner_walls=inner_walls,
                    ):
                        continue

                    dist = _min_dist_to_walls(
                        comp, packages, inner_walls, is_bottom=sc_is_bottom
                    )
                    status = "FAIL" if dist < _CLEARANCE_MM else "PASS"
                    rows.append({
                        "comp": sc.comp_name,
                        "cmp_layer": sc_layer,
                        "neighbor_cmp": comp.comp_name,
                        "part_name": comp.part_name or "",
                        "distance": round(dist, 4),
                        "status": status,
                    })

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"{fail_count} capacitor(s)/inductor(s) placed within "
                f"{_CLEARANCE_MM} mm of a shield can inner wall."
                if not passed
                else "All capacitors and inductors near shield can inner walls "
                "meet the 0.3 mm clearance requirement."
            ),
            affected_components=[
                r["neighbor_cmp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
