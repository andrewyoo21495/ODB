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
from .clearance import build_inset_boundary
from .orientation import get_major_axis_angle
from .overlap import _get_individual_pad_polygons, _get_pad_union
from .polygon import (
    _get_pad_centers,
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
    from shapely import concave_hull as _concave_hull
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False


# ---------------------------------------------------------------------------
# Outline helpers
# ---------------------------------------------------------------------------

def _get_shield_can_outline(comp: Component,
                            packages: list[Package],
                            *, is_bottom: bool = False,
                            concave_ratio: float = 0.3):
    """Build an outline polygon for a shield can component.

    Uses the package-level component outline when available.  Otherwise
    falls back to a **concave hull** of pad centre positions so that
    non-convex shield can shapes (L-shapes, U-shapes, etc.) are preserved
    rather than being inflated into a convex hull.

    Parameters
    ----------
    concave_ratio : float
        Ratio parameter for ``shapely.concave_hull`` (0 = tightest fit,
        1 = convex hull).  The default 0.3 follows the pad arrangement
        closely while avoiding overly tight concavities between adjacent
        perimeter pads.

    Returns a Shapely Polygon or None.
    """
    if not _HAS_SHAPELY:
        return None
    outline = _resolve_outline(comp, packages, is_bottom=is_bottom)
    if outline is not None:
        return outline
    centers = _get_pad_centers(comp, packages, is_bottom=is_bottom)
    if len(centers) >= 3:
        hull = _concave_hull(MultiPoint(centers), ratio=concave_ratio)
        if hull is not None and not hull.is_empty and hasattr(hull, "exterior"):
            return hull
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
    """Check if cap is near a corner vertex or diagonal section of shield_can."""
    if not _HAS_SHAPELY:
        return False

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

def get_outermost_outline(
    shield_can: Component,
    packages: list[Package],
    *,
    is_bottom: bool = False,
):
    """Return the outermost component outline of a shield can (filled).

    Uses ``_resolve_outline`` (= ``get_component_outline``) which computes
    ``unary_union`` of all ``pkg.outlines`` — the same geometry shown as the
    dashed **CONTAINER FRAME** in CKL-02-005 visualization.

    The result is filled (holes removed via exterior ring) so that:
    - The visualization draws only the outer boundary.
    - ``detect_inner_walls`` can measure pad distance to the outer boundary
      without interference from interior ring boundaries.

    Returns a Shapely Polygon or None.
    """
    if not _HAS_SHAPELY:
        return None

    outline = _resolve_outline(shield_can, packages, is_bottom=is_bottom)
    if outline is None:
        return None

    # Fill the outline — use exterior ring only (remove holes).
    if hasattr(outline, "geoms"):
        # MultiPolygon / GeometryCollection — pick the largest, fill it.
        polys = [g for g in outline.geoms if hasattr(g, "exterior")]
        if not polys:
            return None
        polys.sort(key=lambda g: g.area, reverse=True)
        return ShapelyPolygon(polys[0].exterior)

    if hasattr(outline, "exterior"):
        return ShapelyPolygon(outline.exterior)

    return None


def get_inner_wall_inset_line(
    shield_can: Component,
    packages: list[Package],
    *,
    is_bottom: bool = False,
    inset_mm: float = 1.4,
):
    """Return the inset line used to detect a shield can's inner walls.

    The inset line is the boundary of the outermost component outline
    eroded inward by *inset_mm* (``outer.buffer(-inset_mm).boundary``),
    mirroring the inset-boundary concept used by CKL-03-015 for PCB
    outline clearance.

    Returns a Shapely LineString / MultiLineString (the inset ring), or
    ``None`` when the outline is missing or the erosion collapses the
    polygon to nothing (shield can smaller than 2*inset_mm).
    """
    if not _HAS_SHAPELY:
        return None

    outer = get_outermost_outline(
        shield_can, packages, is_bottom=is_bottom,
    )
    if outer is None or outer.is_empty or not hasattr(outer, "exterior"):
        return None

    inset_poly = build_inset_boundary(outer, inset_mm)
    if inset_poly is None or inset_poly.is_empty:
        return None

    line = inset_poly.boundary
    if line is None or line.is_empty:
        return None
    return line


def detect_inner_walls(
    shield_can: Component,
    packages: list[Package],
    *,
    is_bottom: bool = False,
    inset_mm: float = 1.4,
    user_symbols: dict | None = None,
):
    """Detect inner-wall pads of a shield can.

    Returns a list of Shapely Polygon objects for each detected inner-wall pad.

    Inner wall = SC pad that runs inward, subdividing the interior, rather
    than hugging the outer component outline.

    Strategy (inset-line crossing — mirrors CKL-03-015's clearance check):
    1. Obtain the outer component outline via ``get_outermost_outline`` —
       the filled ``unary_union`` of all ``pkg.outlines``, consistent with
       the CONTAINER FRAME shown in visualizations.
    2. Erode it inward by *inset_mm* and take the boundary as the **inset
       line** (see :func:`get_inner_wall_inset_line`).
    3. Any pad that **intersects the inset line** reaches deep enough into
       the interior to be an inner wall.

    Unlike a distance-to-outer-boundary test, this correctly catches inner
    walls that connect to the outer wall (their minimum distance to the
    outer boundary is ~0, but they still cross the inset line as they run
    inward).

    Pad geometry is resolved via ``_get_individual_pad_polygons`` — the same
    FID-resolved ``Toeprint.geom`` path used by ``_get_pad_union`` (and by
    CKL-01-001's pad rendering) — so the detected inner-wall pads match the
    pads drawn in the visualization. *user_symbols* must be passed for
    user-defined pad symbols to resolve correctly.

    *inset_mm* is caller-tunable.
    """
    if not _HAS_SHAPELY:
        return []

    # Resolve individual pad polygons the same way _get_pad_union does
    # (toeprint geometry first, pin-outline fallback) so the inner-wall
    # highlight is geometrically consistent with the drawn pads.
    pad_geoms = _get_individual_pad_polygons(
        shield_can, packages, is_bottom=is_bottom, user_symbols=user_symbols,
    )
    pad_geoms = [g for g in pad_geoms if g is not None and not g.is_empty]
    if len(pad_geoms) < 4:
        return []

    # Inset line = outer outline eroded inward by inset_mm. Pads crossing it
    # run deep into the interior → inner walls.
    inset_line = get_inner_wall_inset_line(
        shield_can, packages, is_bottom=is_bottom, inset_mm=inset_mm,
    )
    if inset_line is None or inset_line.is_empty:
        return []

    inner_walls = []
    for pad_geom in pad_geoms:
        if pad_geom.intersects(inset_line):
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
    user_symbols: dict | None = None,
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
            user_symbols=user_symbols,
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
# Inner-wall compartment classification (inside / outside)
# ---------------------------------------------------------------------------

def _extract_polygons(geom) -> list:
    """Return a flat list of non-empty Polygon parts from *geom*."""
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if hasattr(geom, "geoms"):
        return [g for g in geom.geoms
                if g.geom_type == "Polygon" and not g.is_empty]
    return []


def split_interior_by_inner_walls(
    shield_can: Component,
    packages: list[Package],
    inner_walls,
    *,
    is_bottom: bool = False,
    min_room_ratio: float = 0.02,
):
    """Partition a shield can's interior into outside / inside compartments.

    The inner-wall pads, together with the outer wall, enclose a smaller
    pocket inside the shield can.  This splits the filled interior into
    connected "rooms": the largest room is the main area (**outside**) and any
    remaining rooms form the enclosed pocket (**inside**).

    The inner-wall pads usually leave a small gap to the outer wall (and to
    each other), so a plain ``difference`` with the raw walls would not
    disconnect the interior.  The walls are therefore buffered by a
    progressively larger bridge distance until the interior splits into two or
    more meaningful rooms.

    Returns ``(outside_region, inside_region)``:
    - ``outside_region`` — Shapely (Multi)Polygon, or ``None`` when the
      interior cannot be resolved.
    - ``inside_region``  — Shapely (Multi)Polygon for the enclosed pocket(s),
      or ``None`` when the interior could not be split (no inner walls, or the
      walls do not enclose a pocket). Callers should treat the
      ``inside_region is None`` case as "everything is outside".

    *min_room_ratio* ignores sliver rooms smaller than this fraction of the
    total interior area.
    """
    if not _HAS_SHAPELY:
        return (None, None)

    interior = get_outermost_outline(shield_can, packages, is_bottom=is_bottom)
    if interior is None or interior.is_empty:
        return (None, None)

    walls_list = [w for w in (inner_walls or []) if w is not None and not w.is_empty]
    if not walls_list:
        return (interior, None)

    walls = unary_union(walls_list)
    if walls.is_empty:
        return (interior, None)

    min_area = interior.area * min_room_ratio
    rooms: list = []
    for bridge in (0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0):
        cut_walls = walls.buffer(bridge) if bridge > 0 else walls
        try:
            cut = interior.difference(cut_walls)
        except Exception:
            continue
        polys = [p for p in _extract_polygons(cut) if p.area >= min_area]
        if len(polys) >= 2:
            rooms = polys
            break

    if len(rooms) < 2:
        return (interior, None)

    rooms.sort(key=lambda p: p.area, reverse=True)
    outside_region = rooms[0]
    inside_region = unary_union(rooms[1:])
    return (outside_region, inside_region)


def classify_inner_region(
    comp: Component,
    packages: list[Package],
    outside_region,
    inside_region,
    *,
    is_bottom: bool = False,
    user_symbols: dict | None = None,
) -> str:
    """Classify *comp* as ``"inside"`` or ``"outside"`` the inner-wall pocket.

    ``inside``  — the component lies in the enclosed pocket (*inside_region*).
    ``outside`` — the component lies in the main shield area, or the inside
                  region is unavailable / undeterminable.

    The component's pad union is used (component centre as fallback). When the
    geometry overlaps both regions, the region with the larger overlap area
    wins; with no area overlap (point geometry, or a component sitting in a
    bridged gap) the nearer region wins. Defaults to ``"outside"``.
    """
    if not _HAS_SHAPELY or inside_region is None or inside_region.is_empty:
        return "outside"

    geom = _get_pad_union(
        comp, packages, is_bottom=is_bottom, user_symbols=user_symbols,
    )
    if geom is None or geom.is_empty:
        geom = ShapelyPoint(comp.x, comp.y)

    has_outside = outside_region is not None and not outside_region.is_empty

    in_area = 0.0
    out_area = 0.0
    try:
        in_area = inside_region.intersection(geom).area
    except Exception:
        in_area = 0.0
    if has_outside:
        try:
            out_area = outside_region.intersection(geom).area
        except Exception:
            out_area = 0.0

    if in_area > 0.0 or out_area > 0.0:
        return "inside" if in_area > out_area else "outside"

    # No area overlap — decide by proximity.
    in_d = inside_region.distance(geom)
    out_d = outside_region.distance(geom) if has_outside else float("inf")
    return "inside" if in_d < out_d else "outside"


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


# ---------------------------------------------------------------------------
# Curved-edge overlap detection
# ---------------------------------------------------------------------------

def is_on_curved_edge(
    comp: Component,
    shield_can: Component,
    packages: list[Package],
    *,
    comp_is_bottom: bool = False,
    sc_is_bottom: bool = False,
    buffer_mm: float = 0.05,
    fill_cuts: list | None = None,
    user_symbols: dict | None = None,
) -> bool:
    """Check if *comp*'s pads overlap a curved (fill-cut) region of *shield_can*.

    A shield can's oblong edge pads have straight sides and rounded caps.
    This function tests whether the candidate component's pad geometry
    intersects any of those rounded cap (fill-cut) regions, which indicate
    placement at the curved edge of the shield can.

    A component whose pads overlap only the straight portion of a shield
    can pad is NOT considered on the curved edge.

    Parameters
    ----------
    comp : Component
        The component to test (typically on the opposite side of the board).
    shield_can : Component
        The shield can whose curved edges are checked.
    packages : list[Package]
    comp_is_bottom : bool
        Whether *comp* is on the bottom layer.
    sc_is_bottom : bool
        Whether *shield_can* is on the bottom layer.
    buffer_mm : float
        Buffer applied to fill-cut regions for tolerance (default 0.05 mm).
    fill_cuts : list[ShapelyPolygon] | None
        Pre-computed fill-cut regions.  Pass this when calling repeatedly
        for the same shield can to avoid recomputation.
    user_symbols : dict | None
        User-defined symbol lookup for pad geometry resolution.

    Returns
    -------
    bool
        True if *comp*'s pad geometry intersects a fill-cut (curved) region.
    """
    if not _HAS_SHAPELY:
        return False

    # Build fill-cut regions for the shield can (or use pre-computed ones)
    if fill_cuts is None:
        fill_cuts = detect_fill_cuts(
            shield_can, packages, is_bottom=sc_is_bottom,
        )
    if not fill_cuts:
        return False

    # Build the pad geometry of the candidate component
    from .overlap import _get_pad_union
    pad_geom = _get_pad_union(
        comp, packages,
        is_bottom=comp_is_bottom,
        user_symbols=user_symbols,
    )
    if pad_geom is None or pad_geom.is_empty:
        # Fallback to a small buffer around the component centre
        pad_geom = ShapelyPoint(comp.x, comp.y).buffer(0.05)

    # Check if pad geometry intersects any fill-cut region
    for fc in fill_cuts:
        buffered_fc = fc.buffer(buffer_mm) if buffer_mm > 0 else fc
        if pad_geom.intersects(buffered_fc):
            return True

    return False
