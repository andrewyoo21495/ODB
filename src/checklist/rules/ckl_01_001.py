"""CKL-01-001: IC vs interposer/connector/SIM-socket overlap on opposite side.

ICs must be placed so they do not have pad-to-pad overlaps with interposers,
connectors, or SIM sockets on the opposite side of the PCB.  Outline overlaps
are acceptable; only pad-to-pad contact is flagged as a failure.
"""

from __future__ import annotations

from src.checklist.component_classifier import (
    find_connectors, find_ics, find_interposers, find_simsockets,
)
from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    find_overlapping_components,
    find_pad_overlapping_components,
)
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


@register_rule
class CKL01001(ChecklistRule):
    rule_id = "CKL-01-001"
    description = (
        "ICs must not have pad-to-pad overlaps with interposers, connectors, "
        "or SIM sockets on the opposite side"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        columns = ["comp", "cmp_layer", "overlapping_cmp", "opp_type", "status"]
        rows: list[dict] = []

        for ics, ic_layer, opp_comps in [
            (find_ics(components_top), "Top", components_bot),
            (find_ics(components_bot), "Bottom", components_top),
        ]:
            # Candidates on the opposite side: interposers + connectors + SIM sockets
            opp_interposers = find_interposers(opp_comps)
            opp_connectors  = find_connectors(opp_comps)
            opp_simsockets  = find_simsockets(opp_comps)
            opp_targets = opp_interposers + opp_connectors + opp_simsockets

            if not opp_targets:
                continue

            # Quick pre-filter: keep only targets whose outline overlaps the IC
            def _opp_type(c):
                if c in opp_interposers:
                    return "Interposer"
                if c in opp_simsockets:
                    return "SIM_Socket"
                return "Connector"

            for ic in ics:
                outline_overlaps = find_overlapping_components(ic, opp_targets, packages)
                pad_overlaps     = find_pad_overlapping_components(ic, opp_targets, packages)

                if pad_overlaps:
                    for ovl in pad_overlaps:
                        rows.append({
                            "comp": ic.comp_name,
                            "cmp_layer": ic_layer,
                            "overlapping_cmp": ovl.comp_name,
                            "opp_type": _opp_type(ovl),
                            "status": "FAIL",
                        })
                elif outline_overlaps:
                    # Outline overlap only — acceptable, record as PASS
                    for ovl in outline_overlaps:
                        rows.append({
                            "comp": ic.comp_name,
                            "cmp_layer": ic_layer,
                            "overlapping_cmp": ovl.comp_name,
                            "opp_type": _opp_type(ovl),
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
                f"{fail_count} IC pad-to-pad overlap(s) with opposite-side "
                f"interposer/connector/SIM-socket found."
                if not passed
                else "No IC pad-to-pad overlaps with opposite-side components detected."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
