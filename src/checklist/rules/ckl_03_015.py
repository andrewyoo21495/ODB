"""CKL-03-015: PCB outline clearance check.

Components and routing must be placed with a clearance of at least
0.65mm from the inner PCB outline.

- Top / Bottom layers: flags components whose **pads** intersect or fall
  within the clearance zone (component outline overlap is acceptable).
- Signal layers: identifies nets with copper features encroaching on the
  clearance zone.  (Currently commented out for verification.)
"""

from __future__ import annotations

from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    build_board_polygon,
    build_inset_boundary,
    components_with_pads_in_clearance_zone,
    # signal_features_in_clearance_zone,  # TODO: re-enable after verification
)
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult


_CLEARANCE_MM = 0.65
_EXCLUDED_PREFIXES = ("ANT", "CN", "TP")


@register_rule
class CKL03015(ChecklistRule):
    rule_id = "CKL-03-015"
    description = (
        "부품은 PCB 외곽선으로부터 최소 0.65mm 이격되어야 합니다"
    )
    category = "Clearance"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        profile = job_data.get("profile")
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        board_poly = build_board_polygon(profile)
        if board_poly is None:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                category=self.category,
                passed=True,
                message="이격 검사에 사용할 보드 프로파일이 없습니다.",
            )

        inset_poly = build_inset_boundary(board_poly, _CLEARANCE_MM)
        if inset_poly is None:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                category=self.category,
                passed=True,
                message="이격 검사를 위한 내측 경계를 생성할 수 없습니다.",
            )

        # --- Part 1: Top / Bottom component pad clearance ------------------
        columns = ["comp", "part_name", "cmp_layer", "distance", "status"]
        rows: list[dict] = []

        for comps, layer_name in [
            (components_top, "Top"),
            (components_bot, "Bottom"),
        ]:
            violations = components_with_pads_in_clearance_zone(
                comps, board_poly, inset_poly, packages
            )
            for comp, dist in violations:
                if comp.comp_name.startswith(_EXCLUDED_PREFIXES):
                    continue
                status = "PASS" if dist >= _CLEARANCE_MM else "FAIL"
                rows.append({
                    "comp": comp.comp_name,
                    "part_name": comp.part_name or "",
                    "cmp_layer": layer_name,
                    "distance": f"{dist:.3f}",
                    "status": status,
                })

        # --- Part 2: Signal layer copper clearance -------------------------
        # TODO: re-enable after Top/Bottom pad clearance is verified
        # signal_columns = [
        #     "layer_name", "net_name", "feature_type", "distance", "status",
        # ]
        # signal_rows: list[dict] = signal_features_in_clearance_zone(
        #     layers_data, board_poly, inset_poly, eda,
        # )

        # --- Aggregate results ---------------------------------------------
        comp_fail = sum(1 for r in rows if r["status"] == "FAIL")
        passed = comp_fail == 0

        message = (
            f"PCB 외곽선으로부터 {_CLEARANCE_MM}mm 이내에 패드가 있는 부품이 "
            f"{comp_fail}건 발견되었습니다."
            if not passed
            else f"모든 부품이 {_CLEARANCE_MM}mm 이격 요건을 충족합니다."
        )

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=message,
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={
                "columns": columns,
                "rows": [r for r in rows if r["status"] != "PASS"],
            },
        )
