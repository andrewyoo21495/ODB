"""Component outline and footprint polygon construction.

Provides:
- Pin outline → vertex extraction
- Board-coordinate shapely polygon construction (footprint / outline)
- Resolver helpers (_resolve_outline, _resolve_footprint)
- Pad-centre collection (_get_pad_centers)
- Edge/corner detection (is_on_edge)
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

import numpy as np

from src.models import Component, Package, Pin, PinOutline
from src.visualizer.component_overlay import transform_point, transform_pts
from src.visualizer.symbol_renderer import contour_to_vertices

try:
    from shapely.geometry import (
        MultiPoint,
        Point as ShapelyPoint,
        Polygon as ShapelyPolygon,
    )
    from shapely.ops import unary_union
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False


# ---------------------------------------------------------------------------
# Pin outline → vertices
# ---------------------------------------------------------------------------

def _outline_vertices(outline: PinOutline) -> list[tuple[float, float]]:
    """Extract vertices from a single PinOutline in package-local coords."""
    p = outline.params

    if outline.type in ("CR", "CT"):
        xc = p.get("xc", 0.0)
        yc = p.get("yc", 0.0)
        r = p.get("radius", 0.0)
        if r <= 0:
            return []
        angles = np.linspace(0, 2 * math.pi, 16, endpoint=False)
        return [(xc + r * math.cos(a), yc + r * math.sin(a)) for a in angles]

    if outline.type == "RC":
        llx = p.get("llx", 0.0)
        lly = p.get("lly", 0.0)
        w = p.get("width", 0.0)
        h = p.get("height", 0.0)
        if w <= 0 or h <= 0:
            return []
        return [
            (llx, lly), (llx + w, lly),
            (llx + w, lly + h), (llx, lly + h),
        ]

    if outline.type == "SQ":
        xc = p.get("xc", 0.0)
        yc = p.get("yc", 0.0)
        hs = p.get("half_side", 0.0)
        if hs <= 0:
            return []
        return [
            (xc - hs, yc - hs), (xc + hs, yc - hs),
            (xc + hs, yc + hs), (xc - hs, yc + hs),
        ]

    if outline.type == "CONTOUR" and outline.contour is not None:
        verts = contour_to_vertices(outline.contour)
        if len(verts) >= 2:
            return [tuple(v) for v in verts]

    return []


# ---------------------------------------------------------------------------
# Footprint and outline polygon construction
# ---------------------------------------------------------------------------

def get_component_footprint(comp: Component, pkg: Package,
                            *, is_bottom: bool = False):
    """Build a board-coordinate shapely Polygon from pin outline vertices.

    Returns a shapely Polygon (convex hull of all pin outline points),
    or None if no geometry is available or shapely is not installed.
    """
    if not _HAS_SHAPELY:
        return None

    all_points: list[tuple[float, float]] = []

    for pin in pkg.pins:
        for outline in pin.outlines:
            local_verts = _outline_vertices(outline)
            for lv in local_verts:
                bx, by = transform_point(lv[0], lv[1], comp, is_bottom=is_bottom)
                all_points.append((bx, by))

    for outline in pkg.outlines:
        local_verts = _outline_vertices(outline)
        for lv in local_verts:
            bx, by = transform_point(lv[0], lv[1], comp, is_bottom=is_bottom)
            all_points.append((bx, by))

    if len(all_points) >= 3:
        return MultiPoint(all_points).convex_hull

    if comp.toeprints:
        tp_pts = [(t.x, t.y) for t in comp.toeprints]
        if len(tp_pts) >= 3:
            return MultiPoint(tp_pts).convex_hull.buffer(0.005)
        if len(tp_pts) >= 1:
            return ShapelyPoint(tp_pts[0]).buffer(0.005)

    return None


def _outline_to_shapely(outline: PinOutline, comp: Component,
                        *, is_bottom: bool = False):
    """Convert a single PinOutline to a board-coordinate Shapely geometry.

    Preserves the exact original shape (circles, rectangles, squares,
    contours) rather than reducing everything to a convex hull.
    Returns a Shapely geometry or None for unknown / degenerate shapes.
    """
    if not _HAS_SHAPELY:
        return None

    p = outline.params

    if outline.type in ("CR", "CT"):
        xc = p.get("xc", 0.0)
        yc = p.get("yc", 0.0)
        r = p.get("radius", 0.0)
        if r <= 0:
            return None
        bx, by = transform_point(xc, yc, comp, is_bottom=is_bottom)
        return ShapelyPoint(bx, by).buffer(r, resolution=32)

    if outline.type == "RC":
        llx = p.get("llx", 0.0)
        lly = p.get("lly", 0.0)
        w = p.get("width", 0.0)
        h = p.get("height", 0.0)
        if w <= 0 or h <= 0:
            return None
        corners = [
            (llx, lly), (llx + w, lly),
            (llx + w, lly + h), (llx, lly + h),
        ]
        board_corners = [transform_point(x, y, comp, is_bottom=is_bottom) for x, y in corners]
        try:
            poly = ShapelyPolygon(board_corners)
            return poly if poly.is_valid and not poly.is_empty else None
        except Exception:
            return None

    if outline.type == "SQ":
        xc = p.get("xc", 0.0)
        yc = p.get("yc", 0.0)
        hs = p.get("half_side", 0.0)
        if hs <= 0:
            return None
        corners = [
            (xc - hs, yc - hs), (xc + hs, yc - hs),
            (xc + hs, yc + hs), (xc - hs, yc + hs),
        ]
        board_corners = [transform_point(x, y, comp, is_bottom=is_bottom) for x, y in corners]
        try:
            poly = ShapelyPolygon(board_corners)
            return poly if poly.is_valid and not poly.is_empty else None
        except Exception:
            return None

    if outline.type == "CONTOUR" and outline.contour is not None:
        verts = contour_to_vertices(outline.contour)
        if len(verts) < 3:
            return None
        board_verts = [transform_point(v[0], v[1], comp, is_bottom=is_bottom) for v in verts]
        try:
            poly = ShapelyPolygon(board_verts)
            return poly if poly.is_valid and not poly.is_empty else None
        except Exception:
            return None

    return None


def get_component_outline(comp: Component, pkg: Package,
                          *, is_bottom: bool = False):
    """Build a board-coordinate polygon from package-level outlines only.

    Unlike get_component_footprint (which includes pin/pad outlines), this
    returns only the physical component body outline.  Each outline entry is
    converted to its exact Shapely geometry and combined with unary_union.
    """
    if not _HAS_SHAPELY:
        return None

    geoms = []
    for outline in pkg.outlines:
        g = _outline_to_shapely(outline, comp, is_bottom=is_bottom)
        if g is not None:
            geoms.append(g)

    if not geoms:
        return None

    result = unary_union(geoms)
    if result.is_empty:
        return None
    return result


def _resolve_outline(comp: Component, packages: list[Package],
                     *, is_bottom: bool = False):
    """Look up the package and build the component outline polygon."""
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return None
    pkg = packages[comp.pkg_ref]
    return get_component_outline(comp, pkg, is_bottom=is_bottom)


def _resolve_footprint(comp: Component, packages: list[Package],
                       *, is_bottom: bool = False):
    """Look up the package and build the footprint polygon."""
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return None
    pkg = packages[comp.pkg_ref]
    return get_component_footprint(comp, pkg, is_bottom=is_bottom)


# ---------------------------------------------------------------------------
# Pad centre collection
# ---------------------------------------------------------------------------

def _get_pad_centers(comp: Component, packages: list[Package],
                     *, is_bottom: bool = False,
                     ) -> list[tuple[float, float]]:
    """Return board-coordinate centre points for each pad of comp.

    Falls back to toeprint positions when package pin data is unavailable.
    """
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return []
    pkg = packages[comp.pkg_ref]

    if pkg.pins:
        return [
            transform_point(pin.center.x, pin.center.y, comp,
                            is_bottom=is_bottom)
            for pin in pkg.pins
        ]

    if comp.toeprints:
        return [(tp.x, tp.y) for tp in comp.toeprints]

    return []


# ---------------------------------------------------------------------------
# Edge / corner detection
# ---------------------------------------------------------------------------

def is_on_edge(comp_a: Component, comp_b: Component,
               packages: list[Package],
               tolerance: float = 0.254) -> bool:
    """Return True if any pad of comp_a is in a corner area of comp_b's outline.

    Args:
        tolerance: Radius in mm around each corner vertex to consider
                   as the corner area.
    """
    if not _HAS_SHAPELY:
        return False

    pad_centers = _get_pad_centers(comp_a, packages)
    outline_b = _resolve_outline(comp_b, packages)

    if not pad_centers or outline_b is None:
        return False

    corners: list[tuple[float, float]] = []
    if hasattr(outline_b, "geoms"):
        for g in outline_b.geoms:
            if hasattr(g, "exterior"):
                corners.extend(g.exterior.coords[:-1])
    elif hasattr(outline_b, "exterior"):
        corners = list(outline_b.exterior.coords[:-1])

    for cx, cy in corners:
        corner_region = ShapelyPoint(cx, cy).buffer(tolerance)
        for px, py in pad_centers:
            if corner_region.contains(ShapelyPoint(px, py)):
                return True

    return False
