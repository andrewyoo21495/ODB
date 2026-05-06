"""PCB outline clearance checking.

Provides:
- build_board_polygon                    — Shapely Polygon from board profile
- build_inset_boundary                   — inward-offset clearance boundary
- distance_to_outline                    — pin-centre to outline distance
- pad_distance_to_outline                — pad geometry to outline distance
- pad_distance_to_component              — pad geometry to footprint distance
- pad_to_pad_distance                    — pad-to-pad distance
- components_in_clearance_zone           — toeprint-based clearance check
- components_with_pads_in_clearance_zone — pad-geometry clearance check
- signal_features_in_clearance_zone      — signal-layer copper clearance check
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

from src.models import ArcRecord, Component, EdaData, LineRecord, PadRecord
from src.parsers.symbol_resolver import resolve_symbol
from src.visualizer.symbol_renderer import contour_to_vertices
from .distance import center_distance, edge_distance
from .overlap import _get_pad_union
from .polygon import _resolve_footprint

try:
    from shapely.geometry import (
        LineString,
        Point as ShapelyPoint,
        Polygon as ShapelyPolygon,
    )
    from shapely.ops import unary_union
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False


def build_board_polygon(profile) -> Optional[object]:
    """Construct a shapely Polygon from the board profile.

    Returns None if shapely is unavailable or no valid contour is found.
    """
    if not _HAS_SHAPELY or not profile or not profile.surface:
        return None

    for contour in profile.surface.contours:
        if contour.is_island:
            verts = contour_to_vertices(contour)
            if len(verts) >= 3:
                poly = ShapelyPolygon(verts)
                if poly.is_valid:
                    return poly
    return None


def build_inset_boundary(board_poly, inset_mm: float = 0.65):
    """Return a polygon inset_mm inward from board_poly's boundary.

    Returns None on failure.
    """
    if not _HAS_SHAPELY or board_poly is None:
        return None
    inset = board_poly.buffer(-inset_mm)
    if inset.is_empty or not inset.is_valid:
        return None
    return inset


def distance_to_outline(comp: Component, board_poly,
                        packages: list | None = None) -> float:
    """Return the minimum distance from any pin/pad of comp to the board outline.

    Falls back to centre-point distance if no pin geometry is available.
    """
    if not _HAS_SHAPELY or board_poly is None:
        return float("inf")

    outline = board_poly.boundary
    min_dist = float("inf")

    if comp.toeprints:
        for tp in comp.toeprints:
            d = outline.distance(ShapelyPoint(tp.x, tp.y))
            if d < min_dist:
                min_dist = d
        return min_dist

    return outline.distance(ShapelyPoint(comp.x, comp.y))


def pad_distance_to_outline(comp: Component, board_poly,
                            packages: list | None = None,
                            *, is_bottom: bool = False,
                            user_symbols: dict | None = None) -> float:
    """Return the minimum distance from comp's pad geometry to the board outline."""
    if not _HAS_SHAPELY or board_poly is None:
        return float("inf")

    outline = board_poly.boundary

    if packages is not None:
        pad_geom = _get_pad_union(comp, packages, is_bottom=is_bottom,
                                  user_symbols=user_symbols)
        if pad_geom is not None:
            return outline.distance(pad_geom)

    if comp.toeprints:
        return min(
            outline.distance(ShapelyPoint(tp.x, tp.y))
            for tp in comp.toeprints
        )

    return outline.distance(ShapelyPoint(comp.x, comp.y))


def pad_distance_to_component(comp: Component, other: Component,
                              packages: list,
                              *, is_bottom: bool = False,
                              user_symbols: dict | None = None) -> float:
    """Return the minimum distance from comp's pads to other's footprint."""
    if not _HAS_SHAPELY:
        return center_distance(comp, other)

    pad_geom = _get_pad_union(comp, packages, is_bottom=is_bottom,
                              user_symbols=user_symbols)
    fp_other = _resolve_footprint(other, packages)

    if pad_geom is None or fp_other is None:
        return float("inf")

    return pad_geom.distance(fp_other)


def pad_to_pad_distance(
    comp_a: Component, comp_b: Component,
    packages: list,
    *,
    is_bottom_a: bool = False,
    is_bottom_b: bool = False,
    user_symbols: dict | None = None,
) -> float:
    """Return the minimum distance between comp_a's pads and comp_b's pads.

    Falls back to edge_distance when pad geometry is unavailable.
    """
    if not _HAS_SHAPELY:
        return edge_distance(comp_a, comp_b, packages)

    pad_a = _get_pad_union(comp_a, packages, is_bottom=is_bottom_a,
                           user_symbols=user_symbols)
    pad_b = _get_pad_union(comp_b, packages, is_bottom=is_bottom_b,
                           user_symbols=user_symbols)

    if pad_a is None or pad_b is None:
        return edge_distance(comp_a, comp_b, packages)

    return pad_a.distance(pad_b)


def components_in_clearance_zone(
    components: Sequence[Component],
    board_poly,
    inset_poly,
    packages: list | None = None,
) -> list[tuple[Component, float]]:
    """Return components with pins/pads in the clearance zone.

    Returns list of (component, min_distance_to_outline).
    """
    if not _HAS_SHAPELY or board_poly is None or inset_poly is None:
        return []

    outline = board_poly.boundary
    results: list[tuple[Component, float]] = []

    for comp in components:
        in_zone = False
        min_dist = float("inf")

        if comp.toeprints:
            for tp in comp.toeprints:
                pt = ShapelyPoint(tp.x, tp.y)
                if board_poly.contains(pt) and not inset_poly.contains(pt):
                    in_zone = True
                    d = outline.distance(pt)
                    if d < min_dist:
                        min_dist = d
                elif not board_poly.contains(pt):
                    in_zone = True
                    d = outline.distance(pt)
                    if d < min_dist:
                        min_dist = d
        else:
            pt = ShapelyPoint(comp.x, comp.y)
            if board_poly.contains(pt) and not inset_poly.contains(pt):
                in_zone = True
                min_dist = outline.distance(pt)
            elif not board_poly.contains(pt):
                in_zone = True
                min_dist = outline.distance(pt)

        if in_zone:
            results.append((comp, min_dist))

    return results


def components_with_pads_in_clearance_zone(
    components: Sequence[Component],
    board_poly,
    inset_poly,
    packages: list | None = None,
) -> list[tuple[Component, float]]:
    """Return components whose pad geometry intersects the clearance zone.

    Returns [(component, min_pad_distance_to_outline), ...].
    """
    if not _HAS_SHAPELY or board_poly is None or inset_poly is None:
        return []

    outline = board_poly.boundary
    clearance_zone = board_poly.difference(inset_poly)
    if clearance_zone.is_empty:
        return []

    results: list[tuple[Component, float]] = []

    for comp in components:
        pad_geom = None
        if packages is not None:
            pad_geom = _get_pad_union(comp, packages)

        if pad_geom is None:
            if comp.toeprints:
                for tp in comp.toeprints:
                    pt = ShapelyPoint(tp.x, tp.y)
                    if clearance_zone.contains(pt) or not board_poly.contains(pt):
                        results.append((comp, outline.distance(pt)))
                        break
            else:
                pt = ShapelyPoint(comp.x, comp.y)
                if clearance_zone.contains(pt) or not board_poly.contains(pt):
                    results.append((comp, outline.distance(pt)))
            continue

        pad_in_zone = pad_geom.intersects(clearance_zone)
        pad_outside = not board_poly.contains(pad_geom)

        if pad_in_zone or pad_outside:
            dist = outline.distance(pad_geom)
            results.append((comp, dist))

    return results


def signal_features_in_clearance_zone(
    layers_data: dict,
    board_poly,
    inset_poly,
    eda_data: EdaData | None = None,
) -> list[dict]:
    """Return signal-layer features whose geometry enters the clearance zone.

    Returns a list of dicts:
        {"layer_name": str, "net_name": str, "feature_type": str,
         "distance": str, "status": str}
    """
    from src.visualizer.fid_lookup import build_layer_name_map

    if not _HAS_SHAPELY or board_poly is None or inset_poly is None:
        return []

    outline = board_poly.boundary
    clearance_zone = board_poly.difference(inset_poly)
    if clearance_zone.is_empty:
        return []

    net_lookup: dict[tuple[str, int], str] = {}
    if eda_data is not None:
        layer_name_map = build_layer_name_map(eda_data.layer_names)
        for net in eda_data.nets:
            for subnet in net.subnets:
                for fid in subnet.feature_ids:
                    if fid.type != "C":
                        continue
                    lname = layer_name_map.get(fid.layer_idx)
                    if lname is not None:
                        net_lookup[(lname, fid.feature_idx)] = net.name

    signal_layers: list[tuple[str, object, object]] = []
    for name, (lf, ml) in layers_data.items():
        if ml.type == "SIGNAL":
            signal_layers.append((name, lf, ml))

    results: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for layer_name, lf, _ml in signal_layers:
        sym_lookup = {s.index: s for s in lf.symbols}

        for feat_idx, feat in enumerate(lf.features):
            geom = _feature_to_geometry(feat, sym_lookup)
            if geom is None:
                continue

            in_zone = geom.intersects(clearance_zone)
            outside = not board_poly.contains(geom)
            if not (in_zone or outside):
                continue

            net_name = net_lookup.get((layer_name, feat_idx), "")

            key = (layer_name, net_name)
            if key in seen:
                continue
            seen.add(key)

            dist = outline.distance(geom)
            feat_type = type(feat).__name__.replace("Record", "")
            results.append({
                "layer_name": layer_name,
                "net_name": net_name,
                "feature_type": feat_type,
                "distance": f"{dist:.3f}",
                "status": "FAIL",
            })

    return results


def _feature_to_geometry(feat, sym_lookup: dict):
    """Convert a layer feature record to a Shapely geometry."""
    if not _HAS_SHAPELY:
        return None

    if isinstance(feat, PadRecord):
        sym_ref = sym_lookup.get(feat.symbol_idx)
        radius = 0.05
        if sym_ref is not None:
            ss = resolve_symbol(sym_ref.name)
            radius = max(ss.width, ss.height) / 2.0 if ss.width > 0 else 0.05
        return ShapelyPoint(feat.x, feat.y).buffer(radius)

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
