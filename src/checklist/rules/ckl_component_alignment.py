"""CKL-001: Component alignment check.

Verifies that specific capacitors on the Top layer are horizontally aligned
with connectors on the Bottom layer.
"""

from __future__ import annotations

import math

from src.checklist.engine import register_rule
from src.checklist.rule_base import ChecklistRule
from src.models import Component, RuleResult


@register_rule
class ComponentAlignmentRule(ChecklistRule):
    rule_id = "CKL-001"
    description = "Capacitors on Top layer must be horizontally aligned with connectors on Bottom layer"
    category = "Alignment"

    # Configuration
    alignment_tolerance = 0.010  # inches (or mm depending on units)
    capacitor_prefixes = ("C",)
    connector_prefixes = ("J", "CN", "CONN")

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])

        # Find capacitors on top
        top_caps = [c for c in components_top
                    if any(c.comp_name.startswith(p) for p in self.capacitor_prefixes)]

        # Find connectors on bottom
        bot_connectors = [c for c in components_bot
                          if any(c.comp_name.startswith(p) for p in self.connector_prefixes)]

        if not top_caps or not bot_connectors:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                category=self.category,
                passed=True,
                message="No applicable capacitor-connector pairs found.",
            )

        misaligned = []
        for cap in top_caps:
            # Find the nearest connector on the bottom
            nearest_conn = min(
                bot_connectors,
                key=lambda c: abs(c.x - cap.x) + abs(c.y - cap.y),
            )

            # Check horizontal alignment (same Y within tolerance)
            y_diff = abs(cap.y - nearest_conn.y)
            if y_diff > self.alignment_tolerance:
                misaligned.append(
                    f"{cap.comp_name} (y={cap.y:.4f}) vs "
                    f"{nearest_conn.comp_name} (y={nearest_conn.y:.4f}), "
                    f"diff={y_diff:.4f}"
                )

        if misaligned:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                category=self.category,
                passed=False,
                message=f"{len(misaligned)} misaligned capacitor-connector pair(s) found.",
                affected_components=[m.split(" ")[0] for m in misaligned],
                details={"misaligned_pairs": misaligned[:20]},
            )

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=True,
            message=f"All {len(top_caps)} capacitors properly aligned with bottom connectors.",
        )
