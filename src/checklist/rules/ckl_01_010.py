"""CKL-01-010: PCB narrow-width area screw fixation check.

If there is no fixing screw near a narrow PCB section (width <= 3.5 mm),
the PCB width should be extended to at least 3.5 mm.

Detection process:
1. Find all PCB regions where local width is <= 3.5 mm using morphological
   opening (same approach as CKL-03-011 bending detection).
2. (Future) Check for fixing screws / through-holes within 10 mm radius of
   each narrow region.
3. Report each region with region index, screw presence, and pass/fail status.

NOTE: Screw / through-hole detection is not yet implemented.  Currently all
narrow regions are reported with screw=FALSE and status=FAIL.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    build_board_polygon,
    find_bending_vulnerable_areas,
)
from src.checklist.rule_base import ChecklistRule
from src.checklist.visualizers.narrow_width_viz import render_narrow_width_image
from src.models import RuleResult

# Width threshold in mm — regions narrower than this are flagged.
_WIDTH_THRESHOLD = 3.5


@register_rule
class CKL01010(ChecklistRule):
    rule_id = "CKL-01-010"
    description = (
        "PCB 고정 SCREW 가 없을 경우 PCB 폭을 3.5 mm 이상 연장 설계할 것"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        profile = job_data.get("profile")

        board_poly = build_board_polygon(profile)

        # Reuse bending-vulnerable-area detection with width_threshold=3.5 mm
        # and protrusion_depth=0.0 to capture *all* narrow regions regardless
        # of how far they protrude.
        narrow_areas = find_bending_vulnerable_areas(
            board_poly,
            width_threshold=_WIDTH_THRESHOLD,
            protrusion_depth=0.0,
        )

        columns = ["region", "screw", "status"]
        rows: list[dict] = []
        region_labels: list[str] = []

        for idx, area in enumerate(narrow_areas, start=1):
            label = f"region{idx}"
            region_labels.append(label)

            # TODO: screw / through-hole proximity check (radius 10 mm)
            screw_found = False

            rows.append({
                "region": label,
                "screw": str(screw_found).upper(),
                "status": "PASS" if screw_found else "FAIL",
            })

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        # Generate visualisation image
        images: list[dict] = []
        if board_poly is not None and narrow_areas:
            image_dir = Path(tempfile.mkdtemp(prefix="ckl_01_010_"))
            img_path = image_dir / "narrow_width_areas.png"
            render_narrow_width_image(
                board_poly, narrow_areas, region_labels, img_path,
                rule_id=self.rule_id,
                title="Narrow-width areas (width <= 3.5 mm)",
            )
            images.append({
                "path": img_path,
                "title": "Narrow-width area check",
                "width": 600,
            })

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"폭 3.5 mm 이하의 PCB 영역이 {fail_count}건 발견되었습니다."
                if not passed
                else "폭 3.5 mm 이하의 PCB 영역이 없습니다."
            ),
            affected_components=[],
            details={"columns": columns, "rows": rows},
            images=images,
        )
