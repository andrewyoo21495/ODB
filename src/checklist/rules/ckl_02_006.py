"""CKL-02-006: General capacitors vs connectors and shield cans — placement check.

Identify general capacitors (NOT in the 51 managed types) overlapping
connectors or shield cans on the opposite side.  Check edge placement,
orientation, and (for shield cans) diagonal-region placement.

Connector criteria (PASS when ALL true):
  - NOT on edge
  - Horizontal orientation

Shield Can criteria (PASS when ALL true):
  - NOT on edge (corner/diagonal of the SC outline)
  - Horizontal orientation relative to the nearest SC wall
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import (
    find_capacitors, find_connectors, find_shield_cans,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    find_pad_overlapping_components,
    get_orientation_relative_to_shield_can,
    get_pair_orientation,
    is_on_corner_or_diagonal,
    is_on_edge,
)
from src.checklist.reference_loader import get_managed_part_names
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import RuleResult


def _get_51_managed_part_names() -> set[str]:
    """Combine capacitors_41_list + capacitors_10_list into 51 managed types."""
    parts_41 = get_managed_part_names("capacitors_41_list")
    parts_10 = get_managed_part_names("capacitors_10_list")
    return parts_41 | parts_10


@register_rule
class CKL02006(ChecklistRule):
    rule_id = "CKL-02-006"
    description = (
        "General capacitors (not in 51 managed types) overlapping "
        "connectors or shield cans on the opposite side: edge, orientation, "
        "and diagonal-region check"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []
        user_symbols: dict = job_data.get("user_symbols") or {}

        managed_51 = _get_51_managed_part_names()

        columns = [
            "comp", "comp_type", "cmp_layer", "overlapping_cap", "part_name",
            "edge", "hori/verti", "diagonal", "status",
        ]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_02_006_"))

        for ref_comps, ref_layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            ref_is_bottom = (ref_layer == "Bottom")
            opp_is_bottom = not ref_is_bottom

            opp_all_caps = find_capacitors(opp_comps)
            # General capacitors = not in managed 51
            opp_general_caps = [
                c for c in opp_all_caps
                if (c.part_name or "") not in managed_51
            ]
            if not opp_general_caps:
                continue

            # ── Connector check ───────────────────────────────────────────────
            connectors = find_connectors(ref_comps)
            for conn in connectors:
                overlaps = find_pad_overlapping_components(
                    conn, opp_general_caps, packages,
                    is_bottom_primary=ref_is_bottom,
                    is_bottom_candidates=opp_is_bottom,
                    user_symbols=user_symbols,
                )
                overlap_items: list[dict] = []
                for cap in overlaps:
                    on_edge = is_on_edge(cap, conn, packages)
                    orientation = get_pair_orientation(cap, conn, packages)
                    edge_str = "TRUE" if on_edge else "FALSE"
                    status = (
                        "PASS"
                        if (not on_edge and orientation == "Horizontal")
                        else "FAIL"
                    )
                    rows.append({
                        "comp": conn.comp_name,
                        "comp_type": "Connector",
                        "cmp_layer": ref_layer,
                        "overlapping_cap": cap.comp_name,
                        "part_name": cap.part_name or "",
                        "edge": edge_str,
                        "hori/verti": orientation,
                        "diagonal": "N/A",
                        "status": status,
                    })
                    detail_parts = [orientation]
                    if on_edge:
                        detail_parts.append("Edge")
                    overlap_items.append({
                        "comp": cap, "status": status,
                        "detail": ", ".join(detail_parts),
                    })

                if overlap_items and any(i["status"] == "FAIL" for i in overlap_items):
                    safe = conn.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{ref_layer}.png"
                    render_overlap_image(
                        conn, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="General capacitor alignment (Connector)",
                        layer_name=ref_layer,
                        primary_label="Connector",
                        overlap_label="General cap",
                        primary_is_bottom=ref_is_bottom,
                        overlap_is_bottom=opp_is_bottom,
                        user_symbols=user_symbols,
                    )
                    images.append({"path": img_path,
                                   "title": f"{conn.comp_name} ({ref_layer})",
                                   "width": 500})

            # ── Shield Can check ──────────────────────────────────────────────
            shield_cans = find_shield_cans(ref_comps)
            for sc in shield_cans:
                overlaps = find_pad_overlapping_components(
                    sc, opp_general_caps, packages,
                    is_bottom_primary=ref_is_bottom,
                    is_bottom_candidates=opp_is_bottom,
                    user_symbols=user_symbols,
                )
                overlap_items = []
                for cap in overlaps:
                    on_diag = is_on_corner_or_diagonal(
                        cap, sc, packages,
                        cap_is_bottom=opp_is_bottom,
                        sc_is_bottom=ref_is_bottom,
                    )
                    orientation = get_orientation_relative_to_shield_can(
                        cap, sc, packages,
                        cap_is_bottom=opp_is_bottom,
                        sc_is_bottom=ref_is_bottom,
                    )
                    diag_str = "TRUE" if on_diag else "FALSE"
                    status = (
                        "PASS"
                        if (not on_diag and orientation == "Horizontal")
                        else "FAIL"
                    )
                    rows.append({
                        "comp": sc.comp_name,
                        "comp_type": "Shield_Can",
                        "cmp_layer": ref_layer,
                        "overlapping_cap": cap.comp_name,
                        "part_name": cap.part_name or "",
                        "edge": diag_str,
                        "hori/verti": orientation,
                        "diagonal": diag_str,
                        "status": status,
                    })
                    detail_parts = [orientation]
                    if on_diag:
                        detail_parts.append("Diagonal/Corner")
                    overlap_items.append({
                        "comp": cap, "status": status,
                        "detail": ", ".join(detail_parts),
                    })

                if overlap_items and any(i["status"] == "FAIL" for i in overlap_items):
                    safe = sc.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{ref_layer}_sc.png"
                    render_overlap_image(
                        sc, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="General capacitor alignment (Shield Can)",
                        layer_name=ref_layer,
                        primary_label="Shield Can",
                        overlap_label="General cap",
                        primary_is_bottom=ref_is_bottom,
                        overlap_is_bottom=opp_is_bottom,
                        user_symbols=user_symbols,
                    )
                    images.append({"path": img_path,
                                   "title": f"{sc.comp_name} ({ref_layer})",
                                   "width": 500})

        fail_rows = [r for r in rows if r["status"] == "FAIL"]
        fail_count = len(fail_rows)
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"{fail_count} general capacitor placement issue(s) near "
                f"connectors or shield cans."
                if not passed
                else "All general capacitors near connectors and shield cans are properly placed."
            ),
            affected_components=[
                r["overlapping_cap"] for r in fail_rows
            ],
            details={"columns": columns, "rows": fail_rows},
            images=images,
            recommended=True,
        )
