"""CKL-03-001: Connectors overlapping opposite side of MCP ICs.

Identify and inspect connectors located on the opposite side of
Memory IC (MCP — Multi-Chip Package) components.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.component_classifier import find_connectors, find_ics
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import find_pad_overlapping_components
from src.checklist.reference_loader import get_part_category_map
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.overlap_viz import render_overlap_image
from src.models import Component, RuleResult


def _find_mcp_ics(components: list[Component]) -> list[Component]:
    """Return IC components whose part_name maps to category 'MCP' in ap_memory.csv."""
    category_map = get_part_category_map("ap_memory")
    ics = find_ics(components)
    return [
        ic for ic in ics
        if category_map.get(ic.part_name or "") == "MCP"
    ]


@register_rule
class CKL03001(ChecklistRule):
    rule_id = "CKL-03-001"
    description = (
        "Connectors must not overlap the opposite side of MCP IC components"
    )
    category = "Clearance"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        columns = [
            "comp", "cmp_layer", "overlapping_cmp", "part_name", "status",
        ]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_03_001_"))

        for ic_layer_comps, ic_layer, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            mcp_ics = _find_mcp_ics(ic_layer_comps)
            if not mcp_ics:
                continue

            opp_connectors = find_connectors(opp_comps)
            if not opp_connectors:
                continue

            for mcp in mcp_ics:
                overlaps = find_pad_overlapping_components(
                    mcp, opp_connectors, packages
                )
                overlap_items: list[dict] = []
                for conn in overlaps:
                    rows.append({
                        "comp": mcp.comp_name,
                        "cmp_layer": ic_layer,
                        "overlapping_cmp": conn.comp_name,
                        "part_name": conn.part_name or "",
                        "status": "FAIL",
                    })
                    overlap_items.append({"comp": conn, "status": "FAIL"})

                if overlap_items:
                    safe = mcp.comp_name.replace("/", "_")
                    img_path = image_dir / f"{safe}_{ic_layer}.png"
                    render_overlap_image(
                        mcp, packages, overlap_items, opp_comps, img_path,
                        rule_id=self.rule_id,
                        title="Connector overlap on MCP",
                        layer_name=ic_layer,
                        primary_label="MCP IC",
                        overlap_label="Connector",
                    )
                    images.append({"path": img_path,
                                   "title": f"{mcp.comp_name} ({ic_layer})",
                                   "width": 500})

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"{fail_count} connector(s) overlap the opposite side of MCP ICs."
                if not passed
                else "No connectors overlap opposite side of MCP ICs."
            ),
            affected_components=[
                r["overlapping_cmp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
