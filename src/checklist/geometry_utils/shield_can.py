"""Shield can geometry helpers.

Provides:
- is_on_corner_or_diagonal                      — corner/diagonal proximity check
- get_orientation_relative_to_shield_can        — cap orientation vs shield-can edge
- find_outline_boundary_pad_overlapping_components
- get_orientation_relative_to_outline_edge
- detect_inner_walls                            — inner-wall pad detection
- find_nearest_inner_wall
- is_near_inner_wall
- detect_fill_cuts                              — fill-cut region detection
"""

from __future__ import annotations

import math
from typing import Sequence

from src.models import ArcSegment, Component, Package, Pin
from src.visualizer.component_overlay import transform_point
from .orientation import get_major_axis_angle
from .overlap import _get_pad_union
from .polygon import (
    _get_pad_centers,
    _outline_to_shapely,
    _resolve_outline,
)

try:
    from shapely.geometry import (
        LineString,
        MultiPoint,
        Point as ShapelyPoint,
        Polygon as ShapelyPolygon,
    )
    from shapely.ops import unary_union
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False


# ---------------------------------------------------------------------------
# Outline helpers
# ---------------------------------------------------------------------------

def _get_shield_can_outline(comp: Component,
                            packages: list[Package],
                            *, is_bottom: bool = False):
    """Build an outline polygon for a shield can component.

    Falls back to the convex hull of pad centre positions.
    Returns a Shapely Polygon or None.
    """
    if not _HAS_SHAPELY:
        return None
    outline = _resolve_outline(comp, packages, is_bottom=is_bottom)
    if outline is not None:
        return outline
    centers = _get_pad_centers(comp, packages, is_bottom=is_bottom)
    if len(centers) >= 3:
        return MultiPoint(centers).convex_hull
    return None


def _find_nearest_segment(
    point: tuple[float, float],
    outline_poly,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Return the nearest edge segment of outline_poly to point."""
    all_rings: list[list[tuple[float, float]]] = []
    if hasattr(outline_poly, "geoms"):
        for g in outline_poly.geoms:
            if hasattr(g, "exterior"):
                all_rings.append(list(g.exterior.coords[:-1]))
    elif hasattr(outline_poly, "exterior"):
        all_rings.append(list(outline_poly.exterior.coords[:-1]))

    if not all_rings:
        return None

    pt = ShapelyPoint(point)
    best_seg = None
    best_dist = float("inf")

    for coords in all_rings:
        n = len(coords)
        if n < 2:
            continue
        for i in range(n):
            p1 = coords[i]
            p2 = coords[(i + 1) % n]
            seg_line = LineString([p1, p2])
            d = seg_line.distance(pt)
            if d < best_dist:
                best_dist = d
                best_seg = (p1, p2)

    return best_seg


def _find_segment_overlapping_geom(
    geom,
    outline_poly,
    *,
    buffer_mm: float = 0.05,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Return the outline edge segment with the greatest overlap with geom."""
    if geom is None or geom.is_empty:
        return None

    all_rings: list[list[tuple[float, float]]] = []
    if hasattr(outline_poly, "geoms"):
        for g in outline_poly.geoms:
            if hasattr(g, "exterior"):
                all_rings.append(list(g.exterior.coords[:-1]))
    elif hasattr(outline_poly, "exterior"):
        all_rings.append(list(outline_poly.exterior.coords[:-1]))

    if not all_rings:
        return None

    best_seg = None
    best_area = 0.0

    for coords in all_rings:
        n = len(coords)
        if n < 2:
            continue
        for i in range(n):
            p1 = coords[i]
            p2 = coords[(i + 1) % n]
            seg_strip = LineString([p1, p2]).buffer(buffer_mm)
            try:
                inter = seg_strip.intersection(geom)
            except Exception:
                continue
            if inter.is_empty:
                continue
            area = getattr(inter, "area", 0.0)
            if area > best_area:
                best_area = area
                best_seg = (p1, p2)

    return best_seg


def _is_diagonal_segment(
    p1: tuple[float, float],
    p2: tuple[float, float],
    tolerance_deg: float = 10.0,
) -> bool:
    """Return True if the segment is neither horizontal nor vertical."""
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    if dx == 0.0 and dy == 0.0:
        return False
    angle = math.degrees(math.atan2(dy, dx)) % 180.0
    if angle < tolerance_deg or angle > (180.0 - tolerance_deg):
        return False
    if abs(angle - 90.0) < tolerance_deg:
        return False
    return True


# ---------------------------------------------------------------------------
# Public orientation and overlap helpers
# ---------------------------------------------------------------------------

def is_on_corner_or_diagonal(
    cap: Component,
    shield_can: Component,
    packages: list[Package],
    corner_tolerance: float = 0.254,
    diagonal_tolerance_deg: float = 10.0,
    *,
    cap_is_bottom: bool = False,
    sc_is_bottom: bool = False,
) -> bool:
    """Check if cap overlaps a curved end-cap (fill-cut) of a shield-can pad.

    Only the semicircular curved sections of each shield-can pad count as
    "edge" positions.  Straight portions of the pad are not considered edges.

    Falls back to the legacy vertex-buffer / diagonal-segment method when
    fill-cut geometry is unavailable (e.g. circular pads without sufficient
    aspect ratio).
    """
    if not _HAS_SHAPELY:
        return False

    # --- Primary: fill-cut (curved end-cap) based check ---
    fill_cuts = detect_fill_cuts(
        shield_can, packages, is_bottom=sc_is_bottom,
    )

    if fill_cuts:
        cap_geom = _get_pad_union(
            cap, packages, is_bottom=cap_is_bottom,
        )
        if cap_geom is None or cap_geom.is_empty:
            pad_centers = _get_pad_centers(cap, packages, is_bottom=cap_is_bottom)
            if not pad_centers:
                return False
            cap_geom = MultiPoint(
                [ShapelyPoint(px, py) for px, py in pad_centers]
            )

        for fc in fill_cuts:
            if fc.intersects(cap_geom):
                return True
        return False

    # --- Fallback: legacy vertex-buffer / diagonal-segment method ---
    outline = _get_shield_can_outline(shield_can, packages, is_bottom=sc_is_bottom)
    if outline is None:
        return False

    pad_centers = _get_pad_centers(cap, packages, is_bottom=cap_is_bottom)
    if not pad_centers:
        return False

    corners = list(outline.exterior.coords[:-1])

    for cx, cy in corners:
        corner_region = ShapelyPoint(cx, cy).buffer(corner_tolerance)
        for px, py in pad_centers:
            if corner_region.contains(ShapelyPoint(px, py)):
                return True

    nearest_seg = _find_nearest_segment((cap.x, cap.y), outline)
    if nearest_seg is not None and _is_diagonal_segment(
        nearest_seg[0], nearest_seg[1], diagonal_tolerance_deg
    ):
        return True

    return False


def get_orientation_relative_to_shield_can(
    cap: Component,
    shield_can: Component,
    packages: list[Package],
    *,
    cap_is_bottom: bool = False,
    sc_is_bottom: bool = False,
) -> str:
    """Determine if cap is Horizontal or Vertical relative to a shield-can edge.

    Returns "Horizontal", "Vertical", or "Unknown".
    """
    if not _HAS_SHAPELY:
        return "Unknown"

    outline = _get_shield_can_outline(shield_can, packages, is_bottom=sc_is_bottom)
    if outline is None:
        return "Unknown"

    nearest_seg = _find_nearest_segment((cap.x, cap.y), outline)
    if nearest_seg is None:
        return "Unknown"

    seg_dx = nearest_seg[1][0] - nearest_seg[0][0]
    seg_dy = nearest_seg[1][1] - nearest_seg[0][1]
    seg_angle = math.degrees(math.atan2(seg_dy, seg_dx)) % 180.0

    cap_angle = get_major_axis_angle(cap, packages, is_bottom=cap_is_bottom)
    if cap_angle is None:
        return "Unknown"

    diff = abs(cap_angle - seg_angle) % 180.0
    if diff > 90.0:
        diff = 180.0 - diff

    if diff < 45.0:
        return "Horizontal"
    return "Vertical"


def find_outline_boundary_pad_overlapping_components(
    comp: Component,
    candidates: Sequence[Component],
    packages: list[Package],
    *,
    is_bottom_primary: bool = False,
    is_bottom_candidates: bool = False,
    buffer_mm: float = 0.05,
    user_symbols: dict | None = None,
) -> list[Component]:
    """Return candidates whose pads intersect the outline boundary ring of comp."""
    if not _HAS_SHAPELY:
        return []

    outline = _resolve_outline(comp, packages, is_bottom=is_bottom_primary)
    if outline is None:
        return []

    boundary_strip = outline.exterior.buffer(buffer_mm)

    overlapping: list[Component] = []
    for cand in candidates:
        pad_union = _get_pad_union(
            cand, packages,
            is_bottom=is_bottom_candidates,
            user_symbols=user_symbols,
        )
        if pad_union is None:
            pad_union = ShapelyPoint(cand.x, cand.y).buffer(0.05)
        if boundary_strip.intersects(pad_union):
            overlapping.append(cand)
    return overlapping


def get_orientation_relative_to_outline_edge(
    comp: Component,
    outline_comp: Component,
    packages: list[Package],
    *,
    comp_is_bottom: bool = False,
    outline_is_bottom: bool = False,
    user_symbols: dict | None = None,
) -> str:
    """Determine if comp is Horizontal or Vertical relative to the outline edge it overlaps.

    Returns "Horizontal", "Vertical", or "Unknown".
    """
    if not _HAS_SHAPELY:
        return "Unknown"

    outline = _resolve_outline(outline_comp, packages, is_bottom=outline_is_bottom)
    if outline is None:
        return "Unknown"

    seg = None
    pad_union = _get_pad_union(
        comp, packages,
        is_bottom=comp_is_bottom,
        user_symbols=user_symbols,
    )
    if pad_union is not None and not pad_union.is_empty:
        seg = _find_segment_overlapping_geom(pad_union, outline)

    if seg is None:
        seg = _find_nearest_segment((comp.x, comp.y), outline)
    if seg is None:
        return "Unknown"

    seg_dx = seg[1][0] - seg[0][0]
    seg_dy = seg[1][1] - seg[0][1]
    seg_angle = math.degrees(math.atan2(seg_dy, seg_dx)) % 180.0

    cap_angle = get_major_axis_angle(comp, packages, is_bottom=comp_is_bottom)
    if cap_angle is None:
        return "Unknown"

    diff = abs(cap_angle - seg_angle) % 180.0
    if diff > 90.0:
        diff = 180.0 - diff

    return "Horizontal" if diff < 45.0 else "Vertical"


# ---------------------------------------------------------------------------
# Inner wall detection
# ---------------------------------------------------------------------------

def detect_inner_walls(
    shield_can: Component,
    packages: list[Package],
    *,
    is_bottom: bool = False,
    boundary_proximity: float = 0.1,
):
    """Detect inner-wall pads of a shield can.

    Returns a list of Shapely Polygon objects for each detected inner-wall pad.
    A pad is an inner wall when its centroid lies strictly inside the convex hull
    of all pad centroids by >= boundary_proximity mm.
    """
    if not _HAS_SHAPELY:
        return []

    if shield_can.pkg_ref < 0 or shield_can.pkg_ref >= len(packages):
        return []
    pkg = packages[shield_can.pkg_ref]
    if not pkg.pins:
        return []

    pad_entries: list[tuple[tuple[float, float], object]] = []
    for pin in pkg.pins:
        if not pin.outlines:
            continue
        pad_geom = _outline_to_shapely(pin.outlines[0], shield_can,
                                       is_bottom=is_bottom)
        if pad_geom is None or pad_geom.is_empty:
            continue
        c = pad_geom.centroid
        pad_entries.append(((c.x, c.y), pad_geom))

    if len(pad_entries) < 4:
        return []

    centroids = [entry[0] for entry in pad_entries]
    hull = MultiPoint(centroids).convex_hull
    if not hasattr(hull, "exterior"):
        return []
    hull_boundary = hull.exterior

    inner_walls = []
    for (cx, cy), pad_geom in pad_entries:
        if ShapelyPoint(cx, cy).distance(hull_boundary) >= boundary_proximity:
            inner_walls.append(pad_geom)

    return inner_walls


def find_nearest_inner_wall(
    point: tuple[float, float],
    inner_walls,
):
    """Return the nearest inner wall to point and its distance.

    Returns (nearest_wall, distance) or None when inner_walls is empty.
    """
    if not inner_walls or not _HAS_SHAPELY:
        return None

    pt = ShapelyPoint(point)
    best_wall = None
    best_dist = float("inf")
    for wall in inner_walls:
        d = wall.distance(pt)
        if d < best_dist:
            best_dist = d
            best_wall = wall
    return (best_wall, best_dist)


def is_near_inner_wall(
    comp: Component,
    shield_can: Component,
    packages: list[Package],
    distance_threshold: float = 0.5,
    *,
    comp_is_bottom: bool = False,
    sc_is_bottom: bool = False,
    inner_walls=None,
    boundary_tolerance: float = 0.2,
) -> bool:
    """Check if comp is within distance_threshold of an inner wall.

    Tests both the component board centre and all pad centres.
    Pass pre-computed inner_walls to avoid recomputation across multiple calls.
    """
    if not _HAS_SHAPELY:
        return False

    if inner_walls is None:
        inner_walls = detect_inner_walls(
            shield_can, packages,
            is_bottom=sc_is_bottom,
        )
    if not inner_walls:
        return False

    result = find_nearest_inner_wall((comp.x, comp.y), inner_walls)
    if result is not None and result[1] <= distance_threshold:
        return True

    pad_centers = _get_pad_centers(comp, packages, is_bottom=comp_is_bottom)
    for px, py in pad_centers:
        result = find_nearest_inner_wall((px, py), inner_walls)
        if result is not None and result[1] <= distance_threshold:
            return True

    return False


# ---------------------------------------------------------------------------
# Fill-cut detection
# ---------------------------------------------------------------------------

def _arc_seg_to_pts(
    start: tuple[float, float],
    seg: ArcSegment,
    resolution: int = 32,
) -> list[tuple[float, float]]:
    """Approximate a single ArcSegment as a polyline (local coords)."""
    xs, ys = start
    xe, ye = seg.end.x, seg.end.y
    xc, yc = seg.center.x, seg.center.y

    radius = math.hypot(xs - xc, ys - yc)
    if radius < 1e-10:
        return [(xs, ys), (xe, ye)]

    start_angle = math.atan2(ys - yc, xs - xc)
    end_angle   = math.atan2(ye - yc, xe - xc)

    if seg.clockwise:
        if end_angle >= start_angle:
            end_angle -= 2 * math.pi
    else:
        if end_angle <= start_angle:
            end_angle += 2 * math.pi

    pts = []
    for i in range(resolution):
        t = start_angle + (end_angle - start_angle) * i / (resolution - 1)
        pts.append((xc + radius * math.cos(t), yc + radius * math.sin(t)))
    pts[-1] = (xe, ye)
    return pts


def _extract_fill_cuts_from_contour(
    contour,
    arc_resolution: int = 32,
) -> list[list[tuple[float, float]]]:
    """Extract fill-cut cap polygon vertices from a CONTOUR outline."""
    segs = contour.segments
    if not segs:
        return []

    arc_flags: list[bool] = [isinstance(seg, ArcSegment) for seg in segs]

    n = len(segs)
    transitions = sum(1 for i in range(n) if arc_flags[i] != arc_flags[(i + 1) % n])
    if transitions != 4:
        return []

    pts: list[tuple[float, float]] = [(contour.start.x, contour.start.y)]
    for seg in segs:
        pts.append((seg.end.x, seg.end.y))

    cap_polys: list[list[tuple[float, float]]] = []
    for i, seg in enumerate(segs):
        if not arc_flags[i]:
            continue
        arc_start = pts[i]
        arc_pts = _arc_seg_to_pts(arc_start, seg, arc_resolution)
        cap_polys.append(arc_pts)

    return cap_polys


def _extract_fill_cuts_from_rc(
    params: dict,
    min_aspect: float = 1.3,
    arc_resolution: int = 32,
) -> list[list[tuple[float, float]]]:
    """Build fill-cut cap polygon vertices for an RC outline."""
    llx = params.get("llx", 0.0)
    lly = params.get("lly", 0.0)
    w = params.get("width", 0.0)
    h = params.get("height", 0.0)
    if w <= 0 or h <= 0:
        return []
    if max(w, h) / min(w, h) < min_aspect:
        return []

    cx = llx + w / 2.0
    cy = lly + h / 2.0
    radius = min(w, h) / 2.0
    offset = max(w, h) / 2.0 - radius

    cap_polys: list[list[tuple[float, float]]] = []

    if h >= w:
        top_angles = [math.pi - i * math.pi / (arc_resolution - 1)
                      for i in range(arc_resolution)]
        top_pts = [(cx + radius * math.cos(a), (cy + offset) + radius * math.sin(a))
                   for a in top_angles]
        cap_polys.append(top_pts)

        bot_angles = [i * math.pi / (arc_resolution - 1) - math.pi
                      for i in range(arc_resolution)]
        bot_pts = [(cx + radius * math.cos(a), (cy - offset) + radius * math.sin(a))
                   for a in bot_angles]
        cap_polys.append(bot_pts)
    else:
        right_angles = [-math.pi / 2 + i * math.pi / (arc_resolution - 1)
                        for i in range(arc_resolution)]
        right_pts = [((cx + offset) + radius * math.cos(a), cy + radius * math.sin(a))
                     for a in right_angles]
        cap_polys.append(right_pts)

        left_angles = [math.pi / 2 + i * math.pi / (arc_resolution - 1)
                       for i in range(arc_resolution)]
        left_pts = [((cx - offset) + radius * math.cos(a), cy + radius * math.sin(a))
                    for a in left_angles]
        cap_polys.append(left_pts)

    return cap_polys


def _get_pin_fill_cuts(
    pin: Pin,
    min_aspect: float = 1.3,
    min_long_side_mm: float = 0.3,
    arc_resolution: int = 32,
) -> list[list[tuple[float, float]]]:
    """Return fill-cut cap polygon vertex lists for a single pin (local coords)."""
    for outline in pin.outlines:
        if outline.type == "CONTOUR" and outline.contour is not None:
            result = _extract_fill_cuts_from_contour(outline.contour, arc_resolution)
            if result:
                chord = math.hypot(
                    result[0][-1][0] - result[0][0][0],
                    result[0][-1][1] - result[0][0][1],
                )
                if chord >= min_long_side_mm:
                    return result
        elif outline.type == "RC":
            p = outline.params
            w = p.get("width", 0.0)
            h = p.get("height", 0.0)
            if max(w, h) < min_long_side_mm:
                continue
            result = _extract_fill_cuts_from_rc(p, min_aspect, arc_resolution)
            if result:
                return result
    return []


def detect_fill_cuts(
    shield_can: Component,
    packages: list[Package],
    *,
    is_bottom: bool = False,
    min_aspect: float = 1.3,
    min_long_side_mm: float = 0.3,
    arc_resolution: int = 32,
):
    """Detect fill-cut regions for all pins of a shield can component.

    Returns list[ShapelyPolygon] in board coordinates.
    Empty when no oblong pads are found or Shapely is unavailable.
    """
    if not _HAS_SHAPELY:
        return []

    if shield_can.pkg_ref < 0 or shield_can.pkg_ref >= len(packages):
        return []

    pkg = packages[shield_can.pkg_ref]
    fill_cuts = []

    for pin in pkg.pins:
        local_cap_polys = _get_pin_fill_cuts(
            pin, min_aspect, min_long_side_mm, arc_resolution
        )
        for local_pts in local_cap_polys:
            board_pts = [
                transform_point(lx, ly, shield_can, is_bottom=is_bottom)
                for lx, ly in local_pts
            ]
            try:
                poly = ShapelyPolygon(board_pts)
                if poly.is_valid and not poly.is_empty:
                    fill_cuts.append(poly)
            except Exception:
                pass

    return fill_cuts
