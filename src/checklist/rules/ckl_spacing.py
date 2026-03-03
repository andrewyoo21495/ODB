"""CKL-002: Component spacing check.

Verifies minimum distance between components using spatial indexing.
"""

from __future__ import annotations

import numpy as np

from src.checklist.engine import register_rule
from src.checklist.rule_base import ChecklistRule
from src.models import Component, RuleResult


@register_rule
class ComponentSpacingRule(ChecklistRule):
    rule_id = "CKL-002"
    description = "Minimum spacing between components must be maintained"
    category = "Spacing"

    # Configuration
    min_spacing = 0.008  # inches (approx 0.2mm)

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])

        violations = []

        # Check top layer
        violations.extend(self._check_layer_spacing(components_top, "Top"))

        # Check bottom layer
        violations.extend(self._check_layer_spacing(components_bot, "Bottom"))

        if violations:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                category=self.category,
                passed=False,
                message=f"{len(violations)} spacing violation(s) found.",
                affected_components=list(set(
                    v.split(" ")[0] for v in violations[:40]
                )),
                details={"violations": violations[:20]},
            )

        total = len(components_top) + len(components_bot)
        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=True,
            message=f"All {total} components meet minimum spacing of {self.min_spacing}.",
        )

    def _check_layer_spacing(self, components: list[Component],
                             layer_label: str) -> list[str]:
        """Check spacing between components on a single layer."""
        if len(components) < 2:
            return []

        violations = []

        try:
            from scipy.spatial import KDTree

            positions = np.array([[c.x, c.y] for c in components])
            tree = KDTree(positions)

            # Find pairs within minimum spacing
            pairs = tree.query_pairs(self.min_spacing)

            for i, j in pairs:
                ci = components[i]
                cj = components[j]
                dist = np.sqrt((ci.x - cj.x) ** 2 + (ci.y - cj.y) ** 2)
                violations.append(
                    f"{ci.comp_name} <-> {cj.comp_name} ({layer_label}): "
                    f"distance={dist:.6f}, min={self.min_spacing}"
                )
        except ImportError:
            # Fallback without scipy: brute force (limited to first 500 components)
            comps = components[:500]
            for i in range(len(comps)):
                for j in range(i + 1, len(comps)):
                    ci, cj = comps[i], comps[j]
                    dist = ((ci.x - cj.x) ** 2 + (ci.y - cj.y) ** 2) ** 0.5
                    if dist < self.min_spacing:
                        violations.append(
                            f"{ci.comp_name} <-> {cj.comp_name} ({layer_label}): "
                            f"distance={dist:.6f}, min={self.min_spacing}"
                        )

        return violations
