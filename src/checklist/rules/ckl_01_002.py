"""CKL-01-002: VIA presence check for outermost PMIC pads.

For PMIC components (identified by part_name in references/pmic_list.csv),
the outermost (outer perimeter) pads must each have at least one VIA.
A pad on the outer perimeter with zero VIAs is flagged FAIL.
"""

from __future__ import annotations

from src.checklist.engine import register_rule
from src.checklist.geometry_utils import (
    build_toeprint_lookup,
    build_via_position_set,
    count_vias_at_pad,
    lookup_resolved_pads_for_pin,
)
from src.checklist.reference_loader import get_managed_part_names
from src.checklist.rule_base import ChecklistRule
from src.models import Pin, RuleResult
from src.visualizer.fid_lookup import (
    build_fid_map,
    resolve_fid_features,
    _find_top_bottom_signal_layers,
)


def _find_outermost_pin_indices(pins: list[Pin]) -> set[int]:
    """Return indices of pins that lie on the outer perimeter (convex hull).

    For packages with <= 4 pins, all pins are considered outermost.
    For larger packages, computes the convex hull of pin centres and
    returns pins whose centres lie on or very near the hull boundary.
    """
    if len(pins) <= 4:
        return set(range(len(pins)))

    centres = [(p.center.x, p.center.y) for p in pins]

    # Check for degenerate cases (all collinear or coincident)
    xs = {c[0] for c in centres}
    ys = {c[1] for c in centres}
    if len(xs) <= 1 or len(ys) <= 1:
        # All pins in a line or single point – all are outermost
        return set(range(len(pins)))

    # Compute convex hull using Andrew's monotone chain algorithm
    hull_pts = _convex_hull(centres)
    hull_set = set(hull_pts)

    # Tolerance for "on hull edge" check (0.01 mm)
    tol = 0.01

    outermost: set[int] = set()
    for idx, (cx, cy) in enumerate(centres):
        if (cx, cy) in hull_set:
            outermost.add(idx)
        else:
            # Check if point lies on any hull edge
            for i in range(len(hull_pts)):
                ax, ay = hull_pts[i]
                bx, by = hull_pts[(i + 1) % len(hull_pts)]
                if _point_on_segment(cx, cy, ax, ay, bx, by, tol):
                    outermost.add(idx)
                    break

    return outermost


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Andrew's monotone chain convex hull. Returns vertices in CCW order."""
    pts = sorted(set(points))
    if len(pts) <= 1:
        return pts

    # Build lower hull
    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    # Build upper hull
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def _cross(
    o: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _point_on_segment(
    px: float, py: float,
    ax: float, ay: float,
    bx: float, by: float,
    tol: float,
) -> bool:
    """Check if point (px,py) lies on segment (ax,ay)-(bx,by) within tolerance."""
    # Cross product for distance from line
    cross = abs((bx - ax) * (py - ay) - (by - ay) * (px - ax))
    seg_len = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
    if seg_len < 1e-9:
        return False
    dist = cross / seg_len
    if dist > tol:
        return False
    # Check that projection falls within segment bounds
    dot = (px - ax) * (bx - ax) + (py - ay) * (by - ay)
    return -tol <= dot <= seg_len * seg_len + tol


@register_rule
class CKL01002(ChecklistRule):
    rule_id = "CKL-01-002"
    description = (
        "Outermost pads of PMIC components must have VIA designs applied"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        layers_data = job_data.get("layers_data", {})
        packages = eda.packages if eda else []

        pmic_parts = get_managed_part_names("pmic_list")

        # Build VIA position sets per layer
        via_top: set[tuple[float, float]] = set()
        via_bot: set[tuple[float, float]] = set()
        if eda and layers_data:
            via_top = build_via_position_set(eda, layers_data, is_bottom=False)
            via_bot = build_via_position_set(eda, layers_data, is_bottom=True)

        # Build FID-resolved pad lookup for actual copper pad geometry
        fid_resolved: dict = {}
        top_sig_name, bot_sig_name = None, None
        if eda and layers_data:
            fid_map = build_fid_map(eda)
            fid_resolved = resolve_fid_features(
                fid_map, eda.layer_names, layers_data)
            top_sig_name, bot_sig_name = _find_top_bottom_signal_layers(
                layers_data)

        columns = ["comp", "cmp_layer", "pad_name", "via", "status"]
        rows: list[dict] = []

        for comps, layer_name, is_bottom in [
            (components_top, "Top", False),
            (components_bot, "Bottom", True),
        ]:
            via_positions = via_bot if is_bottom else via_top
            sig_name = bot_sig_name if is_bottom else top_sig_name
            pmic_comps = [
                c for c in comps if (c.part_name or "") in pmic_parts
            ]

            for comp in pmic_comps:
                if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
                    continue
                pkg = packages[comp.pkg_ref]

                if not pkg.pins:
                    continue

                outermost_indices = _find_outermost_pin_indices(pkg.pins)
                toep_by_pin = build_toeprint_lookup(comp, pkg)

                for pin_idx in sorted(outermost_indices):
                    pin = pkg.pins[pin_idx]
                    tp = toep_by_pin.get(pin_idx)
                    rpads = lookup_resolved_pads_for_pin(
                        fid_resolved, comp, is_bottom,
                        pin_idx, signal_layer_name=sig_name,
                    )
                    via_count = count_vias_at_pad(
                        comp, pin.center.x, pin.center.y,
                        via_positions, is_bottom=is_bottom,
                        toeprint=tp, pin=pin,
                        resolved_pads=rpads,
                    )
                    has_via = via_count > 0
                    rows.append({
                        "comp": comp.comp_name,
                        "cmp_layer": layer_name,
                        "pad_name": pin.name,
                        "via": "TRUE" if has_via else "FALSE",
                        "status": "PASS" if has_via else "FAIL",
                    })

        fail_count = sum(1 for r in rows if r["status"] == "FAIL")
        passed = fail_count == 0

        return RuleResult(
            rule_id=self.rule_id,
            description=self.description,
            category=self.category,
            passed=passed,
            message=(
                f"{fail_count} outermost PMIC pad(s) without a VIA detected."
                if not passed
                else "All outermost PMIC pads have VIA designs applied."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
        )
