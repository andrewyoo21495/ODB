"""CKL-02-011: Capacitor sandwiched between AP/Memory – outline overlap check.

When a capacitor is placed in a tight gap between AP and Memory components
(on the same layer), check whether it overlaps with either component's
outline.  If even one side overlaps, the placement is flagged as FAIL.
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
        "Capacitor sandwiched between AP/Memory: if overlapping an "
        "outline, pads must be arranged horizontally"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        columns = ["comp", "part_name", "overlapping_cmp", "status"]
        rows: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_02_011_"))
        images: list[dict] = []

        for layer_comps, layer_name in [
            (components_top, "Top"),
            (components_bot, "Bottom"),
        ]:
            ap_mems = _find_ap_memory(layer_comps)
            caps = find_capacitors(layer_comps)

            if len(ap_mems) < 2 or not caps:
                continue

            # Pre-compute AP/Memory pairs that are close enough for a
            # capacitor to be sandwiched between them.  Use edge_distance
            # so large components that are nearby in outline (not just
            # centre) are included.
            close_pairs: list[tuple[Component, Component]] = []
            for am_a, am_b in combinations(ap_mems, 2):
                dist = edge_distance(am_a, am_b, packages)
                # If the outlines are more than 5 mm apart the gap is wide
                # enough that a capacitor there is not "sandwiched".
                if dist < 5.0:
                    close_pairs.append((am_a, am_b))

            if not close_pairs:
                continue

            for cap in caps:
                # Determine which close AP/Memory pairs this cap sits
                # between (centre-projection test).
                sandwiching_ams: set[str] = set()
                for am_a, am_b in close_pairs:
                    if _is_between(cap, am_a, am_b):
                        sandwiching_ams.add(am_a.comp_name)
                        sandwiching_ams.add(am_b.comp_name)

                if not sandwiching_ams:
                    continue

                # Check outline overlap with each neighbouring AP/Memory.
                overlapping_names: list[str] = []
                overlap_items: list[dict] = []
                for am in ap_mems:
                    if am.comp_name not in sandwiching_ams:
                        continue
                    if overlaps_component_outline(cap, am, packages):
                        overlapping_names.append(am.comp_name)
                        overlap_items.append({"comp": am, "status": "FAIL"})
                    else:
                        overlap_items.append({"comp": am, "status": "PASS"})

                if overlapping_names:
                    for am_name in overlapping_names:
                        rows.append({
                            "comp": cap.comp_name,
                            "part_name": cap.part_name or "",
                            "overlapping_cmp": am_name,
                            "status": "FAIL",
                        })
                else:
                    # Sandwiched but no outline overlap – acceptable.
                    rows.append({
                        "comp": cap.comp_name,
                        "part_name": cap.part_name or "",
                        "overlapping_cmp": "",
                        "status": "PASS",
                    })

                # --- visualisation ----------------------------------------
                if overlap_items:
                    safe = cap.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{layer_name}.png"
                    render_overlap_image(
                        cap, packages, overlap_items, ap_mems, img_path,
                        rule_id=self.rule_id,
                        title="AP/Memory outline overlap",
                        layer_name=layer_name,
                        primary_label="Capacitor",
                        overlap_label="AP/Memory",
                    )
                    images.append({
                        "path": img_path,
                        "title": f"{cap.comp_name} ({layer_name})",
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
