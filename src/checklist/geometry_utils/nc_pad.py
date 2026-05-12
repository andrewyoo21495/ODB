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
    return ShapelyPoint(bx, by).buffer(tolerance)


def _non_pad_feature_to_geometry(feat, sym_lookup: dict):
    """Convert a non-pad layer feature to a Shapely geometry.

    Handles LineRecord, ArcRecord, and SurfaceRecord.  PadRecords are
    intentionally excluded (the caller skips them).
    """
    if isinstance(feat, LineRecord):
        sym_ref = sym_lookup.get(feat.symbol_idx)
        half_w = 0.0
        if sym_ref is not None:
            ss = resolve_symbol(sym_ref.name)
            half_w = ss.width / 2.0 if ss.width > 0 else 0.0
        line = LineString([(feat.xs, feat.ys), (feat.xe, feat.ye)])
        return line.buffer(half_w) if half_w > 0 else line

    if isinstance(feat, ArcRecord):
        sym_ref = sym_lookup.get(feat.symbol_idx)
        half_w = 0.0
        if sym_ref is not None:
            ss = resolve_symbol(sym_ref.name)
            half_w = ss.width / 2.0 if ss.width > 0 else 0.0
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


def is_pad_nc_by_signal_layer(
    comp: Component,
    pin: Pin,
    is_bottom: bool,
    layers_data: dict,
    signal_layer_name: str | None,
    resolved_pads: list | None = None,
    toeprint: Toeprint | None = None,
    tolerance: float = 0.01,
) -> bool:
    """Return True if no traces, arcs, or copper planes on the signal layer
    physically connect to the pad.

    The check examines only the signal layer that corresponds to the
    component's placement side (top signal layer for top-placed components,
    bottom signal layer for bottom-placed components).  PadRecords on the
    signal layer are intentionally excluded so the pad's own copper
    footprint does not count as a connection.

    Falls back to ``False`` (assume connected) when Shapely is unavailable
    or the signal layer data cannot be inspected.
    """
    if not _HAS_SHAPELY:
        return False
    if signal_layer_name is None or signal_layer_name not in layers_data:
        return False

    lf, _ml = layers_data[signal_layer_name]

    # Guard against selectively-loaded layers where most features are None.
    none_count = sum(1 for f in lf.features if f is None)
    if none_count > len(lf.features) // 2:
        return False

    pad_geom = _pad_to_shapely(
        comp, pin, is_bottom, resolved_pads, toeprint, tolerance)
    if pad_geom is None or pad_geom.is_empty:
        return False

    buffered = pad_geom.buffer(tolerance)
    prep_buffered = buffered  # Shapely intersects is fast enough here

    sym_lookup = {s.index: s for s in lf.symbols}

    from src.models import PadRecord
    for feat in lf.features:
        if feat is None:
            continue
        if isinstance(feat, PadRecord):
            continue
        geom = _non_pad_feature_to_geometry(feat, sym_lookup)
        if geom is None or geom.is_empty:
            continue
        if prep_buffered.intersects(geom):
            return False  # Connected – a non-pad feature touches this pad

    return True  # No non-pad feature touches this pad → NC
