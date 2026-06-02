"""CKL-01-008: Interposer curved-area outer pins must not carry signal balls.

Check process
-------------
1. Find interposer components on both top and bottom layers.
2. Identify the outermost-ring pins of each interposer.
3. Among outer pins, filter to those located in *curved* (corner) areas.
4. Check the net/signal assigned to each corner pin:
   - GND / GROUND / VSS or similar → PASS
   - Any other signal → FAIL  (signal ball at curved area)
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

from src.checklist.component_classifier import find_interposers
from src.checklist.engine import register_rule
from src.checklist.geometry_utils.overlap import (
    find_outermost_pin_indices,
    transform_point,
)
from src.checklist.rule_base import ChecklistRule
from src.models import RuleResult

# Net names that are considered safe (ground) for corner pins
_GND_PATTERNS = {"GND", "GROUND", "VSS", "VSSA", "VSSQ", "DGND", "AGND",
                 "PGND", "SGND", "AVSS", "DVSS"}


def _is_ground_net(net_name: str) -> bool:
    """Return True if *net_name* looks like a ground net."""
    if not net_name:
        return False
    upper = net_name.strip().upper()
    if upper in _GND_PATTERNS:
        return True
    # Accept names containing "GND" or "GROUND"
    if "GND" in upper or "GROUND" in upper or "VSS" in upper:
        return True
    return False


def _get_net_name(toeprint, eda_data) -> str:
    """Resolve net name for a toeprint from EDA data."""
    if eda_data is None or toeprint is None:
        return ""
    if toeprint.net_num < 0 or toeprint.net_num >= len(eda_data.nets):
        return ""
    return eda_data.nets[toeprint.net_num].name or ""


def _find_corner_outer_pin_indices(pins, *, corner_fraction: float = 0.15):
    """Return the subset of outermost pin indices that are in corner/curved areas.

    A pin is in the "corner" area if it is near a corner of the bounding box
    of the outermost pins.  Specifically, a pin within *corner_fraction* of
    each edge range from a corner is flagged.

    This corresponds to the curved/chamfered corners of a BGA-type interposer.
    """
    outer = find_outermost_pin_indices(pins)
    if len(outer) <= 4:
        return outer

    centres = [(pins[i].center.x, pins[i].center.y) for i in outer]
    xs = [c[0] for c in centres]
    ys = [c[1] for c in centres]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)

    x_span = x_max - x_min
    y_span = y_max - y_min
    if x_span < 0.01 or y_span < 0.01:
        return outer

    x_margin = x_span * corner_fraction
    y_margin = y_span * corner_fraction

    corner_pins: set[int] = set()
    for idx in outer:
        cx = pins[idx].center.x
        cy = pins[idx].center.y
        near_left = cx <= x_min + x_margin
        near_right = cx >= x_max - x_margin
        near_bottom = cy <= y_min + y_margin
        near_top = cy >= y_max - y_margin

        # Pin is in a corner area if it is near BOTH an x-edge AND a y-edge
        if (near_left or near_right) and (near_bottom or near_top):
            corner_pins.add(idx)

    return corner_pins


@register_rule
class CKL01008(ChecklistRule):
    rule_id = "CKL-01-008"
    description = (
        "인터포저의 곡선부 외곽 pin에는 SIGNAL BALL(pin map)을 "
        "설계하지 말아야 합니다 (GND만 허용)"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []

        columns = ["comp", "cmp_layer", "pin", "signal", "status"]
        rows: list[dict] = []

        for comps, layer in [(components_top, "Top"), (components_bot, "Bottom")]:
            is_bottom = layer == "Bottom"
            interposers = find_interposers(comps)

            for inp in interposers:
                if inp.pkg_ref < 0 or inp.pkg_ref >= len(packages):
                    continue
                pkg = packages[inp.pkg_ref]
                if not pkg.pins:
                    continue

                corner_indices = _find_corner_outer_pin_indices(pkg.pins)
                if not corner_indices:
                    continue

                # Build toeprint lookup by pin name
                tp_by_name: dict[str, object] = {}
                for tp in inp.toeprints:
                    tp_by_name[tp.name] = tp

                for idx in sorted(corner_indices):
                    pin = pkg.pins[idx]
                    tp = tp_by_name.get(pin.name)
                    net_name = _get_net_name(tp, eda) if tp else ""

                    is_gnd = _is_ground_net(net_name)
                    status = "PASS" if is_gnd else "FAIL"

                    rows.append({
                        "comp": inp.comp_name,
                        "cmp_layer": layer,
                        "pin": pin.name,
                        "signal": net_name or "(none)",
                        "status": status,
                    })

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"인터포저 곡선부 외곽 핀에 시그널 볼이 {fail_count}건 발견되었습니다."
                if not passed
                else "인터포저 곡선부 외곽 핀에 시그널 볼이 없습니다."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
