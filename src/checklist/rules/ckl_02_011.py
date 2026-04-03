"""CKL-02-011: Capacitor sandwiched between AP/Memory – outline overlap check.

When a capacitor is placed in a tight gap between AP and Memory components,
check whether it overlaps with either component's outline.  If even one
side overlaps, the placement is flagged as FAIL.

Checks are performed in two modes:
  - Same-layer: cap and both AP/Memory components on the same layer
  - Cross-layer: cap on one layer, AP/Memory pair on the opposite layer
    (position projected in XY; outline overlap checked across layers)
"""

from __future__ import annotations

import tempfile
from itertools import combinations
from pathlib import Path

from src.checklist.component_classifier import find_capacitors
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    edge_distance,
    overlaps_component_outline,
)
from src.checklist.reference_loader import get_managed_part_names
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import Component, RuleResult


def _find_ap_memory(components: list[Component]) -> list[Component]:
    """Return components whose part_name is listed in ap_memory.csv."""
    ap_parts = get_managed_part_names("ap_memory")
    return [c for c in components if (c.part_name or "") in ap_parts]


def _is_between(cap: Component, am_a: Component, am_b: Component) -> bool:
    """Check if *cap* centre projects between the centres of *am_a* and *am_b*.

    Uses a simple dot-product projection.  Returns True when the
    projection parameter *t* falls strictly between 0 and 1, meaning the
    capacitor centre lies between the two AP/Memory centres along the
    line connecting them.
    """
    ax, ay = am_a.x, am_a.y
    bx, by = am_b.x, am_b.y
    cx, cy = cap.x, cap.y

    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-9:
        return False

    t = ((cx - ax) * dx + (cy - ay) * dy) / length_sq
    return 0.0 < t < 1.0


@register_rule
class CKL02011(ChecklistRule):
    rule_id = "CKL-02-011"
    description = (
        "Capacitor sandwiched between AP/Memory (same or opposite layer): "
        "if overlapping an outline, placement is flagged"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        columns = ["comp", "part_name", "cap_layer", "overlapping_cmp", "am_layer", "status"]
        rows: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_02_011_"))
        images: list[dict] = []

        # We check each cap against AP/Memory pairs on the SAME layer and the
        # OPPOSITE layer.  Layer combinations:
        #   cap_layer=Top,    am_layer=Top    (same)
        #   cap_layer=Top,    am_layer=Bottom (cross)
        #   cap_layer=Bottom, am_layer=Bottom (same)
        #   cap_layer=Bottom, am_layer=Top    (cross)
        layer_pairs = [
            # (cap_comps, cap_layer, cap_is_bottom, am_comps, am_layer, am_is_bottom)
            (components_top, "Top",    False, components_top, "Top",    False),
            (components_top, "Top",    False, components_bot, "Bottom", True),
            (components_bot, "Bottom", True,  components_bot, "Bottom", False),
            (components_bot, "Bottom", True,  components_top, "Top",    False),
        ]

        # Track which (cap, am) pairs have already been reported to avoid
        # double-counting when a cross-layer pair is symmetric.
        reported: set[tuple[str, str, str]] = set()

        for cap_comps, cap_layer, cap_is_bot, am_comps, am_layer, am_is_bot in layer_pairs:
            ap_mems = _find_ap_memory(am_comps)
            caps = find_capacitors(cap_comps)

            if len(ap_mems) < 2 or not caps:
                continue

            close_pairs: list[tuple[Component, Component]] = []
            for am_a, am_b in combinations(ap_mems, 2):
                dist = edge_distance(am_a, am_b, packages)
                if dist < 5.0:
                    close_pairs.append((am_a, am_b))

            if not close_pairs:
                continue

            for cap in caps:
                sandwiching_ams: set[str] = set()
                for am_a, am_b in close_pairs:
                    if _is_between(cap, am_a, am_b):
                        sandwiching_ams.add(am_a.comp_name)
                        sandwiching_ams.add(am_b.comp_name)

                if not sandwiching_ams:
                    continue

                overlapping_names: list[str] = []
                overlap_items: list[dict] = []
                for am in ap_mems:
                    if am.comp_name not in sandwiching_ams:
                        continue

                    report_key = (cap.comp_name, am.comp_name, f"{cap_layer}-{am_layer}")
                    if report_key in reported:
                        continue
                    reported.add(report_key)

                    if overlaps_component_outline(
                        cap, am, packages,
                        is_bottom_comp=cap_is_bot,
                        is_bottom_target=am_is_bot,
                    ):
                        overlapping_names.append(am.comp_name)
                        overlap_items.append({"comp": am, "status": "FAIL"})
                    else:
                        overlap_items.append({"comp": am, "status": "PASS"})

                if overlapping_names:
                    for am_name in overlapping_names:
                        rows.append({
                            "comp": cap.comp_name,
                            "part_name": cap.part_name or "",
                            "cap_layer": cap_layer,
                            "overlapping_cmp": am_name,
                            "am_layer": am_layer,
                            "status": "FAIL",
                        })
                elif overlap_items:
                    # Sandwiched but no outline overlap – acceptable.
                    rows.append({
                        "comp": cap.comp_name,
                        "part_name": cap.part_name or "",
                        "cap_layer": cap_layer,
                        "overlapping_cmp": "",
                        "am_layer": am_layer,
                        "status": "PASS",
                    })

                # --- visualisation ----------------------------------------
                fail_items = [i for i in overlap_items if i["status"] == "FAIL"]
                if fail_items:
                    safe = cap.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{cap_layer}_vs_{am_layer}.png"
                    render_overlap_image(
                        cap, packages, fail_items, ap_mems, img_path,
                        rule_id=self.rule_id,
                        title=f"AP/Memory outline overlap ({cap_layer} cap vs {am_layer} AM)",
                        layer_name=cap_layer,
                        primary_label="Capacitor",
                        overlap_label="AP/Memory",
                    )
                    images.append({
                        "path": img_path,
                        "title": f"{cap.comp_name} ({cap_layer} vs {am_layer})",
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
                f"{fail_count} capacitor(s) sandwiched between AP/Memory "
                f"overlap an outline."
                if not passed
                else "No sandwiched capacitors overlapping AP/Memory outlines."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
