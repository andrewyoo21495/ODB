"""CKL-003: Component placement zone check.

Verifies that all components are placed within the board outline.
"""

from __future__ import annotations

from src.checklist.engine import register_rule
from src.checklist.rule_base import ChecklistRule
from src.models import Component, Profile, RuleResult


@register_rule
class ComponentPlacementRule(ChecklistRule):
    rule_id = "CKL-003"
    description = "All components must be placed within the board outline"
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        profile = job_data.get("profile")

        if not profile or not profile.surface:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                category=self.category,
                passed=True,
                message="No board profile available for placement check.",
            )

        # Build board outline polygon using shapely
        try:
            from shapely.geometry import Point, Polygon
            from src.visualizer.symbol_renderer import contour_to_vertices

            board_poly = None
            for contour in profile.surface.contours:
                if contour.is_island:
                    verts = contour_to_vertices(contour)
                    if len(verts) >= 3:
                        board_poly = Polygon(verts)
                        break

            if board_poly is None or not board_poly.is_valid:
                return RuleResult(
                    rule_id=self.rule_id,
                    description=self.description,
                    category=self.category,
                    passed=True,
                    message="Could not construct valid board outline polygon.",
                )

            outside = []
            all_comps = (
                [(c, "Top") for c in components_top] +
                [(c, "Bottom") for c in components_bot]
            )

            for comp, side in all_comps:
                pt = Point(comp.x, comp.y)
                if not board_poly.contains(pt):
                    outside.append(f"{comp.comp_name} ({side}): ({comp.x:.4f}, {comp.y:.4f})")

            if outside:
                return RuleResult(
                    rule_id=self.rule_id,
                    description=self.description,
                    category=self.category,
                    passed=False,
                    message=f"{len(outside)} component(s) placed outside board outline.",
                    affected_components=[v.split(" ")[0] for v in outside[:40]],
                    details={"outside_components": outside[:20]},
                )

            total = len(components_top) + len(components_bot)
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                category=self.category,
                passed=True,
                message=f"All {total} components are within the board outline.",
            )

        except ImportError:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                category=self.category,
                passed=True,
                message="Shapely not available - skipping placement check.",
            )
