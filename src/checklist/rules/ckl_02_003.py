"""CKL-02-003: Managed capacitors (41 types) vs shield cans — alignment check.

When the pads of the 41 managed capacitor types overlap with Shield Can
pads on the opposite side, they must be arranged in a horizontal layout.
Capacitors placed on corner areas or diagonally designed sections of the
shield can are flagged as FAIL.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import find_shield_cans
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    find_pad_overlapping_components,
    get_orientation_relative_to_shield_can,
    is_on_corner_or_diagonal,
)
from src.checklist.reference_loader import get_managed_part_names
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import RuleResult


@register_rule
class CKL02003(ChecklistRule):
    rule_id = "CKL-02-003"
    description = (
        "Managed capacitors (41 types) whose pads overlap shield can pads "
        "on the opposite side must be aligned horizontally and not placed "
        "on corner or diagonal sections"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []
        user_symbols: dict = job_data.get("user_symbols") or {}

        managed_41 = get_managed_part_names("capacitors_41_list")

        columns = [
            "comp", "cmp_layer", "overlapping_cap", "part_name",
            "edge", "hori/verti", "status",
        ]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_02_003_"))

        for sc_comps, sc_layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            sc_is_bottom = (sc_layer == "Bottom")
            opp_is_bottom = not sc_is_bottom

            shield_cans = find_shield_cans(sc_comps)
            # Filter opposite-side capacitors to managed 41 types
            opp_managed_caps = [
                c for c in opp_comps
                if (c.part_name or "") in managed_41
            ]
            if not shield_cans or not opp_managed_caps:
                continue

            for sc in shield_cans:
                overlaps = find_pad_overlapping_components(
                    sc, opp_managed_caps, packages,
                    is_bottom_primary=sc_is_bottom,
                    is_bottom_candidates=opp_is_bottom,
                    user_symbols=user_symbols,
                )
                if not overlaps:
                    continue

                overlap_items: list[dict] = []

                for cap in overlaps:
                    on_edge = is_on_corner_or_diagonal(
                        cap, sc, packages,
                        cap_is_bottom=opp_is_bottom,
                        sc_is_bottom=sc_is_bottom,
                    )
                    orientation = get_orientation_relative_to_shield_can(
                        cap, sc, packages,
                        cap_is_bottom=opp_is_bottom,
                        sc_is_bottom=sc_is_bottom,
                    )
                    edge_str = "TRUE" if on_edge else "FALSE"
                    status = (
                        "PASS"
                        if (not on_edge and orientation == "Horizontal")
                        else "FAIL"
                    )
                    rows.append({
                        "comp": sc.comp_name,
                        "cmp_layer": sc_layer,
                        "overlapping_cap": cap.comp_name,
                        "part_name": cap.part_name or "",
                        "edge": edge_str,
                        "hori/verti": orientation,
                        "status": status,
                    })
                    detail_parts = [orientation]
                    if on_edge:
                        detail_parts.append("Edge")
                    overlap_items.append({
                        "comp": cap,
                        "status": status,
                        "detail": ", ".join(detail_parts),
                    })

                # Generate image only when at least one item is FAIL
                if overlap_items and any(i["status"] == "FAIL" for i in overlap_items):
                    safe_name = sc.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe_name}_{sc_layer}.png"
                    render_overlap_image(
                        sc, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="Managed capacitor alignment (Shield Can)",
                        layer_name=sc_layer,
                        primary_label="Shield Can",
                        overlap_label="Managed cap",
                        primary_is_bottom=sc_is_bottom,
                        overlap_is_bottom=opp_is_bottom,
                        user_symbols=user_symbols,
                    )
                    images.append({
                        "path": img_path,
                        "title": f"{sc.comp_name} ({sc_layer})",
                        "width": 500,
                    })

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"{fail_count} managed capacitor(s) not horizontally aligned "
                f"with opposite-side shield can (or on corner/diagonal section)."
                if not passed
                else "All managed capacitors near shield cans are horizontally aligned."
            ),
            affected_components=[
                r["overlapping_cap"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
