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


def _get_pad_bbox(
    comp: Component,
    packages: list[Package],
    *,
    is_bottom: bool = False,
) -> tuple[float, float, float, float] | None:
    """Return (minx, miny, maxx, maxy) covering the outer edges of all pads.

    Unlike *_get_pad_centers* which returns centre points only, this function
    considers each pin's outline shape (RC, SQ, CR, CONTOUR) so that the
    resulting bounding box encompasses the full physical extent of the pads.

    Falls back to centre-based bbox when outline data is unavailable.
    Returns None when the component has no pad information at all.
    """
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return None
    pkg = packages[comp.pkg_ref]

    all_xs: list[float] = []
    all_ys: list[float] = []

    if pkg.pins:
        for pin in pkg.pins:
            if pin.outlines:
                for outline in pin.outlines:
                    verts = _outline_vertices(outline)
                    for lx, ly in verts:
                        bx, by = transform_point(
                            lx, ly, comp, is_bottom=is_bottom)
                        all_xs.append(bx)
                        all_ys.append(by)
            else:
                # No outline → use centre as fallback
                bx, by = transform_point(
                    pin.center.x, pin.center.y, comp, is_bottom=is_bottom)
                all_xs.append(bx)
                all_ys.append(by)

    if not all_xs and comp.toeprints:
        for tp in comp.toeprints:
            all_xs.append(tp.x)
            all_ys.append(tp.y)

    if not all_xs:
        return None

    return (min(all_xs), min(all_ys), max(all_xs), max(all_ys))


# ---------------------------------------------------------------------------
# Edge / corner detection
# ---------------------------------------------------------------------------

def _find_short_edge_pad_indices(
    pad_centers_b: list[tuple[float, float]],
    outline_b,
    tolerance: float = 0.254,
) -> set[int]:
    """Return indices of *comp_b* pads near the short edges of its outline.

    Algorithm:
      1. Extract the outline's exterior ring segments.
      2. Compute the bounding-box width / height to decide which axis
         is the short side.
      3. Among all outline segments, select those whose direction is
         aligned with the **long axis** — these are the two short-side
         segments (the short segments run perpendicular to the long axis,
         which means they span the short dimension).
      4. Pads of *comp_b* within *tolerance* of these short-side
         segments are "short-edge pads".
    """
    if outline_b is None or not pad_centers_b:
        return set()

    from shapely.geometry import LineString as _LS

    # Extract outline coords
    coords: list[tuple[float, float]] = []
    if hasattr(outline_b, "geoms"):
        for g in outline_b.geoms:
            if hasattr(g, "exterior"):
                coords = list(g.exterior.coords[:-1])
                break
    elif hasattr(outline_b, "exterior"):
        coords = list(outline_b.exterior.coords[:-1])

    if len(coords) < 4:
        return set()

    # Bounding box to determine short axis
    minx, miny, maxx, maxy = outline_b.bounds
    width = maxx - minx
    height = maxy - miny

    if width < 1e-6 and height < 1e-6:
        return set()

    # Build edges with their directions
    edges: list[tuple[tuple[float, float], tuple[float, float], float]] = []
    n = len(coords)
    for i in range(n):
        p1 = coords[i]
        p2 = coords[(i + 1) % n]
        length = math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)
        edges.append((p1, p2, length))

    if not edges:
        return set()

    # Sort by length; short-side segments are the shorter ones
    edges_sorted = sorted(edges, key=lambda e: e[2])
    shortest_len = edges_sorted[0][2]

    # Collect segments whose length is close to the shortest (within 30%
    # tolerance to handle non-perfect rectangles)
    len_threshold = shortest_len * 1.3
    short_segments = [(p1, p2) for p1, p2, length in edges_sorted
                      if length <= len_threshold]

    if not short_segments:
        return set()

    # Find comp_b pads near these short segments
    edge_pad_indices: set[int] = set()
    for p1, p2 in short_segments:
        seg = _LS([p1, p2])
        for i, (px, py) in enumerate(pad_centers_b):
            if seg.distance(ShapelyPoint(px, py)) <= tolerance:
                edge_pad_indices.add(i)

    return edge_pad_indices


def _is_near_bbox_edge(
    pad_centers_a: list[tuple[float, float]],
    pad_centers_b: list[tuple[float, float]],
    tolerance: float = 0.5,
    *,
    bbox_b: tuple[float, float, float, float] | None = None,
) -> bool:
    """Return True if any pad of comp_a is near an edge zone of comp_b's pad bbox.

    "Edge zone" is defined by two rules applied to the axis-aligned bounding
    box of *comp_b*'s pads:

    1. **Corner rule** — any of the 4 bbox corners.
    2. **Short-side rule** — the two shorter sides of the bbox (or all
       four sides when the bbox is roughly square).

    A pad of *comp_a* is on the edge when its centre is within *tolerance*
    distance of a corner point or a short-side line segment.

    Args:
        bbox_b: Pre-computed (minx, miny, maxx, maxy) for *comp_b*'s pads.
                When supplied, *pad_centers_b* is ignored for bbox
                calculation (but must still be non-empty for the guard
                check).  Use ``_get_pad_bbox()`` to compute a bbox that
                covers the full outer edges of each pad, not just centres.
    """
    if not pad_centers_a or not pad_centers_b:
        return False

    if bbox_b is not None:
        minx, miny, maxx, maxy = bbox_b
    else:
        xs_b = [p[0] for p in pad_centers_b]
        ys_b = [p[1] for p in pad_centers_b]
        minx, maxx = min(xs_b), max(xs_b)
        miny, maxy = min(ys_b), max(ys_b)
    width = maxx - minx
    height = maxy - miny

    if width < 1e-6 and height < 1e-6:
        return False

    # 4 corners of the bbox
    corners = [(minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)]

    # Short sides as line segments
    near_square = (max(width, height) < 1e-6
                   or min(width, height) / max(width, height) > 0.85)
    if near_square:
        short_sides = [
            ((minx, miny), (maxx, miny)),
            ((minx, maxy), (maxx, maxy)),
            ((minx, miny), (minx, maxy)),
            ((maxx, miny), (maxx, maxy)),
        ]
    elif width < height:
        # Vertical connector → short sides are top and bottom
        short_sides = [
            ((minx, maxy), (maxx, maxy)),
            ((minx, miny), (maxx, miny)),
        ]
    else:
        # Horizontal connector → short sides are left and right
        short_sides = [
            ((minx, miny), (minx, maxy)),
            ((maxx, miny), (maxx, maxy)),
        ]

    tol_sq = tolerance * tolerance

    for px, py in pad_centers_a:
        # Rule 1: near any corner
        for cx, cy in corners:
            dx = px - cx
            dy = py - cy
            if dx * dx + dy * dy <= tol_sq:
                return True

        # Rule 2: near a short-side segment
        for (x1, y1), (x2, y2) in short_sides:
            seg_dx = x2 - x1
            seg_dy = y2 - y1
            seg_len_sq = seg_dx * seg_dx + seg_dy * seg_dy
            if seg_len_sq < 1e-18:
                continue
            t = ((px - x1) * seg_dx + (py - y1) * seg_dy) / seg_len_sq
            t = max(0.0, min(1.0, t))
            nx = x1 + t * seg_dx
            ny = y1 + t * seg_dy
            d_sq = (px - nx) ** 2 + (py - ny) ** 2
            if d_sq <= tol_sq:
                return True

    return False


def _extract_outline_coords(outline) -> list[tuple[float, float]]:
    """Extract exterior ring coordinates from a Shapely outline geometry.

    Returns the vertex list *without* the closing duplicate.
    """
    coords: list[tuple[float, float]] = []
    if outline is None:
        return coords
    if hasattr(outline, "geoms"):
        for g in outline.geoms:
            if hasattr(g, "exterior"):
                coords = list(g.exterior.coords[:-1])
                break
    elif hasattr(outline, "exterior"):
        coords = list(outline.exterior.coords[:-1])
    return coords


def _find_corner_vertices(
    coords: list[tuple[float, float]],
    angle_threshold: float = 20.0,
) -> list[tuple[float, float]]:
    """Return vertices of a polygon where the outline has a corner.

    A "corner" is a vertex where the interior angle deviates from 180°
    by more than *angle_threshold* degrees.  Collinear or near-collinear
    vertices (e.g. intermediate points along a straight segment or very
    gentle curves) are excluded.

    Args:
        coords: Polygon vertices (no closing duplicate).
        angle_threshold: Minimum deviation from 180° in degrees to
            qualify as a real corner.
    """
    n = len(coords)
    if n < 3:
        return list(coords)

    corners: list[tuple[float, float]] = []
    for i in range(n):
        p_prev = coords[(i - 1) % n]
        p_curr = coords[i]
        p_next = coords[(i + 1) % n]

        dx1 = p_curr[0] - p_prev[0]
        dy1 = p_curr[1] - p_prev[1]
        dx2 = p_next[0] - p_curr[0]
        dy2 = p_next[1] - p_curr[1]

        len1 = math.hypot(dx1, dy1)
        len2 = math.hypot(dx2, dy2)
        if len1 < 1e-9 or len2 < 1e-9:
            continue

        # Cosine of the angle between incoming and outgoing vectors
        cos_a = (dx1 * dx2 + dy1 * dy2) / (len1 * len2)
        cos_a = max(-1.0, min(1.0, cos_a))
        angle_deg = math.degrees(math.acos(cos_a))

        # angle_deg is the deflection angle (0° = straight, 180° = U-turn).
        # A real corner has a significant deflection.
        if angle_deg >= angle_threshold:
            corners.append(p_curr)

    return corners


def is_on_edge(comp_a: Component, comp_b: Component,
               packages: list[Package],
               tolerance: float = 0.4) -> bool:
    """Return True if any pad of comp_a is near a corner vertex of comp_b.

    "Corner vertex" = a point on *comp_b*'s component outline where the
    outline changes direction (angle deviation >= 20° from straight).

    Args:
        tolerance: Radius in mm around each corner vertex.
    """
    if not _HAS_SHAPELY:
        return False

    pad_centers_a = _get_pad_centers(comp_a, packages)
    if not pad_centers_a:
        return False

    outline_b = _resolve_outline(comp_b, packages)
    if outline_b is None:
        return False

    coords = _extract_outline_coords(outline_b)
    corners = _find_corner_vertices(coords)
    if not corners:
        return False

    tol_sq = tolerance * tolerance
    for px, py in pad_centers_a:
        for cx, cy in corners:
            dx = px - cx
            dy = py - cy
            if dx * dx + dy * dy <= tol_sq:
                return True

    return False


# ---------------------------------------------------------------------------
# Nearest outline edge detection for capacitor–connector checks
# ---------------------------------------------------------------------------

def get_nearest_outline_edge_angle(
    comp_a: Component,
    comp_b: Component,
    packages: list[Package],
    *,
    is_bottom_a: bool = False,
    is_bottom_b: bool = False,
) -> Optional[float]:
    """Return the angle of the *comp_b* outline edge nearest to *comp_a*.

    Finds the outline segment of *comp_b* that is closest to the centroid
    of *comp_a*'s pads.  Returns the direction angle of that segment in
    degrees [0, 180), or None if geometry is unavailable.

    This is used to determine whether a capacitor is placed "horizontally"
    or "vertically" **relative to the connector outline edge it overlaps**.
    """
    if not _HAS_SHAPELY:
        return None

    pad_centers_a = _get_pad_centers(comp_a, packages, is_bottom=is_bottom_a)
    outline_b = _resolve_outline(comp_b, packages, is_bottom=is_bottom_b)

    if not pad_centers_a or outline_b is None:
        return None

    # Centroid of comp_a pads
    ax = sum(p[0] for p in pad_centers_a) / len(pad_centers_a)
    ay = sum(p[1] for p in pad_centers_a) / len(pad_centers_a)
    a_pt = ShapelyPoint(ax, ay)

    # Extract outline segments
    coords: list[tuple[float, float]] = []
    if hasattr(outline_b, "geoms"):
        for g in outline_b.geoms:
            if hasattr(g, "exterior"):
                coords = list(g.exterior.coords[:-1])
                break
    elif hasattr(outline_b, "exterior"):
        coords = list(outline_b.exterior.coords[:-1])

    if len(coords) < 3:
        return None

    from shapely.geometry import LineString as _LS

    # Find the nearest segment
    best_dist = float("inf")
    best_angle: Optional[float] = None
    n = len(coords)
    for i in range(n):
        p1 = coords[i]
        p2 = coords[(i + 1) % n]
        seg = _LS([p1, p2])
        d = seg.distance(a_pt)
        if d < best_dist:
            best_dist = d
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            if math.hypot(dx, dy) > 1e-9:
                best_angle = math.degrees(math.atan2(dy, dx)) % 180.0

    return best_angle


def is_on_outline_edge(
    comp_a: Component,
    comp_b: Component,
    packages: list[Package],
    *,
    is_bottom_a: bool = False,
    is_bottom_b: bool = False,
    tolerance: float = 0.4,
) -> bool:
    """Return True if *comp_a*'s pads are near a corner vertex of *comp_b*.

    "Corner vertex" = a point on *comp_b*'s component outline where the
    outline changes direction (angle deviation >= 20° from straight).

    Args:
        tolerance: Radius in mm around each corner vertex.
    """
    if not _HAS_SHAPELY:
        return False

    outline_b = _resolve_outline(comp_b, packages, is_bottom=is_bottom_b)
    if outline_b is None:
        return False

    coords = _extract_outline_coords(outline_b)
    corners = _find_corner_vertices(coords)
    if not corners:
        return False

    pad_centers_a = _get_pad_centers(
        comp_a, packages, is_bottom=is_bottom_a)
    if not pad_centers_a:
        return False

    tol_sq = tolerance * tolerance
    for px, py in pad_centers_a:
        for cx, cy in corners:
            dx = px - cx
            dy = py - cy
            if dx * dx + dy * dy <= tol_sq:
                return True

    return False


def does_pad_overlap_outline(
    comp_a: Component,
    comp_b: Component,
    packages: list[Package],
    *,
    is_bottom_a: bool = False,
    is_bottom_b: bool = False,
    user_symbols: dict | None = None,
) -> bool:
    """Return True if *comp_a*'s body crosses *comp_b*'s outline boundary.

    Primary check uses comp_a's component outline (body).  If unavailable,
    falls back to the convex hull of comp_a's pads.  This ensures that the
    gap between two pads (e.g. a vertical cap on a horizontal edge) does not
    cause a false negative.
    """
    if not _HAS_SHAPELY:
        return False

    from .overlap import _get_pad_union

    # comp_a body outline (preferred — spans the full component)
    body_a = _resolve_outline(comp_a, packages, is_bottom=is_bottom_a)
    if body_a is None:
        # Fallback: convex hull of pad geometry (fills inter-pad gap)
        pad_a = _get_pad_union(comp_a, packages, is_bottom=is_bottom_a,
                               user_symbols=user_symbols)
        if pad_a is not None:
            body_a = pad_a.convex_hull

    outline_b = _resolve_outline(comp_b, packages, is_bottom=is_bottom_b)

    if body_a is None or outline_b is None:
        return False

    return body_a.intersects(outline_b.boundary)
