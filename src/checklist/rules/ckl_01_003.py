"""CKL-01-003: QUALCOMM PMIC opposite-side component containment check.

QUALCOMM PMICs must be placed such that components on the opposite side
do NOT overlap with the PMIC's component outline.  Any opposite-side
component whose footprint intersects the PMIC outline is flagged FAIL.
"""

from __future__ import annotations

from src.checklist.engine import register_rule
from src.checklist.geometry_utils import overlaps_component_outline
from src.checklist.reference_loader import load_reference_csv
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


def _get_qualcomm_pmic_part_names() -> set[str]:
    """Return part_names of QUALCOMM PMICs from the reference CSV."""
    rows = load_reference_csv("pmic_list")
    return {
        r["part_name"]
        for r in rows
        if r.get("part_name") and r.get("maker", "").upper().startswith("QUALCO")
    }


@register_rule
class CKL01003(ChecklistRule):
    rule_id = "CKL-01-003"
    description = (
        "QUALCOMM PMICs must be placed such that opposite-side components "
        "are contained within the PMIC outline"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        qualcomm_parts = _get_qualcomm_pmic_part_names()

        columns = ["comp", "cmp_layer", "overlapping_cmp", "outline", "status"]
        rows: list[dict] = []

        for comps, layer_name, opp_comps in [
            (components_top, "Top", components_bot),
            (components_bot, "Bottom", components_top),
        ]:
            pmic_comps = [
                c for c in comps
                if (c.part_name or "") in qualcomm_parts
            ]

            for pmic in pmic_comps:
                if pmic.pkg_ref < 0 or pmic.pkg_ref >= len(packages):
                    continue

                has_any_overlap = False
                for opp in opp_comps:
                    if opp.pkg_ref < 0 or opp.pkg_ref >= len(packages):
                        continue
                    overlaps = overlaps_component_outline(
                        opp, pmic, packages,
                    )
                    if overlaps:
                        has_any_overlap = True
                        rows.append({
                            "comp": pmic.comp_name,
                            "cmp_layer": layer_name,
                            "overlapping_cmp": opp.comp_name,
                            "outline": "TRUE",
                            "status": "FAIL",
                        })

                if not has_any_overlap:
                    rows.append({
                        "comp": pmic.comp_name,
                        "cmp_layer": layer_name,
                        "overlapping_cmp": "-",
                        "outline": "FALSE",
                        "status": "PASS",
                    })

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"{fail_count} opposite-side component(s) overlapping "
                f"QUALCOMM PMIC outline detected."
                if not passed
                else "No opposite-side components overlap QUALCOMM PMIC outlines."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
