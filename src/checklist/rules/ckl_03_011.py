"""CKL-03-011: OSC components in bending-vulnerable areas.

Oscillator (OSC) components must not be mounted on protrusions of the PCB
that are vulnerable to bending.  A bending-vulnerable area is a thin
protruding region whose local width is ≤ 8 mm and that protrudes ≥ 2 mm
from the main board body.
"""

from __future__ import annotations

from shapely.geometry import Point as ShapelyPoint

from src.checklist.component_classifier import find_oscillators
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    build_board_polygon,
    find_bending_vulnerable_areas,
)
from src.checklist.rule_base import ChecklistRule
from src.models import Component, RuleResult


def _is_component_in_areas(comp: Component, areas: list) -> bool:
    """Return True if the component centre lies inside any of *areas*."""
    pt = ShapelyPoint(comp.x, comp.y)
    return any(area.contains(pt) for area in areas)


@register_rule
class CKL03011(ChecklistRule):
    rule_id = "CKL-03-011"
    description = (
        "OSC 부품은 벤딩 취약 영역에 배치되지 않아야 합니다"
    )
    category = "Clearance"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        profile = job_data.get("profile")

        board_poly = build_board_polygon(profile)
        vulnerable_areas = find_bending_vulnerable_areas(board_poly)

        columns = ["comp", "cmp_layer", "bending", "status"]
        rows: list[dict] = []

        for comps, layer_name in [
            (components_top, "Top"),
            (components_bot, "Bottom"),
        ]:
            oscs = find_oscillators(comps)

            for osc in oscs:
                in_bending = _is_component_in_areas(osc, vulnerable_areas)
                status = "FAIL" if in_bending else "PASS"

                rows.append({
                    "comp": osc.comp_name,
                    "cmp_layer": layer_name,
                    "bending": str(in_bending).upper(),
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
                f"벤딩 취약 영역에 배치된 OSC 부품이 {fail_count}건 발견되었습니다."
                if not passed
                else "벤딩 취약 영역에 배치된 OSC 부품이 없습니다."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
