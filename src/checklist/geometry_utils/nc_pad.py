"""NC (Not Connected) pad detection."""

from __future__ import annotations

import math

from src.models import (
    ArcRecord,
    Component,
    EdaData,
    LineRecord,
    Pin,
    SurfaceRecord,
    Toeprint,
)
from src.parsers.symbol_resolver import resolve_symbol

try:
    from shapely.geometry import (
        LineString,
        Point as ShapelyPoint,
        Polygon as ShapelyPolygon,
    )
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False

_NC_NET_NAMES = frozenset({"$NONE$", "NC", "NO_CONNECT", ""})


def is_pad_nc(
    toeprint: Toeprint | None,
    eda_data: EdaData | None,
) -> bool:
    """Return True if the pad has no net connection (NC).

    Detection logic (checked in order):
    1. toeprint is None or net_num < 0 → NC
    2. net_num out of range → NC
    3. Net name matches a known NC pattern → NC
    4. Net has no TRC/VIA/PLN subnets (only TOP) → NC
    """
    if toeprint is None:
        return False
    if toeprint.net_num < 0:
        return True
    if eda_data is None:
        return False
    if toeprint.net_num >= len(eda_data.nets):
        return True

    net = eda_data.nets[toeprint.net_num]

    if (net.name or "").strip().upper() in _NC_NET_NAMES:
        return True

    for subnet in net.subnets:
        if subnet.type in ("TRC", "VIA", "PLN"):
            return False

    return True


# ---------------------------------------------------------------------------
# Signal-layer-based NC detection
# ---------------------------------------------------------------------------

def _pad_to_shapely(
    comp: Component,
    pin: Pin,
    is_bottom: bool,
    resolved_pads: list | None,
    toeprint: Toeprint | None,
    tolerance: float,
):
    """Build a Shapely geometry for a pad in board coordinates.

    Resolution priority mirrors :func:`count_vias_at_pad`:
      1. FID-resolved pad polygons
      2. EDA pin outline polygon
      3. Centre point buffered by *tolerance*
    """
    from .via import _resolved_pad_polygon, _get_pad_polygon_board

    # 1. FID-resolved pads
    if resolved_pads:
        polys = []
        for rpf in resolved_pads:
            verts = _resolved_pad_polygon(rpf, is_bottom=is_bottom)
            if verts is not None and len(verts) >= 3:
                polys.append(ShapelyPolygon(verts))
        if polys:
            from shapely.ops import unary_union
            return unary_union(polys)

    # 2. EDA pin outline
    verts = _get_pad_polygon_board(pin, comp, is_bottom=is_bottom)
    if verts is not None and len(verts) >= 3:
        return ShapelyPolygon(verts)

    # 3. Fallback – buffered centre point
    from src.visualizer.component_overlay import transform_point
    bx, by = transform_point(
        pin.center.x, pin.center.y, comp, is_bottom=is_bottom)
    return ShapelyPoint(bx, by).buffer(max(tolerance, 0.1))


def _sym_scale(units: str, unit_override: str | None) -> float:
    """Return the factor that converts raw symbol dimensions to MM.

    Standard symbol name numbers are in the *sub-unit* of the layer's
    declared unit system:
      - INCH → mils  (×0.0254 → mm)
      - MM   → µm    (÷1000  → mm)

    A per-symbol ``unit_override`` (``"I"`` or ``"M"``) takes precedence.
    """
    if unit_override == "I":
        return 0.0254
    if unit_override == "M":
        return 0.001
    return 0.0254 if units == "INCH" else 0.001


def _non_pad_feature_to_geometry(feat, sym_lookup: dict, layer_units: str):
    """Convert a non-pad layer feature to a Shapely geometry.

    Handles LineRecord, ArcRecord, and SurfaceRecord.  PadRecords are
    intentionally excluded (the caller skips them).

    *layer_units* is the original unit system of the feature file (before
    coordinate scaling) and is needed to correctly convert symbol dimensions
    (encoded as mils or µm) to MM.
    """
    if isinstance(feat, LineRecord):
        sym_ref = sym_lookup.get(feat.symbol_idx)
        half_w = 0.0
        if sym_ref is not None:
            ss = resolve_symbol(sym_ref.name)
            scale = _sym_scale(layer_units, sym_ref.unit_override)
            half_w = ss.width * scale / 2.0 if ss.width > 0 else 0.0
        line = LineString([(feat.xs, feat.ys), (feat.xe, feat.ye)])
        return line.buffer(half_w) if half_w > 0 else line

    if isinstance(feat, ArcRecord):
        sym_ref = sym_lookup.get(feat.symbol_idx)
        half_w = 0.0
        if sym_ref is not None:
            ss = resolve_symbol(sym_ref.name)
            scale = _sym_scale(layer_units, sym_ref.unit_override)
            half_w = ss.width * scale / 2.0 if ss.width > 0 else 0.0
        pts = _arc_to_points(feat)
        if len(pts) >= 2:
            line = LineString(pts)
            return line.buffer(half_w) if half_w > 0 else line

    if isinstance(feat, SurfaceRecord):
        from src.visualizer.symbol_renderer import contour_to_vertices
        for contour in feat.contours:
            if not contour.is_island:
                continue
            verts = contour_to_vertices(contour)
            if len(verts) >= 3:
                return ShapelyPolygon(verts)

    return None


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


# ---------------------------------------------------------------------------
# Helpers for centre-circle NC detection
# ---------------------------------------------------------------------------

def _get_pad_center(comp, pin, is_bottom, toeprint):
    """Return pad centre in board coordinates."""
    if toeprint is not None:
        return toeprint.x, toeprint.y
    from src.visualizer.component_overlay import transform_point
    return transform_point(pin.center.x, pin.center.y, comp, is_bottom=is_bottom)


def _point_to_segment_distance_sq(
    px: float, py: float,
    ax: float, ay: float,
    bx: float, by: float,
) -> float:
    """Return the squared distance from point (px, py) to segment (a→b)."""
    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-18:
        # Degenerate segment (zero length)
        ex, ey = px - ax, py - ay
        return ex * ex + ey * ey
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    ex, ey = px - proj_x, py - proj_y
    return ex * ex + ey * ey


def _point_to_arc_distance_sq(
    px: float, py: float, feat, segments: int = 16,
) -> float:
    """Return the squared distance from (px, py) to an arc polyline."""
    pts = _arc_to_points(feat, segments)
    min_d_sq = float("inf")
    for i in range(len(pts) - 1):
        d_sq = _point_to_segment_distance_sq(
            px, py, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
        if d_sq < min_d_sq:
            min_d_sq = d_sq
    return min_d_sq


def is_pad_nc_by_signal_layer(
    comp: Component,
    pin: Pin,
    is_bottom: bool,
    layers_data: dict,
    signal_layer_name: str | None,
    resolved_pads: list | None = None,
    toeprint: Toeprint | None = None,
    tolerance: float = 0.05,
    search_radius: float = 0.3,
) -> bool:
    """Return True if no signal traces connect to the pad.

    The detection builds a small circle (``search_radius``) around the
    pin centre and checks whether any **trace** (LineRecord / ArcRecord)
    passes through this circle.

    *   A **LineRecord** or **ArcRecord** is considered connecting if the
        minimum distance from the pin centre to the line/arc segment is
        less than ``search_radius`` (accounting for the trace's own width
        when the symbol is resolvable).
    *   A **SurfaceRecord** (copper fill / pour) is considered connecting
        only when the pin centre is inside an island contour AND NOT
        inside any hole contour.  NC pads typically have clearance holes
        cut out in the pour, so they will not match.
    *   **PadRecords** are excluded (the pad's own copper should not
        count as a connection).

    Falls back to ``False`` (assume connected) when the signal layer
    data cannot be inspected.
    """
    if signal_layer_name is None or signal_layer_name not in layers_data:
        return False

    lf, _ml = layers_data[signal_layer_name]

    # Guard against selectively-loaded layers where most features are None.
    none_count = sum(1 for f in lf.features if f is None)
    if none_count > len(lf.features) // 2:
        return False

    from src.models import PadRecord

    pad_cx, pad_cy = _get_pad_center(comp, pin, is_bottom, toeprint)

    sym_lookup = {s.index: s for s in lf.symbols}
    layer_units = lf.units
    search_r_sq = search_radius * search_radius

    for feat in lf.features:
        if feat is None or isinstance(feat, PadRecord):
            continue

        if isinstance(feat, LineRecord):
            # Quick bounding-box pre-filter
            fxmin = min(feat.xs, feat.xe)
            fxmax = max(feat.xs, feat.xe)
            fymin = min(feat.ys, feat.ye)
            fymax = max(feat.ys, feat.ye)
            if (pad_cx < fxmin - search_radius or pad_cx > fxmax + search_radius
                    or pad_cy < fymin - search_radius or pad_cy > fymax + search_radius):
                continue

            # Resolve trace half-width from symbol
            half_w = 0.0
            sym_ref = sym_lookup.get(feat.symbol_idx)
            if sym_ref is not None:
                ss = resolve_symbol(sym_ref.name)
                scale = _sym_scale(layer_units, sym_ref.unit_override)
                half_w = ss.width * scale / 2.0 if ss.width > 0 else 0.0

            d_sq = _point_to_segment_distance_sq(
                pad_cx, pad_cy, feat.xs, feat.ys, feat.xe, feat.ye)
            effective_r = search_radius + half_w
            if d_sq <= effective_r * effective_r:
                return False  # Connected

        elif isinstance(feat, ArcRecord):
            # Quick bounding-box pre-filter using arc centre + radius
            arc_r = math.hypot(feat.xs - feat.xc, feat.ys - feat.yc)
            if (abs(pad_cx - feat.xc) > arc_r + search_radius + 0.5
                    or abs(pad_cy - feat.yc) > arc_r + search_radius + 0.5):
                continue

            half_w = 0.0
            sym_ref = sym_lookup.get(feat.symbol_idx)
            if sym_ref is not None:
                ss = resolve_symbol(sym_ref.name)
                scale = _sym_scale(layer_units, sym_ref.unit_override)
                half_w = ss.width * scale / 2.0 if ss.width > 0 else 0.0

            d_sq = _point_to_arc_distance_sq(pad_cx, pad_cy, feat)
            effective_r = search_radius + half_w
            if d_sq <= effective_r * effective_r:
                return False  # Connected

        elif isinstance(feat, SurfaceRecord) and _HAS_SHAPELY:
            # A copper pour covers large areas, but NC pads have
            # clearance holes cut out around them.  Check that the pad
            # centre is inside an island contour AND NOT inside any
            # hole contour.
            from src.visualizer.symbol_renderer import contour_to_vertices
            pt = ShapelyPoint(pad_cx, pad_cy)
            inside_island = False
            inside_hole = False
            for contour in feat.contours:
                verts = contour_to_vertices(contour)
                if len(verts) < 3:
                    continue
                poly = ShapelyPolygon(verts)
                if contour.is_island:
                    if poly.contains(pt):
                        inside_island = True
                else:
                    if poly.contains(pt):
                        inside_hole = True
            if inside_island and not inside_hole:
                return False  # Connected to plane directly

    return True  # No feature connects to this pad → NC
