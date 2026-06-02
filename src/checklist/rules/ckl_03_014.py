"""CKL-03-014: Signal patterns under shield can enhanced rigidity pads must be
separated by >= 0.2 mm from the pad fill-cut edge.

Check process
-------------
1. Find shield can components on top and bottom layers.
2. For each shield can, identify enhanced rigidity (cross-shaped) pads.
   A cross-shaped pad is detected by:
     a. Symbol name starting with "cross" (standard ODB++ cross symbol), OR
     b. CONTOUR outline with 12 vertices (characteristic of a + shape).
3. If enhanced pads exist, check the signal layer directly below for
   signal traces within 0.2 mm of the pad location.
   - Top components → second signal layer from top (signal layer index 1)
   - Bottom components → second signal layer from bottom (index -2)
4. Report any signal found within the clearance zone.

Columns: comp, cmp_layer, enhanced_pad, signal, status
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon as MplPolygon
import numpy as np

from src.checklist.component_classifier import find_shield_cans
from src.checklist.engine import register_rule
from src.checklist.geometry_utils.polygon import _outline_to_shapely
from src.checklist.rule_base import ChecklistRule
from src.models import (
    ArcRecord,
    Component,
    EdaData,
    LineRecord,
    Package,
    PadRecord,
    RuleResult,
    SurfaceRecord,
)
from src.visualizer.component_overlay import transform_point

try:
    from shapely.geometry import Point as ShapelyPoint
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False

_CLEARANCE_MM = 0.2  # required minimum clearance in mm


# ---------------------------------------------------------------------------
# Cross-shaped pad detection
# ---------------------------------------------------------------------------

def _is_cross_pad_by_symbol(comp: Component, pin_idx: int) -> bool:
    """Check if the toeprint's resolved symbol is a cross type."""
    if pin_idx >= len(comp.toeprints):
        return False
    tp = comp.toeprints[pin_idx]
    if tp.geom is None:
        return False
    sym_name = (tp.geom.symbol_name or "").lower()
    return sym_name.startswith("cross")


def _is_cross_pad_by_outline(pin) -> bool:
    """Check if the pin outline is a CONTOUR with cross-like vertex count.

    A cross (plus) shape has 12 outer vertices (3 per arm × 4 arms).
    We check for CONTOUR outlines with 10-14 vertices (allowing tolerance)
    whose bounding box is roughly square (aspect ratio near 1.0).
    """
    from src.visualizer.symbol_renderer import contour_to_vertices

    for outline in pin.outlines:
        if outline.type == "CONTOUR" and outline.contour is not None:
            verts = contour_to_vertices(outline.contour)
            n = len(verts)
            if 10 <= n <= 14:
                if n >= 3:
                    xs = [v[0] for v in verts]
                    ys = [v[1] for v in verts]
                    w = max(xs) - min(xs)
                    h = max(ys) - min(ys)
                    if w > 0 and h > 0:
                        ratio = min(w, h) / max(w, h)
                        if ratio > 0.5:  # roughly square bounding box
                            return True
        # A cross can also use a user-defined symbol via "cross" type
        if outline.type in ("CR", "CT", "RC", "SQ"):
            return False  # simple shapes are not cross
    return False


def _is_cross_pad(comp: Component, pkg: Package, pin_idx: int) -> bool:
    """Return True if the pin at *pin_idx* is a cross-shaped (enhanced) pad."""
    if _is_cross_pad_by_symbol(comp, pin_idx):
        return True
    if pin_idx < len(pkg.pins):
        return _is_cross_pad_by_outline(pkg.pins[pin_idx])
    return False


def _has_any_cross_pad(comp: Component, pkg: Package) -> bool:
    """Return True if the shield can has at least one cross-shaped pad."""
    for i in range(len(pkg.pins)):
        if _is_cross_pad(comp, pkg, i):
            return True
    return False


def _get_cross_pad_indices(comp: Component, pkg: Package) -> list[int]:
    """Return indices of cross-shaped (enhanced rigidity) pads."""
    return [i for i in range(len(pkg.pins)) if _is_cross_pad(comp, pkg, i)]


# ---------------------------------------------------------------------------
# Signal layer helpers
# ---------------------------------------------------------------------------

def _get_ordered_signal_layers(
    layers_data: dict,
) -> list[tuple[str, object, object]]:
    """Return signal layers sorted by stackup row (top→bottom).

    Returns list of (layer_name, LayerFeatures, MatrixLayer).
    """
    result = []
    for name, (lf, ml) in layers_data.items():
        if ml.type == "SIGNAL":
            result.append((name, lf, ml))
    result.sort(key=lambda x: x[2].row)
    return result


def _get_adjacent_signal_layer(
    layers_data: dict,
    is_bottom: bool,
) -> tuple[str | None, object | None]:
    """Return the signal layer directly below the component side.

    For top-side components: second signal layer from top (index 1).
    For bottom-side components: second signal layer from bottom (index -2).

    Returns (layer_name, LayerFeatures) or (None, None).
    """
    ordered = _get_ordered_signal_layers(layers_data)
    if len(ordered) < 2:
        return None, None

    if not is_bottom:
        # Top component → second signal layer from top
        name, lf, _ml = ordered[1]
    else:
        # Bottom component → second signal layer from bottom
        name, lf, _ml = ordered[-2]

    return name, lf


def _build_net_lookup(
    eda_data: EdaData,
) -> dict[tuple[str, int], str]:
    """Build mapping from (layer_name, feature_idx) → net_name.

    Uses EDA subnet FID cross-references.
    """
    if eda_data is None or not eda_data.layer_names:
        return {}

    layer_name_map = {i: n for i, n in enumerate(eda_data.layer_names)}
    net_lookup: dict[tuple[str, int], str] = {}
    for net in eda_data.nets:
        for subnet in net.subnets:
            for fid in subnet.feature_ids:
                if fid.type != "C":
                    continue
                lname = layer_name_map.get(fid.layer_idx)
                if lname is not None:
                    net_lookup[(lname, fid.feature_idx)] = net.name
    return net_lookup


# ---------------------------------------------------------------------------
# Signal trace proximity detection
# ---------------------------------------------------------------------------

def _sym_scale(units: str, unit_override: str | None) -> float:
    """Convert raw symbol dimensions to MM."""
    if unit_override == "I":
        return 0.0254
    if unit_override == "M":
        return 0.001
    return 0.0254 if units == "INCH" else 0.001


def _point_to_segment_distance_sq(
    px: float, py: float,
    ax: float, ay: float,
    bx: float, by: float,
) -> float:
    """Return squared distance from point (px, py) to segment (a→b)."""
    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-18:
        ex, ey = px - ax, py - ay
        return ex * ex + ey * ey
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    ex, ey = px - proj_x, py - proj_y
    return ex * ex + ey * ey


def _arc_to_points(feat, segments: int = 16) -> list[tuple[float, float]]:
    """Approximate an arc feature as a list of (x, y) points."""
    cx, cy = feat.xc, feat.yc
    r = math.hypot(feat.xs - cx, feat.ys - cy)
    if r < 1e-9:
        return [(feat.xs, feat.ys), (feat.xe, feat.ye)]
    start_angle = math.atan2(feat.ys - cy, feat.xs - cx)
    end_angle = math.atan2(feat.ye - cy, feat.xe - cx)
    if feat.clockwise:
        if end_angle >= start_angle:
            end_angle -= 2 * math.pi
    else:
        if end_angle <= start_angle:
            end_angle += 2 * math.pi
    pts: list[tuple[float, float]] = []
    for i in range(segments + 1):
        t = start_angle + (end_angle - start_angle) * i / segments
        pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return pts


def _point_to_arc_distance_sq(
    px: float, py: float, feat, segments: int = 16,
) -> float:
    """Return squared distance from (px, py) to an arc polyline."""
    pts = _arc_to_points(feat, segments)
    min_d_sq = float("inf")
    for i in range(len(pts) - 1):
        d_sq = _point_to_segment_distance_sq(
            px, py, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
        if d_sq < min_d_sq:
            min_d_sq = d_sq
    return min_d_sq


def _find_signals_near_pad(
    pad_cx: float,
    pad_cy: float,
    layer_name: str,
    lf,
    net_lookup: dict[tuple[str, int], str],
    clearance: float = _CLEARANCE_MM,
) -> list[str]:
    """Return net names of signals passing within *clearance* mm of the pad centre.

    Checks LineRecord, ArcRecord, and SurfaceRecord features on the given
    layer. PadRecords are excluded (pad's own copper is not a signal trace).
    """
    from src.parsers.symbol_resolver import resolve_symbol

    sym_lookup = {s.index: s for s in lf.symbols}
    layer_units = lf.units
    clearance_sq = clearance * clearance
    found_nets: set[str] = set()

    for feat_idx, feat in enumerate(lf.features):
        if feat is None or isinstance(feat, PadRecord):
            continue

        if isinstance(feat, LineRecord):
            # Quick bounding-box pre-filter
            fxmin = min(feat.xs, feat.xe)
            fxmax = max(feat.xs, feat.xe)
            fymin = min(feat.ys, feat.ye)
            fymax = max(feat.ys, feat.ye)
            if (pad_cx < fxmin - clearance - 0.5 or pad_cx > fxmax + clearance + 0.5
                    or pad_cy < fymin - clearance - 0.5 or pad_cy > fymax + clearance + 0.5):
                continue

            half_w = 0.0
            sym_ref = sym_lookup.get(feat.symbol_idx)
            if sym_ref is not None:
                ss = resolve_symbol(sym_ref.name)
                scale = _sym_scale(layer_units, sym_ref.unit_override)
                half_w = ss.width * scale / 2.0 if ss.width > 0 else 0.0

            d_sq = _point_to_segment_distance_sq(
                pad_cx, pad_cy, feat.xs, feat.ys, feat.xe, feat.ye)
            effective_r = clearance + half_w
            if d_sq <= effective_r * effective_r:
                net_name = net_lookup.get((layer_name, feat_idx), "")
                if net_name:
                    found_nets.add(net_name)

        elif isinstance(feat, ArcRecord):
            arc_r = math.hypot(feat.xs - feat.xc, feat.ys - feat.yc)
            if (abs(pad_cx - feat.xc) > arc_r + clearance + 0.5
                    or abs(pad_cy - feat.yc) > arc_r + clearance + 0.5):
                continue

            half_w = 0.0
            sym_ref = sym_lookup.get(feat.symbol_idx)
            if sym_ref is not None:
                ss = resolve_symbol(sym_ref.name)
                scale = _sym_scale(layer_units, sym_ref.unit_override)
                half_w = ss.width * scale / 2.0 if ss.width > 0 else 0.0

            d_sq = _point_to_arc_distance_sq(pad_cx, pad_cy, feat)
            effective_r = clearance + half_w
            if d_sq <= effective_r * effective_r:
                net_name = net_lookup.get((layer_name, feat_idx), "")
                if net_name:
                    found_nets.add(net_name)

        elif isinstance(feat, SurfaceRecord) and _HAS_SHAPELY:
            from src.visualizer.symbol_renderer import contour_to_vertices
            from shapely.geometry import Polygon as ShapelyPolygon

            pt = ShapelyPoint(pad_cx, pad_cy)
            inside_island = False
            inside_hole = False
            for contour in feat.contours:
                verts = contour_to_vertices(contour)
                if len(verts) < 3:
                    continue
                poly = ShapelyPolygon(verts)
                if contour.is_island:
                    if poly.contains(pt) or poly.distance(pt) < clearance:
                        inside_island = True
                else:
                    if poly.contains(pt):
                        inside_hole = True
            if inside_island and not inside_hole:
                net_name = net_lookup.get((layer_name, feat_idx), "")
                if net_name:
                    found_nets.add(net_name)

    return sorted(found_nets)


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------

def _shapely_to_arrays(geom):
    """Yield (xs, ys) numpy arrays for each ring of a Shapely geometry."""
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "Polygon":
        xs, ys = geom.exterior.xy
        yield np.array(xs), np.array(ys)
    elif geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        for part in geom.geoms:
            yield from _shapely_to_arrays(part)
    elif geom.geom_type in ("Point", "MultiPoint"):
        yield from _shapely_to_arrays(geom.buffer(0.02))


def _render_enhanced_pad_image(
    comp: Component,
    pkg: Package,
    cross_indices: list[int],
    nearby_signals: dict[int, list[str]],
    is_bottom: bool,
    output_path: Path,
    *,
    rule_id: str,
) -> Path:
    """Render a shield can highlighting enhanced pads and signal violations."""
    fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    layer_str = "Bottom" if is_bottom else "Top"
    has_fail = any(len(sigs) > 0 for sigs in nearby_signals.values())
    status = "FAIL" if has_fail else "PASS"
    ax.set_title(
        f"{comp.comp_name} ({comp.part_name}) — {layer_str} Layer\n"
        f"{rule_id}: Enhanced pad signal clearance  [{status}]",
        fontsize=12, fontweight="bold",
    )
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)

    all_xs, all_ys = [], []
    cross_set = set(cross_indices)

    for i, pin in enumerate(pkg.pins):
        for outline in pin.outlines:
            g = _outline_to_shapely(outline, comp, is_bottom=is_bottom)
            if g is not None and not g.is_empty:
                if i in cross_set:
                    sigs = nearby_signals.get(i, [])
                    if sigs:
                        fc, ec = "#FFB0B0", "darkred"
                    else:
                        fc, ec = "#FFFACD", "orange"
                else:
                    fc, ec = "#D0D0D0", "gray"

                for xs, ys in _shapely_to_arrays(g):
                    verts = list(zip(xs, ys))
                    ax.add_patch(MplPolygon(
                        verts, closed=True,
                        facecolor=fc, edgecolor=ec,
                        alpha=0.55, linewidth=1.0,
                    ))
                    all_xs.extend(xs)
                    all_ys.extend(ys)
                break

    # Draw clearance circles around cross pads
    for ci in cross_indices:
        if ci < len(pkg.pins):
            pin = pkg.pins[ci]
            bx, by = transform_point(
                pin.center.x, pin.center.y, comp, is_bottom=is_bottom)
            circle = plt.Circle(
                (bx, by), _CLEARANCE_MM,
                fill=False, edgecolor="red", linewidth=1.0,
                linestyle="--", alpha=0.7,
            )
            ax.add_patch(circle)

    # Component centre
    ax.plot(comp.x, comp.y, "x", color="blue", markersize=10,
            markeredgewidth=2)

    # Viewport
    if all_xs and all_ys:
        cx = (max(all_xs) + min(all_xs)) / 2
        cy = (max(all_ys) + min(all_ys)) / 2
        span = max(max(all_xs) - min(all_xs),
                   max(all_ys) - min(all_ys), 0.5)
        margin = span * 0.3
        ax.set_xlim(cx - span / 2 - margin, cx + span / 2 + margin)
        ax.set_ylim(cy - span / 2 - margin, cy + span / 2 + margin)

    # Legend
    legend_elements = [
        mpatches.Patch(facecolor="#D0D0D0", edgecolor="gray", alpha=0.55,
                       label="Normal pad"),
        mpatches.Patch(facecolor="#FFFACD", edgecolor="orange", alpha=0.55,
                       label="Enhanced pad (cross) - OK"),
    ]
    if has_fail:
        legend_elements.append(
            mpatches.Patch(facecolor="#FFB0B0", edgecolor="darkred",
                           alpha=0.55, label="Enhanced pad - signal too close"))
    legend_elements.append(
        plt.Line2D([], [], color="red", linewidth=1, linestyle="--",
                   label=f"Clearance zone ({_CLEARANCE_MM} mm)"))
    ax.legend(handles=legend_elements, loc="upper left", fontsize=8)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


# ---------------------------------------------------------------------------
# Rule
# ---------------------------------------------------------------------------

@register_rule
class CKL03014(ChecklistRule):
    rule_id = "CKL-03-014"
    description = (
        "실드캔 강성 개선 패드 하단에 위치한 SIGNAL 패턴들은 "
        "PAD fill cut 기준으로 0.2mm 이격할 것"
    )
    category = "Placement"

    def evaluate(self, job_data: dict) -> RuleResult:
        components_top = job_data.get("components_top", [])
        components_bot = job_data.get("components_bot", [])
        eda = job_data.get("eda_data")
        packages = eda.packages if eda else []
        layers_data = job_data.get("layers_data", {})

        columns = ["comp", "cmp_layer", "enhanced_pad", "signal", "status"]
        rows: list[dict] = []
        images: list[dict] = []
        image_dir = Path(tempfile.mkdtemp(prefix="ckl_03_014_"))

        if not _HAS_SHAPELY:
            return RuleResult(
                rule_id=self.rule_id,
                description=self.description,
                category=self.category,
                passed=False,
                message="Shapely 라이브러리가 설치되어 있지 않습니다.",
            )

        # Build net lookup once
        net_lookup = _build_net_lookup(eda)

        for comps, layer_name, is_bottom in [
            (components_top, "Top", False),
            (components_bot, "Bottom", True),
        ]:
            shield_cans = find_shield_cans(comps)

            # Get the signal layer directly below this component side
            sig_layer_name, sig_lf = _get_adjacent_signal_layer(
                layers_data, is_bottom)

            for comp in shield_cans:
                if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
                    continue
                pkg = packages[comp.pkg_ref]
                if not pkg.pins:
                    continue

                cross_indices = _get_cross_pad_indices(comp, pkg)
                has_enhanced = len(cross_indices) > 0

                if not has_enhanced:
                    # No enhanced pads → PASS
                    rows.append({
                        "comp": comp.comp_name,
                        "cmp_layer": layer_name,
                        "enhanced_pad": "FALSE",
                        "signal": "",
                        "status": "PASS",
                    })
                    continue

                # Check each cross pad for nearby signals
                nearby_signals: dict[int, list[str]] = {}
                all_signal_names: set[str] = set()

                if sig_layer_name is not None and sig_lf is not None:
                    for ci in cross_indices:
                        pin = pkg.pins[ci]
                        pad_cx, pad_cy = transform_point(
                            pin.center.x, pin.center.y,
                            comp, is_bottom=is_bottom,
                        )
                        signals = _find_signals_near_pad(
                            pad_cx, pad_cy,
                            sig_layer_name, sig_lf,
                            net_lookup,
                            clearance=_CLEARANCE_MM,
                        )
                        nearby_signals[ci] = signals
                        all_signal_names.update(signals)

                signal_str = ", ".join(sorted(all_signal_names)) if all_signal_names else ""
                status = "FAIL" if all_signal_names else "PASS"

                rows.append({
                    "comp": comp.comp_name,
                    "cmp_layer": layer_name,
                    "enhanced_pad": "TRUE",
                    "signal": signal_str,
                    "status": status,
                })

                # Generate visualisation
                safe_name = comp.comp_name.replace("/", "_")
                img_path = image_dir / f"{safe_name}_{layer_name}.png"
                _render_enhanced_pad_image(
                    comp, pkg, cross_indices, nearby_signals,
                    is_bottom, img_path,
                    rule_id=self.rule_id,
                )
                images.append({
                    "path": img_path,
                    "title": f"{comp.comp_name} ({layer_name})",
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
                f"강성 개선 패드 하단 {_CLEARANCE_MM}mm 이내에 SIGNAL이 "
                f"존재하는 실드캔이 {fail_count}건 감지되었습니다."
                if not passed
                else "모든 실드캔 강성 개선 패드 하단 SIGNAL 이격이 기준을 충족합니다."
            ),
            affected_components=[
                r["comp"] for r in rows if r["status"] == "FAIL"
            ],
            details={"columns": columns, "rows": rows},
            images=images,
        )
