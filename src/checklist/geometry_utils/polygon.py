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
    from shapely.validation import make_valid
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
            if poly.is_empty:
                return None
            if not poly.is_valid:
                poly = make_valid(poly)
                if poly.is_empty:
                    return None
            return poly
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
            if poly.is_empty:
                return None
            if not poly.is_valid:
                poly = make_valid(poly)
                if poly.is_empty:
                    return None
            return poly
        except Exception:
            return None

    if outline.type == "CONTOUR" and outline.contour is not None:
        verts = contour_to_vertices(outline.contour)
        if len(verts) < 3:
            return None
        board_verts = [transform_point(v[0], v[1], comp, is_bottom=is_bottom) for v in verts]
        try:
            poly = ShapelyPolygon(board_verts)
            if poly.is_empty:
                return None
            if not poly.is_valid:
                poly = make_valid(poly)
                if poly.is_empty:
                    return None
            return poly
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


def _build_outer_boundary_from_pins(comp: Component, pkg: Package,
                                     *, is_bottom: bool = False):
    """Build a boundary polygon from the outermost pins (concave hull).

    Used as a fallback for containers (interposers, shield cans) when
    ``pkg.outlines`` does not produce valid geometry.  The outer-border
    pins are used to form a concave hull that approximates the physical
    container boundary.
    """
    if not _HAS_SHAPELY or not pkg.pins:
        return None

    from .overlap import find_outermost_pin_indices

    outermost = find_outermost_pin_indices(pkg.pins)
    if len(outermost) < 3:
        return None

    from src.visualizer.component_overlay import transform_point
    pts = []
    for idx in outermost:
        pin = pkg.pins[idx]
        bx, by = transform_point(pin.center.x, pin.center.y, comp,
                                 is_bottom=is_bottom)
        pts.append((bx, by))

    try:
        from shapely.geometry import MultiPoint
        hull = MultiPoint(pts).convex_hull
        if hull.is_valid and not hull.is_empty and hull.geom_type == "Polygon":
            return hull
    except Exception:
        pass
    return None


def get_container_interior(comp: Component, pkg: Package,
                           *, is_bottom: bool = False):
    """Build a filled interior polygon for a container component (SC/INP).

    The interior region must match the **CONTAINER FRAME** shown in the
    visualization (the dashed outline produced by ``get_component_outline``).
    Everything inside the frame's outer boundary is "INSIDE"; everything
    outside is "OUTSIDE".

    Strategy:
    1. Compute the component outline via ``get_component_outline`` — this is
       the same ``unary_union`` of all ``pkg.outlines`` used for the dashed
       container frame in visualizations.
    2. Fill the outline (remove holes) so that containment checks treat the
       entire region enclosed by the outer boundary as interior.

    Fallback chain (for both shield cans and interposers):
      a. ``pkg.outlines`` → filled outer boundary
      b. Outer-border pin concave hull (preserves shape for ring-like layouts)
      c. ``get_component_footprint`` (convex hull of all pads / toeprints)
    """
    if not _HAS_SHAPELY:
        return None

    outline = get_component_outline(comp, pkg, is_bottom=is_bottom)
    if outline is not None:
        # Fill the outline by removing holes so that containment checks
        # match the visible container frame boundary.
        if hasattr(outline, "exterior"):
            # Single Polygon — fill by using only the exterior ring.
            return ShapelyPolygon(outline.exterior)

        if hasattr(outline, "geoms"):
            # MultiPolygon / GeometryCollection — fill each sub-polygon and union.
            filled = []
            for g in outline.geoms:
                if hasattr(g, "exterior"):
                    filled.append(ShapelyPolygon(g.exterior))
            if filled:
                return unary_union(filled)

        return outline

    # Fallback: build boundary from outermost pins (works for interposers
    # that lack outline data but have a ring-shaped pin layout).
    pin_hull = _build_outer_boundary_from_pins(comp, pkg, is_bottom=is_bottom)
    if pin_hull is not None:
        return pin_hull

    return get_component_footprint(comp, pkg, is_bottom=is_bottom)


def _resolve_container_interior(comp: Component, packages: list[Package],
                                *, is_bottom: bool = False):
    """Look up the package and build the filled container interior polygon."""
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return None
    pkg = packages[comp.pkg_ref]
    return get_container_interior(comp, pkg, is_bottom=is_bottom)


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

def _get_outline_short_edges(
    outline_b,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Return the two short-side line segments of *outline_b*.

    For a rectangular outline, compares adjacent edge lengths and returns
    the two shortest edges.  If the outline is not a simple polygon or
    has fewer than 4 vertices, returns an empty list.
    """
    coords: list[tuple[float, float]] = []
    if hasattr(outline_b, "geoms"):
        for g in outline_b.geoms:
            if hasattr(g, "exterior"):
                coords = list(g.exterior.coords[:-1])
                break
    elif hasattr(outline_b, "exterior"):
        coords = list(outline_b.exterior.coords[:-1])

    if len(coords) < 4:
        return []

    # Build list of edges with their lengths
    edges: list[tuple[float, tuple[tuple[float, float], tuple[float, float]]]] = []
    n = len(coords)
    for i in range(n):
        p1 = coords[i]
        p2 = coords[(i + 1) % n]
        length = math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)
        edges.append((length, (p1, p2)))

    # Sort by length and take the shorter half (for a rectangle, the 2
    # shortest edges are the "short sides")
    edges.sort(key=lambda e: e[0])
    short_len = edges[0][0]

    # Collect edges whose length is close to the shortest (within 20%)
    threshold = short_len * 1.2
    short_edges = [seg for length, seg in edges if length <= threshold]

    return short_edges


def is_on_edge(comp_a: Component, comp_b: Component,
               packages: list[Package],
               tolerance: float = 0.254) -> bool:
    """Return True if any pad of comp_a is in an edge area of comp_b.

    Three detection methods are used (returns True if any matches):

    1. **Outline corner check**: any pad of *comp_a* falls within
       *tolerance* of an outline polygon vertex of *comp_b*.
    2. **Short-edge check**: for a rectangular outline, the two shorter
       sides are identified.  Any pad of *comp_a* within *tolerance* of
       these short edges is considered on the edge.
    3. **Corner-pad check**: the four pads of *comp_b* closest to its
       bounding-box corners are identified.  If any pad of *comp_a* is
       within *tolerance* of a corner pad **and** lies on the outward
       side (away from *comp_b*'s centre), it is considered on the edge.

    Args:
        tolerance: Radius in mm around each corner vertex / corner pad
                   / short edge to consider as the edge area.
    """
    if not _HAS_SHAPELY:
        return False

    pad_centers = _get_pad_centers(comp_a, packages)
    outline_b = _resolve_outline(comp_b, packages)

    if not pad_centers:
        return False

    # --- 1. Outline corner check -------------------------------------------
    if outline_b is not None:
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

    # --- 2. Short-edge check -----------------------------------------------
    if outline_b is not None:
        from shapely.geometry import LineString as _LS

        short_edges = _get_outline_short_edges(outline_b)
        for (x1, y1), (x2, y2) in short_edges:
            edge_line = _LS([(x1, y1), (x2, y2)])
            edge_zone = edge_line.buffer(tolerance)
            for px, py in pad_centers:
                if edge_zone.contains(ShapelyPoint(px, py)):
                    return True

    # --- 3. Corner-pad check -----------------------------------------------
    pad_centers_b = _get_pad_centers(comp_b, packages)
    if not pad_centers_b or len(pad_centers_b) < 4:
        return False

    # Bounding box of comp_b (prefer outline, fall back to pads)
    if outline_b is not None:
        minx, miny, maxx, maxy = outline_b.bounds
    else:
        xs_b = [p[0] for p in pad_centers_b]
        ys_b = [p[1] for p in pad_centers_b]
        minx, miny, maxx, maxy = min(xs_b), min(ys_b), max(xs_b), max(ys_b)

    bbox_corners = [(minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)]

    # For each bbox corner, find the nearest pad of comp_b
    corner_pad_indices: set[int] = set()
    for bcx, bcy in bbox_corners:
        best_idx: int | None = None
        best_dist = float("inf")
        for i, (px, py) in enumerate(pad_centers_b):
            d = (px - bcx) ** 2 + (py - bcy) ** 2
            if d < best_dist:
                best_dist = d
                best_idx = i
        if best_idx is not None:
            corner_pad_indices.add(best_idx)

    # Centroid of comp_b pads
    center_x = sum(p[0] for p in pad_centers_b) / len(pad_centers_b)
    center_y = sum(p[1] for p in pad_centers_b) / len(pad_centers_b)

    tol_sq = tolerance * tolerance
    for cp_idx in corner_pad_indices:
        cpx, cpy = pad_centers_b[cp_idx]
        # Direction vector: comp_b centre → corner pad (outward)
        dx = cpx - center_x
        dy = cpy - center_y
        for px, py in pad_centers:
            # Distance from comp_a pad to the corner pad
            apx = px - cpx
            apy = py - cpy
            if apx * apx + apy * apy > tol_sq:
                continue
            # comp_a pad must be on the outward side (dot product >= 0)
            if dx * apx + dy * apy >= 0:
                return True

    return False
