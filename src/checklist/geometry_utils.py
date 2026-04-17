"""Shared geometry utilities for checklist rules.

Provides functions for:
- Component orientation detection (Horizontal / Vertical)
- Component footprint polygon construction from pin outlines
- Opposite-side overlap detection between components
- Edge detection between components
- Distance measurement (center-to-center and edge-to-edge)
- Component size parsing and filtering
- PCB outline clearance checking
- CSV component list loading and filtering

All coordinate data is expected to be pre-normalised to MM.
"""

from __future__ import annotations

import csv
import math
import re
from typing import Optional, Sequence

import numpy as np

from src.models import (
    ArcRecord, ArcSegment, BBox, Component, EdaData, LineRecord, LineSegment,
    Package, PadRecord, Pin, PinGeometry, PinOutline, SurfaceRecord, Toeprint,
    UserSymbol,
)
from src.visualizer.component_overlay import (
    transform_point,
    transform_pts,
)
from src.visualizer.symbol_renderer import (
    arc_to_points,
    contour_to_vertices,
    get_line_width_for_symbol,
)
from src.parsers.symbol_resolver import resolve_symbol

try:
    from shapely.geometry import (
        MultiPoint, MultiPolygon as ShapelyMultiPolygon,
        Point as ShapelyPoint, Polygon as ShapelyPolygon,
        LineString,
    )
    from shapely.ops import unary_union
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False


# ---------------------------------------------------------------------------
# 1. Component Orientation
# ---------------------------------------------------------------------------

def _classify_wh(w: float, h: float) -> str:
    """Classify orientation from width/height in board coordinates.

    Returns "Horizontal", "Vertical", "Square", or "Unknown".
    """
    if w <= 0 and h <= 0:
        return "Unknown"

    # Treat near-square as "Square" (within 5% tolerance)
    if w > 0 and h > 0:
        ratio = max(w, h) / min(w, h)
        if ratio < 1.05:
            return "Square"

    if w >= h:
        return "Horizontal"
    return "Vertical"


def get_component_orientation(comp: Component,
                              packages: list[Package]) -> str:
    """Determine a component's board-level orientation from its component outline.

    The orientation is derived from the bounding box of the component's
    **package-level outline** polygon in board coordinates (which already
    accounts for rotation).  Falls back to the package bbox with rotation
    if no outline geometry is available.

    Returns:
        "Horizontal" – major axis is roughly along the board X-axis
        "Vertical"   – major axis is roughly along the board Y-axis
        "Square"     – aspect ratio is near 1:1
        "Unknown"    – no geometry data available
    """
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return "Unknown"

    pkg = packages[comp.pkg_ref]

    # Primary: use the component outline polygon in board coordinates
    outline_poly = get_component_outline(comp, pkg)
    if outline_poly is not None:
        minx, miny, maxx, maxy = outline_poly.bounds
        return _classify_wh(maxx - minx, maxy - miny)

    # Fallback: package bbox with rotation
    if pkg.bbox is None:
        return "Unknown"

    w = pkg.bbox.xmax - pkg.bbox.xmin
    h = pkg.bbox.ymax - pkg.bbox.ymin

    if w <= 0 and h <= 0:
        return "Unknown"

    # Treat near-square as "Square" (within 5% tolerance)
    if w > 0 and h > 0:
        ratio = max(w, h) / min(w, h)
        if ratio < 1.05:
            return "Square"

    # Local major axis angle: 0° if wider than tall, 90° if taller than wide
    local_angle = 0.0 if w >= h else 90.0

    # Board-level angle after rotation
    board_angle = (local_angle + comp.rotation) % 180.0

    # Classify: near 0° or 180° → Horizontal, near 90° → Vertical
    # Use a 45° threshold centred on each axis
    if board_angle < 45.0 or board_angle > 135.0:
        return "Horizontal"
    return "Vertical"


def get_major_axis_angle(comp: Component,
                         packages: list[Package],
                         *, is_bottom: bool = False) -> Optional[float]:
    """Return the major-axis direction of *comp* as an angle in degrees [0, 180).

    The major axis is the longer side of the component outline (or fallback
    bounding box) in board coordinates.  Returns ``None`` when orientation
    cannot be determined (missing geometry or near-square outline).
    """
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return None

    pkg = packages[comp.pkg_ref]

    # Primary: use the component outline polygon in board coordinates
    outline_poly = get_component_outline(comp, pkg, is_bottom=is_bottom)
    if outline_poly is not None:
        # Use minimum rotated rectangle to find the true major axis
        mrr = outline_poly.minimum_rotated_rectangle
        coords = list(mrr.exterior.coords)  # 5 points (closed ring)
        # Two edge vectors from the first vertex
        edge_a = (coords[1][0] - coords[0][0], coords[1][1] - coords[0][1])
        edge_b = (coords[2][0] - coords[1][0], coords[2][1] - coords[1][1])
        len_a = math.hypot(*edge_a)
        len_b = math.hypot(*edge_b)

        # Near-square check (within 5 % tolerance)
        if len_a > 0 and len_b > 0:
            ratio = max(len_a, len_b) / min(len_a, len_b)
            if ratio < 1.05:
                return None  # Square — no dominant axis

        major = edge_a if len_a >= len_b else edge_b
        angle = math.degrees(math.atan2(major[1], major[0])) % 180.0
        return angle

    # Fallback: package bbox with rotation
    if pkg.bbox is None:
        return None

    w = pkg.bbox.xmax - pkg.bbox.xmin
    h = pkg.bbox.ymax - pkg.bbox.ymin

    if w <= 0 and h <= 0:
        return None

    if w > 0 and h > 0:
        ratio = max(w, h) / min(w, h)
        if ratio < 1.05:
            return None  # Square

    local_angle = 0.0 if w >= h else 90.0
    effective_mirror = (not comp.mirror) if is_bottom else comp.mirror
    rot = -comp.rotation if effective_mirror else comp.rotation
    board_angle = (local_angle + rot) % 180.0
    return board_angle


def get_pair_orientation(comp_a: Component, comp_b: Component,
                         packages: list[Package]) -> str:
    """Determine alignment by comparing major axes of two component outlines.

    Finds the major-axis direction of each component and checks whether they
    are parallel (→ ``"Horizontal"``) or perpendicular (→ ``"Vertical"``).

    Returns ``"Unknown"`` when either component's axis cannot be determined.
    """
    angle_a = get_major_axis_angle(comp_a, packages)
    angle_b = get_major_axis_angle(comp_b, packages)

    if angle_a is None or angle_b is None:
        return "Unknown"

    # Angle difference, normalised to [0, 90]
    diff = abs(angle_a - angle_b) % 180.0
    if diff > 90.0:
        diff = 180.0 - diff

    # 45° threshold: < 45° → parallel (Horizontal), >= 45° → perpendicular (Vertical)
    if diff < 45.0:
        return "Horizontal"
    return "Vertical"


def are_components_aligned(comp_a: Component, comp_b: Component,
                           packages: list[Package]) -> bool:
    """Return True if both components have the same orientation (both H or both V)."""
    orient_a = get_component_orientation(comp_a, packages)
    orient_b = get_component_orientation(comp_b, packages)
    if orient_a in ("Unknown", "Square") or orient_b in ("Unknown", "Square"):
        return True  # Cannot determine misalignment
    return orient_a == orient_b


# ---------------------------------------------------------------------------
# 2. Component Footprint Polygon
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
        # Approximate circle as polygon
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


def get_component_footprint(comp: Component, pkg: Package,
                            *, is_bottom: bool = False):
    """Build a board-coordinate shapely Polygon from pin outline vertices.

    Returns a shapely Polygon (convex hull of all pin outline points),
    or None if no geometry is available or shapely is not installed.
    """
    if not _HAS_SHAPELY:
        return None

    all_points: list[tuple[float, float]] = []

    # Collect from pin outlines
    for pin in pkg.pins:
        for outline in pin.outlines:
            local_verts = _outline_vertices(outline)
            for lv in local_verts:
                bx, by = transform_point(lv[0], lv[1], comp, is_bottom=is_bottom)
                all_points.append((bx, by))

    # Collect from package-level outlines
    for outline in pkg.outlines:
        local_verts = _outline_vertices(outline)
        for lv in local_verts:
            bx, by = transform_point(lv[0], lv[1], comp, is_bottom=is_bottom)
            all_points.append((bx, by))

    if len(all_points) >= 3:
        return MultiPoint(all_points).convex_hull

    # Fallback: use toeprint positions with a small buffer
    if comp.toeprints:
        tp_pts = [(t.x, t.y) for t in comp.toeprints]
        if len(tp_pts) >= 3:
            return MultiPoint(tp_pts).convex_hull.buffer(0.005)
        if len(tp_pts) >= 1:
            return ShapelyPoint(tp_pts[0]).buffer(0.005)

    return None


def _outline_to_shapely(outline: PinOutline, comp: Component,
                        *, is_bottom: bool = False):
    """Convert a single *PinOutline* to a board-coordinate Shapely geometry.

    Mirrors the visualiser's ``_outline_to_patch`` but produces Shapely
    objects instead of matplotlib patches, preserving the **exact original
    shape** (circles, rectangles, squares, contours) rather than reducing
    everything to a convex hull.

    Returns a Shapely geometry or *None* for unknown / degenerate shapes.
    """
    if not _HAS_SHAPELY:
        return None

    p = outline.params

    # -- Circle (CR) or rounded/chamfered circle (CT) -------------------------
    if outline.type in ("CR", "CT"):
        xc = p.get("xc", 0.0)
        yc = p.get("yc", 0.0)
        r = p.get("radius", 0.0)
        if r <= 0:
            return None
        bx, by = transform_point(xc, yc, comp, is_bottom=is_bottom)
        return ShapelyPoint(bx, by).buffer(r, resolution=32)

    # -- Rectangle (RC) – lower-left corner + width + height ------------------
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

    # -- Square (SQ) – centre + half-side -------------------------------------
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

    # -- Complex contour (CONTOUR / OB) ---------------------------------------
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
    """Build a board-coordinate polygon from **package-level** outlines only.

    Unlike :func:`get_component_footprint` (which includes pin/pad outlines),
    this returns only the physical component body outline.

    Each outline entry in the package is converted to its **exact** Shapely
    geometry (rectangle, circle, contour, etc.) and the results are combined
    with ``unary_union``.  This preserves concave, L-shaped, and circular
    outlines faithfully — matching the yellow boundary drawn by the
    visualiser's ``show_pkg_outlines`` mode.
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
# 3. Edge Detection
# ---------------------------------------------------------------------------

def _get_pad_centers(comp: Component, packages: list[Package],
                     *, is_bottom: bool = False,
                     ) -> list[tuple[float, float]]:
    """Return board-coordinate centre points for each pad of *comp*.

    Uses pin centre positions transformed to board coordinates.
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

    # Fallback: toeprint positions
    if comp.toeprints:
        return [(tp.x, tp.y) for tp in comp.toeprints]

    return []


def is_on_edge(comp_a: Component, comp_b: Component,
               packages: list[Package],
               tolerance: float = 0.254) -> bool:
    """Return True if any pad of *comp_a* is in a corner area of *comp_b*'s outline.

    "On the edge" means at least one of *comp_a*'s pad centres falls
    within *tolerance* of a corner vertex of *comp_b*'s component outline.

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

    # Extract corner vertices of comp_b's outline (exclude closing duplicate).
    # The outline may be a MultiPolygon when the package has multiple outline
    # entries, so collect exterior coords from all constituent polygons.
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


# ---------------------------------------------------------------------------
# 4. Distance Measurement
# ---------------------------------------------------------------------------

def center_distance(comp_a: Component, comp_b: Component) -> float:
    """Euclidean distance between component centres (mm)."""
    dx = comp_a.x - comp_b.x
    dy = comp_a.y - comp_b.y
    return math.sqrt(dx * dx + dy * dy)


def edge_distance(comp_a: Component, comp_b: Component,
                  packages: list[Package]) -> float:
    """Minimum distance between footprint polygon boundaries (mm).

    Returns float('inf') if footprint polygons cannot be built.
    Falls back to center_distance if shapely is unavailable.
    """
    if not _HAS_SHAPELY:
        return center_distance(comp_a, comp_b)

    fp_a = _resolve_footprint(comp_a, packages)
    fp_b = _resolve_footprint(comp_b, packages)

    if fp_a is None or fp_b is None:
        return float("inf")

    return fp_a.distance(fp_b)


# ---------------------------------------------------------------------------
# 5. CSV Component List Loading
# ---------------------------------------------------------------------------

def load_component_list(csv_path: str) -> list[dict]:
    """Load a managed component list CSV file.

    Expected columns: comp, part_name, size (matching references/*.csv format).
    Returns a list of dicts with those keys.
    """
    entries: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entries.append({
                "comp": row.get("comp", "").strip(),
                "part_name": row.get("part_name", "").strip(),
                "size": row.get("size", "").strip(),
            })
    return entries


def filter_components_by_list(components: list[Component],
                              csv_entries: list[dict]) -> list[Component]:
    """Return components whose comp_name matches an entry in the CSV list."""
    names = {e["comp"] for e in csv_entries if e.get("comp")}
    return [c for c in components if c.comp_name in names]


# ---------------------------------------------------------------------------
# 6. Opposite-Side Overlap Detection
# ---------------------------------------------------------------------------

def find_overlapping_components(
    comp: Component,
    candidates: Sequence[Component],
    packages: list[Package],
    *,
    is_bottom_primary: bool = False,
    is_bottom_candidates: bool = False,
) -> list[Component]:
    """Return *candidates* whose footprints overlap *comp*'s footprint.

    Both *comp* and every candidate are assumed to be on opposite sides of
    the PCB so their 2-D projections are compared directly.
    """
    if not _HAS_SHAPELY:
        return []

    fp_comp = _resolve_footprint(comp, packages, is_bottom=is_bottom_primary)
    if fp_comp is None:
        # Fallback: use a small box around the centre
        fp_comp = ShapelyPoint(comp.x, comp.y).buffer(0.1)

    overlapping: list[Component] = []
    for cand in candidates:
        fp_cand = _resolve_footprint(cand, packages, is_bottom=is_bottom_candidates)
        if fp_cand is None:
            fp_cand = ShapelyPoint(cand.x, cand.y).buffer(0.1)
        if fp_comp.intersects(fp_cand):
            overlapping.append(cand)
    return overlapping


def overlaps_component_outline(
    comp: Component,
    target: Component,
    packages: list[Package],
    *,
    is_bottom_comp: bool = False,
    is_bottom_target: bool = False,
) -> bool:
    """Return True if *comp*'s footprint overlaps *target*'s component outline.

    Unlike :func:`find_overlapping_components` (which checks footprint vs
    footprint), this checks *comp*'s full footprint against only the
    package-level outline of *target* (the physical component body, excluding
    pad geometry).  Returns False if the outline cannot be resolved.
    """
    if not _HAS_SHAPELY:
        return False

    fp_comp = _resolve_footprint(comp, packages, is_bottom=is_bottom_comp)
    outline_target = _resolve_outline(target, packages, is_bottom=is_bottom_target)

    if fp_comp is None or outline_target is None:
        return False

    return fp_comp.intersects(outline_target)


# ---------------------------------------------------------------------------
# 6b. Sandwich Zone Detection
# ---------------------------------------------------------------------------

def is_sandwiched_between(
    cap: Component,
    am_a: Component,
    am_b: Component,
    packages: list[Package],
    *,
    is_bottom_cap: bool = False,
    is_bottom_am: bool = False,
) -> bool:
    """Return True if *cap* is sandwiched between *am_a* and *am_b*.

    A capacitor is sandwiched if any part of its footprint falls within the
    corridor between the two AP/Memory components' footprints.  This includes
    cases where the cap partially overlaps one of the components while
    extending into the gap between them (not just when the cap centre is
    strictly between the two component centres).

    With Shapely: the corridor is ``convex_hull(am_a ∪ am_b) − (am_a ∪ am_b)``,
    and we check whether *cap*'s footprint intersects this region.

    Fallback (no Shapely / missing footprints): dot-product centre projection.
    """
    if _HAS_SHAPELY:
        fp_a = _resolve_footprint(am_a, packages, is_bottom=is_bottom_am)
        fp_b = _resolve_footprint(am_b, packages, is_bottom=is_bottom_am)
        fp_cap = _resolve_footprint(cap, packages, is_bottom=is_bottom_cap)

        if fp_a is not None and fp_b is not None and fp_cap is not None:
            combined = unary_union([fp_a, fp_b])
            corridor = combined.convex_hull.difference(combined)
            if not corridor.is_empty:
                return bool(fp_cap.intersects(corridor))

    # Fallback: centre-based dot-product projection
    ax, ay = am_a.x, am_a.y
    bx, by = am_b.x, am_b.y
    cx, cy = cap.x, cap.y

    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-9:
        return False

    t = ((cx - ax) * dx + (cy - ay) * dy) / length_sq
    return 0.0 < t < 1.0


# ---------------------------------------------------------------------------
# 6c. Outermost Pin Detection
# ---------------------------------------------------------------------------

def find_outermost_pin_indices(pins: list[Pin]) -> set[int]:
    """Return indices of pins on the outer perimeter of the pad array.

    A pin is considered outermost when its centre lies at the global
    extreme boundary of the pad arrangement in at least one of the four
    cardinal directions (minimum/maximum X **or** minimum/maximum Y across
    ALL pins in the package).

    This correctly handles non-convex pad layouts such as cross or
    T-shaped arrangements, where dense inner pad clusters might
    coincidentally fall on the convex hull boundary despite not being
    truly peripheral.  For simple rectangular arrays every pad in the
    first/last row and first/last column is correctly identified.

    For packages with <= 4 pins all pins are returned unconditionally.
    """
    if not pins:
        return set()
    if len(pins) <= 4:
        return set(range(len(pins)))

    centres = [(p.center.x, p.center.y) for p in pins]
    xs = [c[0] for c in centres]
    ys = [c[1] for c in centres]

    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)

    # Degenerate: all pads coincide
    if x_min == x_max and y_min == y_max:
        return set(range(len(pins)))

    # Tolerance well below any realistic pad pitch (typically >= 0.4 mm)
    tol = 0.01  # mm

    outermost: set[int] = set()
    for idx, (cx, cy) in enumerate(centres):
        if (cx <= x_min + tol or cx >= x_max - tol or
                cy <= y_min + tol or cy >= y_max - tol):
            outermost.add(idx)

    return outermost


def _get_outermost_pad_union(comp: Component, packages: list[Package],
                             *, is_bottom: bool = False,
                             user_symbols: dict | None = None):
    """Build a union of only the **outermost** pad polygons for *comp*.

    Same as :func:`_get_pad_union` but restricted to pads at the perimeter.

    Primary path: uses FID-resolved ``Toeprint.geom`` data.  Outermost
    toeprints are identified by board-space position (same criterion as
    :func:`find_outermost_pin_indices`).

    Fallback: when no toeprint has ``geom``, uses the package-level pin
    outline definitions restricted to the outermost pin indices.
    """
    if not _HAS_SHAPELY:
        return None
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return None

    user_symbols = user_symbols or {}

    # --- Primary path: select outermost toeprints by board position -----------
    tps_with_geom = [tp for tp in comp.toeprints if tp.geom is not None]
    if tps_with_geom:
        if len(tps_with_geom) <= 4:
            outer_tps = tps_with_geom
        else:
            xs = [tp.x for tp in tps_with_geom]
            ys = [tp.y for tp in tps_with_geom]
            x_min, x_max = min(xs), max(xs)
            y_min, y_max = min(ys), max(ys)
            tol = 0.01
            outer_tps = [
                tp for tp in tps_with_geom
                if (tp.x <= x_min + tol or tp.x >= x_max - tol or
                    tp.y <= y_min + tol or tp.y >= y_max - tol)
            ]

        pad_polys = []
        for tp in outer_tps:
            geom = tp.geom
            pad_rot = -geom.rotation if is_bottom else geom.rotation
            if geom.is_user_symbol and geom.symbol_name in user_symbols:
                g = _user_symbol_to_shapely(
                    user_symbols[geom.symbol_name],
                    geom.x, geom.y, pad_rot, geom.mirror,
                )
            else:
                g = _symbol_to_shapely(
                    geom.symbol_name, geom.x, geom.y, pad_rot, geom.mirror,
                    geom.units, geom.unit_override, geom.resize_factor,
                )
            if g is not None and not g.is_empty:
                pad_polys.append(g)

        if pad_polys:
            return unary_union(pad_polys)

    # --- Fallback: package-level outermost pin outlines -----------------------
    pkg = packages[comp.pkg_ref]
    if not pkg.pins:
        return None

    outermost_indices = find_outermost_pin_indices(pkg.pins)
    pad_polys = []

    for pin_idx in outermost_indices:
        pin = pkg.pins[pin_idx]
        placed = False
        for outline in pin.outlines:
            verts = _outline_vertices(outline)
            if not verts:
                continue
            board_verts = [transform_point(v[0], v[1], comp, is_bottom=is_bottom) for v in verts]
            if len(board_verts) >= 3:
                try:
                    poly = ShapelyPolygon(board_verts)
                    if poly.is_valid and not poly.is_empty:
                        pad_polys.append(poly)
                        placed = True
                        break
                except Exception:
                    pass
        if not placed:
            bx, by = transform_point(pin.center.x, pin.center.y, comp, is_bottom=is_bottom)
            pad_polys.append(ShapelyPoint(bx, by).buffer(0.05))

    if not pad_polys:
        return None

    return unary_union(pad_polys)


def find_outermost_pad_overlapping_components(
    comp: Component,
    candidates: Sequence[Component],
    packages: list[Package],
    *,
    is_bottom_primary: bool = False,
    is_bottom_candidates: bool = False,
    user_symbols: dict | None = None,
) -> list[Component]:
    """Return *candidates* whose **outermost** pads overlap *comp*'s pads.

    For each candidate, only the outermost (convex-hull perimeter) pads are
    considered.  *comp*'s full pad set is used.
    """
    if not _HAS_SHAPELY:
        return []

    pad_union_comp = _get_pad_union(comp, packages, is_bottom=is_bottom_primary,
                                    user_symbols=user_symbols)
    if pad_union_comp is None:
        pad_union_comp = ShapelyPoint(comp.x, comp.y).buffer(0.05)

    overlapping: list[Component] = []
    for cand in candidates:
        outermost_union = _get_outermost_pad_union(cand, packages,
                                                   is_bottom=is_bottom_candidates,
                                                   user_symbols=user_symbols)
        if outermost_union is None:
            outermost_union = ShapelyPoint(cand.x, cand.y).buffer(0.05)
        if pad_union_comp.intersects(outermost_union):
            overlapping.append(cand)
    return overlapping


# ---------------------------------------------------------------------------
# 7. Pad-to-Pad Overlap Detection
# ---------------------------------------------------------------------------

def _mm_scale(units: str, unit_override: str | None) -> float:
    """Return the scale factor that converts symbol params to MM.

    ODB++ standard symbol name numbers are encoded in the *sub-unit* of the
    file's declared unit:
      - INCH files → mils  (×0.0254 to get mm)
      - MM   files → microns (×0.001 to get mm)
    unit_override "I" / "M" overrides the file-level unit.
    Matches symbol_renderer._get_scale_factor().
    """
    if unit_override == "I":
        return 0.0254    # mils → mm
    if unit_override == "M":
        return 0.001     # microns → mm
    if units == "INCH":
        return 0.0254    # mils → mm
    return 0.001         # microns → mm


def _rot_pts(pts: np.ndarray, cx: float, cy: float, angle_deg: float) -> np.ndarray:
    """Rotate *pts* (N×2) clockwise by *angle_deg* around (cx, cy).

    Matches symbol_renderer._rotate_points() convention (CW for positive angle).
    """
    a = math.radians(-angle_deg)   # negative → CW in standard math coords
    cos_a, sin_a = math.cos(a), math.sin(a)
    shifted = pts - np.array([cx, cy])
    rotated = np.column_stack([
        shifted[:, 0] * cos_a - shifted[:, 1] * sin_a,
        shifted[:, 0] * sin_a + shifted[:, 1] * cos_a,
    ])
    return rotated + np.array([cx, cy])


def _symbol_to_shapely(symbol_name: str, x: float, y: float,
                       rotation: float, mirror: bool,
                       units: str = "INCH", unit_override: str | None = None,
                       resize_factor: float | None = None):
    """Convert a standard symbol name to a Shapely geometry at board position.

    Mirrors the shape logic in ``symbol_to_patch()`` but produces Shapely
    objects for geometric analysis instead of matplotlib patches.  Falls back
    to a small circular buffer for unrecognised or complex symbol types.
    """
    if not _HAS_SHAPELY:
        return None

    try:
        sym = resolve_symbol(symbol_name)
    except Exception:
        return ShapelyPoint(x, y).buffer(0.025)

    scale = _mm_scale(units, unit_override)
    if resize_factor is not None and resize_factor > 0:
        scale *= resize_factor

    def _apply_transform(pts: np.ndarray) -> np.ndarray:
        if mirror:
            pts[:, 0] = 2 * x - pts[:, 0]
        if rotation:
            pts = _rot_pts(pts, x, y, rotation)
        return pts

    if sym.type == "round":
        return ShapelyPoint(x, y).buffer(sym.params["diameter"] * scale / 2)

    if sym.type == "square":
        s = sym.params["side"] * scale / 2
        corners = np.array([
            [x - s, y - s], [x + s, y - s],
            [x + s, y + s], [x - s, y + s],
        ])
        corners = _apply_transform(corners)
        try:
            return ShapelyPolygon(corners)
        except Exception:
            return ShapelyPoint(x, y).buffer(s)

    if sym.type in ("rect", "rect_round", "rect_chamfer"):
        w = sym.params["width"] * scale / 2
        h = sym.params["height"] * scale / 2
        corners = np.array([
            [x - w, y - h], [x + w, y - h],
            [x + w, y + h], [x - w, y + h],
        ])
        corners = _apply_transform(corners)
        try:
            return ShapelyPolygon(corners)
        except Exception:
            return ShapelyPoint(x, y).buffer(max(w, h))

    if sym.type == "oval":
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        half_long = max(w, h) / 2
        half_short = min(w, h) / 2
        if w >= h:
            bar = np.array([
                [x - half_long + half_short, y - half_short],
                [x + half_long - half_short, y - half_short],
                [x + half_long - half_short, y + half_short],
                [x - half_long + half_short, y + half_short],
            ])
            bar = _apply_transform(bar)
            try:
                rect = ShapelyPolygon(bar)
            except Exception:
                rect = ShapelyPoint(x, y).buffer(half_long)
            dx = (half_long - half_short) * math.cos(math.radians(rotation if not mirror else -rotation))
            dy = (half_long - half_short) * math.sin(math.radians(rotation if not mirror else -rotation))
            c1 = ShapelyPoint(x - dx, y - dy).buffer(half_short)
            c2 = ShapelyPoint(x + dx, y + dy).buffer(half_short)
            return unary_union([rect, c1, c2])
        else:
            bar = np.array([
                [x - half_short, y - half_long + half_short],
                [x + half_short, y - half_long + half_short],
                [x + half_short, y + half_long - half_short],
                [x - half_short, y + half_long - half_short],
            ])
            bar = _apply_transform(bar)
            try:
                rect = ShapelyPolygon(bar)
            except Exception:
                rect = ShapelyPoint(x, y).buffer(half_long)
            dx = (half_long - half_short) * math.sin(math.radians(rotation if not mirror else -rotation))
            dy = (half_long - half_short) * math.cos(math.radians(rotation if not mirror else -rotation))
            c1 = ShapelyPoint(x - dx, y + dy).buffer(half_short)
            c2 = ShapelyPoint(x + dx, y - dy).buffer(half_short)
            return unary_union([rect, c1, c2])

    if sym.type == "ellipse":
        w = sym.params["width"] * scale / 2
        h = sym.params["height"] * scale / 2
        return ShapelyPoint(x, y).buffer(1.0).simplify(0.01).__class__  # fallback

    if sym.type == "diamond":
        w = sym.params["width"] * scale / 2
        h = sym.params["height"] * scale / 2
        verts = np.array([[x, y + h], [x + w, y], [x, y - h], [x - w, y]])
        verts = _apply_transform(verts)
        try:
            return ShapelyPolygon(verts)
        except Exception:
            return ShapelyPoint(x, y).buffer(max(w, h))

    # Fallback: circular approximation using a rough size estimate
    try:
        size = max(
            sym.params.get("diameter", 0),
            sym.params.get("width", 0),
            sym.params.get("height", 0),
            sym.params.get("side", 0),
            sym.params.get("outer_diameter", 0),
            sym.params.get("outer_size", 0),
            sym.params.get("outer_width", 0),
        ) * scale / 2
        if size > 0:
            return ShapelyPoint(x, y).buffer(size)
    except Exception:
        pass
    return ShapelyPoint(x, y).buffer(0.025)


def _user_symbol_to_shapely(symbol: UserSymbol, x: float, y: float,
                            rotation: float, mirror: bool):
    """Convert a UserSymbol to a Shapely geometry union at board position (x, y).

    Handles the same four feature record types as ``user_symbol_to_patches()``:
    SurfaceRecord, LineRecord, ArcRecord, and PadRecord.  The result is a
    unary union of all sub-geometries, suitable for geometric analysis.
    """
    if not _HAS_SHAPELY:
        return None

    geoms = []
    sym_lookup = {s.index: s for s in symbol.symbols}

    def _local_to_board(pts: np.ndarray) -> np.ndarray:
        """Apply mirror → rotate (CW) → translate to symbol-local points.

        Matches symbol_renderer._user_local_to_board() convention.
        """
        out = np.asarray(pts, dtype=float).copy()
        if mirror:
            out[:, 0] = -out[:, 0]
        if rotation:
            a = math.radians(-rotation)   # negative → CW
            cos_a, sin_a = math.cos(a), math.sin(a)
            rotated = np.column_stack([
                out[:, 0] * cos_a - out[:, 1] * sin_a,
                out[:, 0] * sin_a + out[:, 1] * cos_a,
            ])
            out = rotated
        out[:, 0] += x
        out[:, 1] += y
        return out

    for feature in symbol.features:
        if isinstance(feature, SurfaceRecord):
            for contour in feature.contours:
                if not contour.is_island:
                    continue
                verts = contour_to_vertices(contour)
                if len(verts) < 3:
                    continue
                board_verts = _local_to_board(np.array(verts))
                try:
                    poly = ShapelyPolygon(board_verts.tolist())
                    if poly.is_valid and not poly.is_empty:
                        geoms.append(poly)
                except Exception:
                    pass

        elif isinstance(feature, LineRecord):
            sym_ref = sym_lookup.get(feature.symbol_idx)
            if sym_ref is None:
                continue
            width = get_line_width_for_symbol(
                sym_ref.name, symbol.units, sym_ref.unit_override)
            if width <= 0:
                continue
            pts = _local_to_board(
                np.array([[feature.xs, feature.ys], [feature.xe, feature.ye]]))
            try:
                geoms.append(LineString(pts.tolist()).buffer(width / 2))
            except Exception:
                pass

        elif isinstance(feature, ArcRecord):
            sym_ref = sym_lookup.get(feature.symbol_idx)
            if sym_ref is None:
                continue
            width = get_line_width_for_symbol(
                sym_ref.name, symbol.units, sym_ref.unit_override)
            if width <= 0:
                continue
            arc_pts = arc_to_points(
                feature.xs, feature.ys, feature.xe, feature.ye,
                feature.xc, feature.yc, feature.clockwise, num_points=24)
            if len(arc_pts) < 2:
                continue
            board_pts = _local_to_board(np.array(arc_pts))
            try:
                geoms.append(LineString(board_pts.tolist()).buffer(width / 2))
            except Exception:
                pass

        elif isinstance(feature, PadRecord):
            sym_ref = sym_lookup.get(feature.symbol_idx)
            if sym_ref is None:
                continue
            pos = _local_to_board(np.array([[feature.x, feature.y]]))[0]
            eff_mirror = mirror ^ feature.mirror
            eff_rot = (rotation - feature.rotation) if mirror else (rotation + feature.rotation)
            g = _symbol_to_shapely(
                sym_ref.name, float(pos[0]), float(pos[1]),
                eff_rot, eff_mirror,
                symbol.units, sym_ref.unit_override,
            )
            if g is not None and not g.is_empty:
                geoms.append(g)

    if not geoms:
        return None
    return unary_union(geoms)


def _get_pad_union(comp: Component, packages: list[Package],
                   *, is_bottom: bool = False, user_symbols: dict | None = None):
    """Build a union of all individual pad polygons for *comp*.

    Primary path: uses FID-resolved ``Toeprint.geom`` data (the same source
    as the visualiser's ``draw_components()``).  For UserSymbol pads this
    calls ``_user_symbol_to_shapely()`` which handles all four feature record
    types (SurfaceRecord, LineRecord, ArcRecord, PadRecord).

    Fallback: when no toeprint has a resolved ``geom``, falls back to the
    package-level pin outline definitions (EDA data).

    Returns a Shapely geometry (union of all pads) or None.
    """
    if not _HAS_SHAPELY:
        return None
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return None

    user_symbols = user_symbols or {}

    # --- Primary path: use FID-resolved toeprint geometry (tp.geom) ----------
    # tp.geom.x / tp.geom.y are already in board coordinates (signal-layer
    # feature data), so no transform_point() call is needed for position.
    tp_geom_polys = []
    for tp in comp.toeprints:
        if tp.geom is None:
            continue
        geom = tp.geom
        # is_bottom rotation correction mirrors the view-path logic in
        # component_overlay._draw_component_geometry().
        pad_rot = -geom.rotation if is_bottom else geom.rotation

        if geom.is_user_symbol and geom.symbol_name in user_symbols:
            g = _user_symbol_to_shapely(
                user_symbols[geom.symbol_name],
                geom.x, geom.y, pad_rot, geom.mirror,
            )
        else:
            g = _symbol_to_shapely(
                geom.symbol_name, geom.x, geom.y, pad_rot, geom.mirror,
                geom.units, geom.unit_override, geom.resize_factor,
            )

        if g is not None and not g.is_empty:
            tp_geom_polys.append(g)

    if tp_geom_polys:
        return unary_union(tp_geom_polys)

    # --- Fallback: package-level pin outlines (EDA definition) ---------------
    pkg = packages[comp.pkg_ref]
    pad_polys = []

    for pin in pkg.pins:
        placed = False
        for outline in pin.outlines:
            verts = _outline_vertices(outline)
            if not verts:
                continue
            board_verts = [transform_point(v[0], v[1], comp, is_bottom=is_bottom) for v in verts]
            if len(board_verts) >= 3:
                try:
                    poly = ShapelyPolygon(board_verts)
                    if poly.is_valid and not poly.is_empty:
                        pad_polys.append(poly)
                        placed = True
                        break
                except Exception:
                    pass
        if not placed:
            bx, by = transform_point(pin.center.x, pin.center.y, comp, is_bottom=is_bottom)
            pad_polys.append(ShapelyPoint(bx, by).buffer(0.05))

    # Fallback: toeprint positions if package has no pin data
    if not pad_polys:
        for tp in comp.toeprints:
            pad_polys.append(ShapelyPoint(tp.x, tp.y).buffer(0.05))

    if not pad_polys:
        return None

    return unary_union(pad_polys)


def find_pad_overlapping_components(
    comp: Component,
    candidates: Sequence[Component],
    packages: list[Package],
    *,
    is_bottom_primary: bool = False,
    is_bottom_candidates: bool = False,
    user_symbols: dict | None = None,
) -> list[Component]:
    """Return *candidates* whose pads overlap *comp*'s pads.

    Unlike :func:`find_overlapping_components` (which uses the full outline
    convex hull), this function checks pad-level geometry only.  Outline
    overlap is acceptable; pad-to-pad contact is not.
    """
    if not _HAS_SHAPELY:
        return []

    pad_union_comp = _get_pad_union(comp, packages, is_bottom=is_bottom_primary,
                                    user_symbols=user_symbols)
    if pad_union_comp is None:
        pad_union_comp = ShapelyPoint(comp.x, comp.y).buffer(0.05)

    overlapping: list[Component] = []
    for cand in candidates:
        pad_union_cand = _get_pad_union(cand, packages, is_bottom=is_bottom_candidates,
                                        user_symbols=user_symbols)
        if pad_union_cand is None:
            pad_union_cand = ShapelyPoint(cand.x, cand.y).buffer(0.05)
        if pad_union_comp.intersects(pad_union_cand):
            overlapping.append(cand)
    return overlapping


def find_components_inside_outline(
    comp: Component,
    candidates: Sequence[Component],
    packages: list[Package],
    *,
    is_bottom: bool = False,
) -> list[Component]:
    """Return *candidates* whose footprint is inside *comp*'s component outline.

    Checks whether a candidate's footprint (or centre point fallback) is
    contained within the physical component body outline of *comp*.  This
    captures cases where pads do not overlap but the candidate sits entirely
    inside the outline boundary.
    """
    if not _HAS_SHAPELY:
        return []

    outline = _resolve_outline(comp, packages, is_bottom=is_bottom)
    if outline is None:
        return []

    inside: list[Component] = []
    for cand in candidates:
        fp_cand = _resolve_footprint(cand, packages, is_bottom=is_bottom)
        if fp_cand is None:
            fp_cand = ShapelyPoint(cand.x, cand.y).buffer(0.05)
        if outline.contains(fp_cand):
            inside.append(cand)
    return inside


# ---------------------------------------------------------------------------
# 7b. Empty-Centre Pad Layout Detection
# ---------------------------------------------------------------------------

def has_empty_center(comp: Component, packages: list[Package]) -> bool:
    """Return True if the IC's internal pad grid has no pads in the interior.

    Algorithm:
      1. Collect all pin centre positions (package-local coordinates).
      2. Detect the grid pitch from the median spacing in X and Y.
      3. Shrink the bounding box inward by ``2 * pitch`` on each side.
      4. If **zero** pins fall inside this interior box → empty centre.

    Returns False when the package has fewer than 9 pins (too few to form
    a meaningful interior) or when pitch cannot be determined.
    """
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return False

    pkg = packages[comp.pkg_ref]
    if len(pkg.pins) < 9:
        return False

    # Gather pin centres in package-local coordinates
    xs = [pin.center.x for pin in pkg.pins]
    ys = [pin.center.y for pin in pkg.pins]

    # Detect grid pitch (median of unique sorted spacings)
    pitch_x = _median_spacing(xs)
    pitch_y = _median_spacing(ys)
    if pitch_x <= 0 or pitch_y <= 0:
        return False

    # Bounding box of all pin positions
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    # Interior region: shrink by 2 * pitch on each side
    # Use a small tolerance (half pitch) to handle floating-point drift
    # at grid boundaries.
    eps = 0.25 * min(pitch_x, pitch_y)
    margin_x = 2.0 * pitch_x - eps
    margin_y = 2.0 * pitch_y - eps
    inner_min_x = min_x + margin_x
    inner_max_x = max_x - margin_x
    inner_min_y = min_y + margin_y
    inner_max_y = max_y - margin_y

    # If the interior region is degenerate, no meaningful void
    if inner_min_x >= inner_max_x or inner_min_y >= inner_max_y:
        return False

    # Count pins inside the interior region
    for px, py in zip(xs, ys):
        if inner_min_x <= px <= inner_max_x and inner_min_y <= py <= inner_max_y:
            return False  # found a pad in the interior → not empty

    return True


def _median_spacing(values: list[float]) -> float:
    """Return the median gap between consecutive sorted unique values."""
    unique = sorted(set(values))
    if len(unique) < 2:
        return 0.0
    gaps = [unique[i + 1] - unique[i] for i in range(len(unique) - 1)]
    gaps.sort()
    return gaps[len(gaps) // 2]


def find_empty_center_ics(
    components: Sequence[Component],
    packages: list[Package],
) -> list[Component]:
    """Return IC components whose pad layout has an empty interior."""
    from src.checklist.component_classifier import find_ics
    return [c for c in find_ics(components) if has_empty_center(c, packages)]


# ---------------------------------------------------------------------------
# 8. Component Size Utilities
# ---------------------------------------------------------------------------

def get_component_size(comp: Component,
                       size_maps: list[dict[str, int]] | None = None,
                       packages: list[Package] | None = None) -> int:
    """Return the numeric size code for *comp*.

    Resolution order:
        1. Lookup ``comp.part_name`` in the provided *size_maps*
           (list of ``{part_name: size}`` dicts from reference CSVs).
        2. Parse from package bbox dimensions (metric LLWW code).
        3. Return 0 if unknown.
    """
    part = comp.part_name or ""

    # 1. Reference CSV lookup
    if size_maps:
        for sm in size_maps:
            if part in sm:
                return sm[part]

    # 2. Infer from package bbox
    if packages and 0 <= comp.pkg_ref < len(packages):
        pkg = packages[comp.pkg_ref]
        if pkg.bbox:
            w_mm = abs(pkg.bbox.xmax - pkg.bbox.xmin)
            h_mm = abs(pkg.bbox.ymax - pkg.bbox.ymin)
            # Convert to metric size code: length(0.1mm) * 100 + width(0.1mm)
            l_code = int(round(max(w_mm, h_mm) * 10))
            w_code = int(round(min(w_mm, h_mm) * 10))
            return l_code * 100 + w_code

    return 0


def size_at_least(size_code: int, threshold: int = 2012) -> bool:
    """Return True if *size_code* >= *threshold*."""
    return size_code >= threshold


def filter_by_size(components: Sequence[Component],
                   threshold: int,
                   size_maps: list[dict[str, int]] | None = None,
                   packages: list[Package] | None = None,
                   ) -> list[tuple[Component, int]]:
    """Return (component, size) pairs for components with size >= *threshold*."""
    result: list[tuple[Component, int]] = []
    for comp in components:
        sz = get_component_size(comp, size_maps, packages)
        if sz >= threshold:
            result.append((comp, sz))
    return result


# ---------------------------------------------------------------------------
# 9. PCB Outline Clearance
# ---------------------------------------------------------------------------

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
    """Return a polygon *inset_mm* inward from *board_poly*'s boundary.

    The returned polygon represents the clearance zone boundary.
    Returns None on failure.
    """
    if not _HAS_SHAPELY or board_poly is None:
        return None
    inset = board_poly.buffer(-inset_mm)
    if inset.is_empty or not inset.is_valid:
        return None
    return inset


def distance_to_outline(comp: Component, board_poly,
                        packages: list[Package] | None = None) -> float:
    """Return the minimum distance from any pin/pad of *comp* to the board outline.

    Falls back to centre-point distance if no pin geometry is available.
    """
    if not _HAS_SHAPELY or board_poly is None:
        return float("inf")

    outline = board_poly.boundary
    min_dist = float("inf")

    # Check toeprint (pin/pad) positions
    if comp.toeprints:
        for tp in comp.toeprints:
            d = outline.distance(ShapelyPoint(tp.x, tp.y))
            if d < min_dist:
                min_dist = d
        return min_dist

    # Fallback: component centre
    return outline.distance(ShapelyPoint(comp.x, comp.y))


def pad_distance_to_outline(comp: Component, board_poly,
                            packages: list[Package] | None = None,
                            *, is_bottom: bool = False,
                            user_symbols: dict | None = None) -> float:
    """Return the minimum distance from *comp*'s pad geometry to the board outline.

    Uses actual pad polygons (via ``_get_pad_union``) rather than just pad
    centre points.  Falls back to toeprint points, then component centre.
    """
    if not _HAS_SHAPELY or board_poly is None:
        return float("inf")

    outline = board_poly.boundary

    if packages is not None:
        pad_geom = _get_pad_union(comp, packages, is_bottom=is_bottom,
                                  user_symbols=user_symbols)
        if pad_geom is not None:
            return outline.distance(pad_geom)

    # Fallback: toeprint centre points
    if comp.toeprints:
        return min(
            outline.distance(ShapelyPoint(tp.x, tp.y))
            for tp in comp.toeprints
        )

    return outline.distance(ShapelyPoint(comp.x, comp.y))


def pad_distance_to_component(comp: Component, other: Component,
                              packages: list[Package],
                              *, is_bottom: bool = False,
                              user_symbols: dict | None = None) -> float:
    """Return the minimum distance from *comp*'s pads to *other*'s footprint.

    Measures from the actual pad polygons of *comp* to the footprint polygon
    of *other*.  Falls back to ``edge_distance`` if geometry is unavailable.
    """
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
    packages: list[Package],
    *,
    is_bottom_a: bool = False,
    is_bottom_b: bool = False,
    user_symbols: dict | None = None,
) -> float:
    """Return the minimum distance between *comp_a*'s pads and *comp_b*'s pads.

    Uses FID-resolved toeprint geometry (UserSymbol-aware) for both components.
    Falls back to ``edge_distance`` when pad geometry is unavailable.
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
    packages: list[Package] | None = None,
) -> list[tuple[Component, float]]:
    """Return components with pins/pads in the clearance zone.

    The clearance zone is the area between the board outline and the
    inset boundary.  Returns list of ``(component, min_distance_to_outline)``.
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
                # Point is in clearance zone if inside board but outside inset
                if board_poly.contains(pt) and not inset_poly.contains(pt):
                    in_zone = True
                    d = outline.distance(pt)
                    if d < min_dist:
                        min_dist = d
                # Also check points outside the board entirely
                elif not board_poly.contains(pt):
                    in_zone = True
                    d = outline.distance(pt)
                    if d < min_dist:
                        min_dist = d
        else:
            # Fallback: check centre only
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
    packages: list[Package] | None = None,
) -> list[tuple[Component, float]]:
    """Return components whose **pad geometry** intersects the clearance zone.

    Unlike :func:`components_in_clearance_zone` (which tests toeprint centre
    points), this function builds the actual pad polygons via
    ``_get_pad_union`` and checks whether any pad intersects the area between
    the board outline and the inset boundary.  Component outline overlap is
    acceptable — only pad-level intrusion is flagged.

    Returns ``[(component, min_pad_distance_to_outline), ...]``.
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
            # Fallback: toeprint centre points (same as original logic)
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

        # Check if any pad geometry intersects the clearance zone or
        # extends outside the board.
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

    Iterates over every SIGNAL layer in *layers_data* and checks each copper
    feature (pad / line / arc) against the clearance zone (area between the
    board outline and the inset boundary).

    When *eda_data* is provided the function resolves the originating **net
    name** for each violating feature via the EDA subnet → feature-id mapping.

    Returns a list of dicts::

        {"layer_name": str, "net_name": str, "feature_type": str,
         "distance": str, "status": str}
    """
    from src.models import ArcRecord, LineRecord, PadRecord
    from src.parsers.symbol_resolver import resolve_symbol
    from src.visualizer.fid_lookup import build_layer_name_map

    if not _HAS_SHAPELY or board_poly is None or inset_poly is None:
        return []

    outline = board_poly.boundary
    clearance_zone = board_poly.difference(inset_poly)
    if clearance_zone.is_empty:
        return []

    # --- build reverse map: (layer_name, feature_index) -> net_name --------
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

    # --- collect signal layers ---------------------------------------------
    signal_layers: list[tuple[str, object, object]] = []
    for name, (lf, ml) in layers_data.items():
        if ml.type == "SIGNAL":
            signal_layers.append((name, lf, ml))

    results: list[dict] = []
    # Track which nets have already been reported per layer to avoid
    # flooding the output with thousands of individual feature hits.
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
    """Convert a layer feature record to a Shapely geometry.

    Returns a buffered point for pads, a buffered line for lines/arcs, or
    None if conversion is not possible.
    """
    from src.models import ArcRecord, LineRecord, PadRecord
    from src.parsers.symbol_resolver import resolve_symbol

    if not _HAS_SHAPELY:
        return None

    if isinstance(feat, PadRecord):
        sym_ref = sym_lookup.get(feat.symbol_idx)
        radius = 0.05  # fallback
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
        # Approximate arc as a polyline for clearance purposes
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


# ---------------------------------------------------------------------------
# 10. VIA-on-Pad Detection
# ---------------------------------------------------------------------------

def _build_via_positions_by_attribute(
    layers_data: dict,
    signal_layer_name: str,
) -> set[tuple[float, float]]:
    """Return VIA (x, y) positions on *signal_layer_name* using ``.pad_usage``.

    A pad whose ``.pad_usage`` raw value is 1 is a via (0 = toeprint).
    Only pads on the specified signal layer are returned.
    """
    from src.models import PadRecord

    ld = layers_data.get(signal_layer_name)
    if ld is None:
        return set()

    lf = ld[0]
    via_text = lf.attr_texts.get(1)
    positions: set[tuple[float, float]] = set()

    for feat in lf.features:
        if not isinstance(feat, PadRecord):
            continue
        pu = feat.attributes.get(".pad_usage")
        if pu is None:
            continue
        if pu != via_text and pu != "1":
            continue
        positions.add((round(feat.x, 4), round(feat.y, 4)))

    return positions


def _build_via_positions_by_subnet(
    eda_data: EdaData,
    layers_data: dict,
    signal_layer_name: str,
) -> set[tuple[float, float]]:
    """Return VIA (x, y) positions on *signal_layer_name* via EDA subnet FIDs.

    Only FID references that resolve to a feature on the specified signal
    layer are included.
    """
    from src.models import PadRecord

    # Map EDA layer indices to layer names.
    layer_name_map: dict[int, str] = {}
    for idx, name in enumerate(eda_data.layer_names):
        layer_name_map[idx] = name

    positions: set[tuple[float, float]] = set()

    for net in eda_data.nets:
        for subnet in net.subnets:
            if subnet.type != "VIA":
                continue
            for fid in subnet.feature_ids:
                if fid.type != "C":
                    continue
                layer_name = layer_name_map.get(fid.layer_idx)
                if layer_name != signal_layer_name:
                    continue
                ld = layers_data.get(layer_name)
                if ld is None:
                    continue
                features = ld[0].features
                if fid.feature_idx < 0 or fid.feature_idx >= len(features):
                    continue
                feat = features[fid.feature_idx]
                if not isinstance(feat, PadRecord):
                    continue
                positions.add((round(feat.x, 4), round(feat.y, 4)))

    return positions


def build_via_position_set(
    eda_data: EdaData,
    layers_data: dict,
    is_bottom: bool = False,
) -> set[tuple[float, float]]:
    """Return deduplicated (x, y) board positions of VIAs on one surface.

    Collects via positions for either the **top** or **bottom** signal
    layer from two independent sources and returns their union:

      1. **``.pad_usage`` attribute** — via pads on the target signal layer
         identified by the ``.pad_usage`` feature attribute (most reliable).
      2. **EDA VIA subnet FIDs** — resolves via positions from EDA net
         connectivity data, filtered to the target signal layer.

    Both sources are always unioned to avoid false negatives.  Positions
    are rounded to 4 decimal places (0.1 µm in mm) for deduplication.

    Args:
        eda_data: Parsed EDA connectivity data.
        layers_data: Dict mapping layer names to (LayerFeatures, MatrixLayer).
        is_bottom: When True, collect vias for the bottom signal layer;
                   otherwise for the top signal layer.
    """
    from src.visualizer.fid_lookup import _find_top_bottom_signal_layers

    top_name, bot_name = _find_top_bottom_signal_layers(layers_data)
    target_name = bot_name if is_bottom else top_name
    if target_name is None:
        return set()

    positions: set[tuple[float, float]] = set()

    # Source 1: .pad_usage attribute on the target signal layer.
    positions.update(
        _build_via_positions_by_attribute(layers_data, target_name))

    # Source 2: EDA subnet FID resolution on the target signal layer.
    positions.update(
        _build_via_positions_by_subnet(eda_data, layers_data, target_name))

    return positions


def build_toeprint_lookup(
    comp: Component,
    pkg: Package,
) -> dict[int, "Toeprint"]:
    """Build a reliable mapping from package pin index to toeprint.

    Resolution strategy (most reliable first):

      1. **Name match** — match ``toeprint.name`` to ``pin.name``.  This is
         the most robust method because pin names are stable identifiers.
      2. **Direct index** — use ``toeprint.pin_num`` as the pin index.

    Returns a dict mapping pin index (0-based, matching
    ``enumerate(pkg.pins)``) to the corresponding :class:`Toeprint`.
    """
    from src.models import Toeprint  # noqa: F811

    result: dict[int, Toeprint] = {}

    # Strategy 1: match toeprint.name to pin.name
    tp_by_name: dict[str, Toeprint] = {}
    for tp in comp.toeprints:
        if tp.name:
            tp_by_name[tp.name] = tp

    if tp_by_name:
        for pin_idx, pin in enumerate(pkg.pins):
            tp = tp_by_name.get(pin.name)
            if tp is not None:
                result[pin_idx] = tp

    # Strategy 2: fill remaining pins using pin_num == pin_idx
    if len(result) < len(pkg.pins):
        tp_by_num: dict[int, Toeprint] = {}
        for tp in comp.toeprints:
            tp_by_num[tp.pin_num] = tp
        for pin_idx in range(len(pkg.pins)):
            if pin_idx not in result:
                tp = tp_by_num.get(pin_idx)
                if tp is not None:
                    result[pin_idx] = tp

    return result


def lookup_resolved_pads_for_pin(
    fid_resolved: dict,
    comp: Component,
    is_bottom: bool,
    pin_idx: int,
    signal_layer_name: str | None = None,
) -> "list | None":
    """Look up FID-resolved pad features for a specific pin.

    Searches *fid_resolved* using both 0-based and 1-based pin numbering
    conventions.  Optionally filters to only features on *signal_layer_name*
    so that containment testing uses the correct copper layer.

    Returns a list of :class:`ResolvedPadFeature` or ``None`` if nothing found.
    """
    side = "B" if is_bottom else "T"
    comp_idx = comp.comp_index

    for pnum in (pin_idx, pin_idx + 1):
        key = (side, comp_idx, pnum)
        pad_features = fid_resolved.get(key)
        if not pad_features:
            continue
        if signal_layer_name is not None:
            filtered = [rpf for rpf in pad_features
                        if rpf.layer_name == signal_layer_name]
            if filtered:
                return filtered
        else:
            return pad_features

    return None


def _symbol_to_polygon(
    symbol_name: str,
    x: float, y: float,
    rotation: float = 0.0,
    mirror: bool = False,
    units: str = "INCH",
    unit_override: str = None,
    resize_factor: float = None,
    num_circle_pts: int = 32,
) -> np.ndarray | None:
    """Convert a standard symbol to board-coordinate polygon vertices.

    Mirrors the logic of :func:`symbol_to_patch` in the visualiser but
    returns an (N, 2) array of polygon vertices instead of a matplotlib
    patch, suitable for point-in-polygon containment testing.

    Returns ``None`` for unsupported or degenerate symbols.
    """
    from src.parsers.symbol_resolver import resolve_symbol
    from src.visualizer.symbol_renderer import (
        _get_scale_factor, _mirror_points, _rotate_points,
    )

    sym = resolve_symbol(symbol_name)
    scale = _get_scale_factor(units, unit_override)
    if resize_factor is not None and resize_factor != 0.0:
        scale *= resize_factor

    if sym.type == "round":
        d = sym.params["diameter"] * scale
        r = d / 2
        angles = np.linspace(0, 2 * np.pi, num_circle_pts, endpoint=False)
        return np.column_stack([x + r * np.cos(angles),
                                y + r * np.sin(angles)])

    if sym.type == "square":
        s = sym.params["side"] * scale
        corners = np.array([
            [x - s/2, y - s/2], [x + s/2, y - s/2],
            [x + s/2, y + s/2], [x - s/2, y + s/2],
        ])
        if mirror:
            corners = _mirror_points(corners, x)
        if rotation:
            corners = _rotate_points(corners, x, y, rotation)
        return corners

    if sym.type in ("rect", "rect_round", "rect_chamfer"):
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        corners = np.array([
            [x - w/2, y - h/2], [x + w/2, y - h/2],
            [x + w/2, y + h/2], [x - w/2, y + h/2],
        ])
        if mirror:
            corners = _mirror_points(corners, x)
        if rotation:
            corners = _rotate_points(corners, x, y, rotation)
        return corners

    if sym.type == "oval":
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        r = min(w, h) / 2
        # Approximate oval as a rounded rectangle
        if w >= h:
            hw, hh = w/2, h/2
        else:
            hw, hh = w/2, h/2
        angles = np.linspace(0, 2 * np.pi, num_circle_pts, endpoint=False)
        pts = np.column_stack([x + hw * np.cos(angles),
                               y + hh * np.sin(angles)])
        if mirror:
            pts = _mirror_points(pts, x)
        if rotation:
            pts = _rotate_points(pts, x, y, rotation)
        return pts

    if sym.type == "diamond":
        w = sym.params["width"] * scale / 2
        h = sym.params["height"] * scale / 2
        verts = np.array([
            [x, y + h], [x + w, y], [x, y - h], [x - w, y],
        ])
        if mirror:
            verts = _mirror_points(verts, x)
        if rotation:
            verts = _rotate_points(verts, x, y, rotation)
        return verts

    if sym.type == "octagon":
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        cs = sym.params["corner_size"] * scale
        from src.visualizer.symbol_renderer import _octagon_vertices
        verts = _octagon_vertices(x, y, w, h, cs)
        if mirror:
            verts = _mirror_points(verts, x)
        if rotation:
            verts = _rotate_points(verts, x, y, rotation)
        return verts

    if sym.type == "user_defined":
        return None

    # Donut types, ellipse, etc. — approximate as outer bounding circle/rect
    if sym.type in ("donut_r",):
        od = sym.params["outer_diameter"] * scale
        r = od / 2
        angles = np.linspace(0, 2 * np.pi, num_circle_pts, endpoint=False)
        return np.column_stack([x + r * np.cos(angles),
                                y + r * np.sin(angles)])

    if sym.type in ("donut_s", "donut_s_round", "donut_sr"):
        od = sym.params["outer_size"] * scale
        s = od / 2
        corners = np.array([
            [x - s, y - s], [x + s, y - s],
            [x + s, y + s], [x - s, y + s],
        ])
        if mirror:
            corners = _mirror_points(corners, x)
        if rotation:
            corners = _rotate_points(corners, x, y, rotation)
        return corners

    if sym.type in ("donut_rc", "donut_rc_round", "donut_o"):
        ow = sym.params["outer_width"] * scale
        oh = sym.params["outer_height"] * scale
        corners = np.array([
            [x - ow/2, y - oh/2], [x + ow/2, y - oh/2],
            [x + ow/2, y + oh/2], [x - ow/2, y + oh/2],
        ])
        if mirror:
            corners = _mirror_points(corners, x)
        if rotation:
            corners = _rotate_points(corners, x, y, rotation)
        return corners

    if sym.type == "ellipse":
        w = sym.params["width"] * scale
        h = sym.params["height"] * scale
        angles = np.linspace(0, 2 * np.pi, num_circle_pts, endpoint=False)
        pts = np.column_stack([x + w/2 * np.cos(angles),
                               y + h/2 * np.sin(angles)])
        if mirror:
            pts = _mirror_points(pts, x)
        if rotation:
            pts = _rotate_points(pts, x, y, rotation)
        return pts

    return None


def _get_pad_polygon_board(
    pin: Pin,
    comp: Component,
    is_bottom: bool = False,
    num_circle_pts: int = 32,
) -> np.ndarray | None:
    """Return the EDA pin outline as board-coordinate vertices (fallback).

    Used only when no FID-resolved or spatially-matched copper pad feature
    is available.  Converts the first :class:`PinOutline` of *pin* into
    an (N, 2) array of board-space vertices.

    Returns ``None`` if the pin has no outlines or the outline is degenerate.
    """
    if not pin.outlines:
        return None

    ol = pin.outlines[0]
    p = ol.params

    if ol.type in ("CR", "CT"):
        xc = p.get("xc", 0.0)
        yc = p.get("yc", 0.0)
        r = p.get("radius", 0.0)
        if r <= 0:
            return None
        angles = np.linspace(0, 2 * np.pi, num_circle_pts, endpoint=False)
        local_pts = np.column_stack([
            xc + r * np.cos(angles),
            yc + r * np.sin(angles),
        ])
    elif ol.type == "RC":
        llx = p.get("llx", 0.0)
        lly = p.get("lly", 0.0)
        w = p.get("width", 0.0)
        h = p.get("height", 0.0)
        if w <= 0 or h <= 0:
            return None
        local_pts = np.array([
            [llx,     lly],
            [llx + w, lly],
            [llx + w, lly + h],
            [llx,     lly + h],
        ])
    elif ol.type == "SQ":
        xc = p.get("xc", 0.0)
        yc = p.get("yc", 0.0)
        hs = p.get("half_side", 0.0)
        if hs <= 0:
            return None
        local_pts = np.array([
            [xc - hs, yc - hs],
            [xc + hs, yc - hs],
            [xc + hs, yc + hs],
            [xc - hs, yc + hs],
        ])
    elif ol.type == "CONTOUR" and ol.contour is not None:
        local_pts = contour_to_vertices(ol.contour)
        if len(local_pts) < 3:
            return None
    else:
        return None

    return transform_pts(local_pts, comp, is_bottom=is_bottom)


def _point_in_polygon(px: float, py: float, verts: np.ndarray) -> bool:
    """Ray-casting point-in-polygon test.

    *verts* is an (N, 2) array of polygon vertices (closed automatically).
    """
    n = len(verts)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = verts[i]
        xj, yj = verts[j]
        if ((yi > py) != (yj > py)) and \
           (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _resolved_pad_polygon(
    rpf: "ResolvedPadFeature",
    is_bottom: bool = False,
) -> "np.ndarray | None":
    """Convert a FID-resolved pad feature to board-coordinate polygon vertices.

    Uses :func:`_symbol_to_polygon` with the pad record's board-space
    position, rotation, mirror, and the symbol's name / units.

    For bottom-layer pads the rotation is negated to match board-space
    orientation (ODB++ stores bottom-layer rotations in mirrored view).
    """
    pad = rpf.pad
    sym = rpf.symbol
    pad_rot = -pad.rotation if is_bottom else pad.rotation
    return _symbol_to_polygon(
        sym.name, pad.x, pad.y,
        rotation=pad_rot,
        mirror=pad.mirror,
        units=rpf.units,
        unit_override=sym.unit_override,
        resize_factor=pad.resize_factor,
    )


def count_vias_at_pad(
    comp: Component,
    pin_center_x: float,
    pin_center_y: float,
    via_positions: set[tuple[float, float]],
    is_bottom: bool = False,
    tolerance: float = 0.05,
    toeprint: "Toeprint | None" = None,
    pin: "Pin | None" = None,
    resolved_pads: "list | None" = None,
) -> int:
    """Count VIAs that fall within a pad's geometric boundary.

    Resolution priority (highest to lowest):

      1. **FID-resolved pad** — when *resolved_pads* is provided, each
         :class:`ResolvedPadFeature` is converted to a polygon via
         :func:`_symbol_to_polygon` and vias are tested for containment.
      2. **EDA pin outline** — when *pin* is provided, its outline is
         transformed to board coordinates via :func:`_get_pad_polygon_board`.
      3. **Centre-distance fallback** — simple radius check using *tolerance*.

    Args:
        comp: The component owning the pad.
        pin_center_x: Pin centre X in package-local coords (fallback).
        pin_center_y: Pin centre Y in package-local coords (fallback).
        via_positions: Set of (x, y) VIA board positions.
        is_bottom: Whether the component is on the bottom layer.
        tolerance: Distance fallback (mm) when no pad outline is available.
        toeprint: Optional toeprint with board-space (x, y) for the pad.
        pin: Optional Pin with outline geometry for precise containment.
        resolved_pads: Optional list of ResolvedPadFeature for this pin.
    """
    # Priority 1: FID-resolved pad geometry (actual copper features).
    if resolved_pads:
        count = 0
        for rpf in resolved_pads:
            poly = _resolved_pad_polygon(rpf, is_bottom=is_bottom)
            if poly is None:
                continue
            xmin, ymin = poly.min(axis=0)
            xmax, ymax = poly.max(axis=0)
            for vx, vy in via_positions:
                if vx < xmin or vx > xmax or vy < ymin or vy > ymax:
                    continue
                if _point_in_polygon(vx, vy, poly):
                    count += 1
            if count > 0:
                return count
        # If all resolved pads gave user_defined symbols (poly=None),
        # fall through to pin outline.

    # Priority 2: EDA pin outline geometry.
    poly = None
    if pin is not None:
        poly = _get_pad_polygon_board(pin, comp, is_bottom=is_bottom)

    if poly is not None:
        xmin, ymin = poly.min(axis=0)
        xmax, ymax = poly.max(axis=0)
        count = 0
        for vx, vy in via_positions:
            if vx < xmin or vx > xmax or vy < ymin or vy > ymax:
                continue
            if _point_in_polygon(vx, vy, poly):
                count += 1
        return count

    # Priority 3: simple centre-distance check.
    if toeprint is not None:
        bx, by = toeprint.x, toeprint.y
    else:
        bx, by = transform_point(pin_center_x, pin_center_y, comp,
                                  is_bottom=is_bottom)
    count = 0
    tol_sq = tolerance * tolerance
    for vx, vy in via_positions:
        dx = bx - vx
        dy = by - vy
        if dx * dx + dy * dy <= tol_sq:
            count += 1
    return count


# ---------------------------------------------------------------------------
# 14. Bending-Vulnerable Area Detection
# ---------------------------------------------------------------------------

def find_bending_vulnerable_areas(
    board_polygon,
    width_threshold: float = 8.0,
    protrusion_depth: float = 2.0,
) -> list:
    """Identify bending-vulnerable areas on the PCB.

    A bending-vulnerable area is a thin protruding region of the board where:
    - the local width is ≤ *width_threshold* mm, **and**
    - the protrusion extends ≥ *protrusion_depth* mm from the main body.

    Uses morphological opening (erosion + dilation) to separate thin
    protrusions from the bulk board shape.

    Parameters
    ----------
    board_polygon : shapely Polygon
        The PCB outline polygon (in mm).
    width_threshold : float
        Maximum width (mm) to be considered narrow.  Default 8.0.
    protrusion_depth : float
        Minimum protrusion depth (mm) to qualify.  Default 2.0.

    Returns
    -------
    list[shapely Polygon]
        Polygons representing each bending-vulnerable region.
        Empty list if none are found or shapely is unavailable.
    """
    if not _HAS_SHAPELY or board_polygon is None:
        return []

    half_w = width_threshold / 2.0

    # Step 1 – morphological opening: removes features narrower than the
    #          width threshold while preserving the main body shape.
    eroded = board_polygon.buffer(-half_w)
    if eroded.is_empty:
        # The entire board is narrower than the threshold.
        return [board_polygon]

    opened = eroded.buffer(half_w)

    # Step 2 – the difference is the set of thin protruding regions.
    protrusions = board_polygon.difference(opened)
    if protrusions.is_empty:
        return []

    # Decompose into individual polygons.
    if isinstance(protrusions, ShapelyMultiPolygon):
        parts = list(protrusions.geoms)
    elif isinstance(protrusions, ShapelyPolygon):
        parts = [protrusions]
    else:
        # GeometryCollection or unexpected type – extract polygons.
        parts = [g for g in protrusions.geoms
                 if isinstance(g, ShapelyPolygon)]

    # Step 3 – filter by protrusion depth.
    #   For each candidate polygon, measure the maximum distance from its
    #   boundary points to the opened (main body) polygon.  Only keep
    #   regions that protrude at least *protrusion_depth*.
    vulnerable: list = []
    for part in parts:
        max_dist = 0.0
        for coord in part.exterior.coords:
            d = ShapelyPoint(coord).distance(opened)
            if d > max_dist:
                max_dist = d
        if max_dist >= protrusion_depth:
            vulnerable.append(part)

    return vulnerable


# ---------------------------------------------------------------------------
# NC (Not Connected) pad detection
# ---------------------------------------------------------------------------

_NC_NET_NAMES = frozenset({"$NONE$", "NC", "NO_CONNECT", ""})


def is_pad_nc(
    toeprint: Toeprint | None,
    eda_data: EdaData | None,
) -> bool:
    """Return *True* if the pad has no net connection (NC).

    Detection logic (checked in order):

    1. ``toeprint`` is *None* or ``net_num < 0`` → no net assigned → NC.
    2. ``net_num`` out of range → invalid reference → NC.
    3. Net name matches a known NC pattern (``$NONE$``, ``NC``, …) → NC.
    4. **EDA subnet routing check** – the net's subnets are inspected across
       *all* layers.  If the net contains **no** ``TRC`` (trace), ``VIA``,
       or ``PLN`` (plane) subnets — i.e. only ``TOP`` (toeprint) subnets
       exist — the pad has no physical routing and is NC.
    """
    if toeprint is None:
        return False  # Cannot determine; assume connected (conservative)
    if toeprint.net_num < 0:
        return True
    if eda_data is None:
        return False
    if toeprint.net_num >= len(eda_data.nets):
        return True

    net = eda_data.nets[toeprint.net_num]

    # Quick name-based check
    if (net.name or "").strip().upper() in _NC_NET_NAMES:
        return True

    # Authoritative check: does this net have any routing at all?
    for subnet in net.subnets:
        if subnet.type in ("TRC", "VIA", "PLN"):
            return False  # Has routing → definitely connected

    # Net exists but has only TOP (toeprint) subnets → no routing → NC
    return True


# ---------------------------------------------------------------------------
# Shield Can Geometry Helpers
# ---------------------------------------------------------------------------

def _get_shield_can_outline(comp: Component,
                            packages: list[Package],
                            *, is_bottom: bool = False):
    """Build an outline polygon for a shield can component.

    Tries the component's package outlines first; falls back to the
    convex hull of pad centre positions (which trace the perimeter).

    Returns a Shapely Polygon or None.
    """
    if not _HAS_SHAPELY:
        return None
    outline = _resolve_outline(comp, packages, is_bottom=is_bottom)
    if outline is not None:
        return outline
    # Fallback: convex hull of pad centres
    centers = _get_pad_centers(comp, packages, is_bottom=is_bottom)
    if len(centers) >= 3:
        return MultiPoint(centers).convex_hull
    return None


def _find_nearest_segment(
    point: tuple[float, float],
    outline_poly,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Return the nearest edge segment of *outline_poly* to *point*.

    Returns ``((x1, y1), (x2, y2))`` or ``None``.
    """
    # Collect exterior coords from all constituent polygons when the outline
    # is a MultiPolygon (multiple package outline entries).
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


def _is_diagonal_segment(
    p1: tuple[float, float],
    p2: tuple[float, float],
    tolerance_deg: float = 10.0,
) -> bool:
    """Return True if the segment is neither horizontal nor vertical.

    Angles within *tolerance_deg* of 0°/180° (horizontal) or 90°
    (vertical) are considered non-diagonal.
    """
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    if dx == 0.0 and dy == 0.0:
        return False
    angle = math.degrees(math.atan2(dy, dx)) % 180.0  # [0, 180)
    # Horizontal: angle near 0° or 180° (i.e. near 0° after mod)
    if angle < tolerance_deg or angle > (180.0 - tolerance_deg):
        return False
    # Vertical: angle near 90°
    if abs(angle - 90.0) < tolerance_deg:
        return False
    return True


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
    """Check if *cap* is near a corner vertex or diagonal section of *shield_can*.

    Returns ``True`` when:
    - Any of *cap*'s pad centres fall within *corner_tolerance* (mm) of a
      shield-can outline vertex (corner area), **or**
    - The nearest shield-can edge segment to *cap*'s board centre is
      diagonal (neither horizontal nor vertical within tolerance).
    """
    if not _HAS_SHAPELY:
        return False

    outline = _get_shield_can_outline(shield_can, packages, is_bottom=sc_is_bottom)
    if outline is None:
        return False

    pad_centers = _get_pad_centers(cap, packages, is_bottom=cap_is_bottom)
    if not pad_centers:
        return False

    corners = list(outline.exterior.coords[:-1])

    # Corner proximity check
    for cx, cy in corners:
        corner_region = ShapelyPoint(cx, cy).buffer(corner_tolerance)
        for px, py in pad_centers:
            if corner_region.contains(ShapelyPoint(px, py)):
                return True

    # Diagonal segment check — use cap board centre
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
    """Determine if *cap* is Horizontal or Vertical relative to a shield-can edge.

    Finds the nearest edge segment of the shield-can outline to the
    capacitor's board centre, then compares the capacitor's major axis
    angle to the segment direction.

    Returns:
        ``"Horizontal"`` – cap major axis roughly parallel to segment
        ``"Vertical"``   – cap major axis roughly perpendicular to segment
        ``"Unknown"``    – insufficient geometry data
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

    # Angle difference normalised to [0, 90]
    diff = abs(cap_angle - seg_angle) % 180.0
    if diff > 90.0:
        diff = 180.0 - diff

    if diff < 45.0:
        return "Horizontal"
    return "Vertical"


# ---------------------------------------------------------------------------
# Shield Can Inner Wall Detection
# ---------------------------------------------------------------------------

def _classify_pads_by_boundary(
    pad_centers: list[tuple[float, float]],
    outline_poly,
    boundary_tolerance: float = 0.2,
    *,
    is_convex_hull_fallback: bool = False,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Classify pad centres as boundary or interior pads.

    A pad is *boundary* when it lies within *boundary_tolerance* (mm) of the
    outline polygon exterior ring.  A pad that is inside the polygon but
    farther than the tolerance is *interior* (candidate inner-wall pad).

    When *is_convex_hull_fallback* is True the outline was derived from the
    convex hull of all pads (no package outline available).  In that case a
    stricter threshold (3× *boundary_tolerance*) is used so that pads near
    concave indentations of the real boundary are not misclassified as
    interior.

    Returns ``(boundary_pads, interior_pads)``.
    """
    if not _HAS_SHAPELY:
        return pad_centers[:], []

    effective_tol = boundary_tolerance * 3.0 if is_convex_hull_fallback else boundary_tolerance
    boundary_line = outline_poly.exterior

    boundary_pads: list[tuple[float, float]] = []
    interior_pads: list[tuple[float, float]] = []

    for px, py in pad_centers:
        pt = ShapelyPoint(px, py)
        dist = boundary_line.distance(pt)
        if dist <= effective_tol:
            boundary_pads.append((px, py))
        elif outline_poly.contains(pt):
            interior_pads.append((px, py))
        # else: outside the polygon — ignore

    return boundary_pads, interior_pads


def _cluster_pads_into_walls(
    pads: list[tuple[float, float]],
    max_spacing: float | None = None,
    *,
    min_pads_per_wall: int = 2,
) -> list[list[tuple[float, float]]]:
    """Group interior pads into wall segments via a proximity graph.

    Pads within *max_spacing* (mm) of each other are considered neighbours.
    Connected components of the resulting graph form candidate wall groups.
    Each group with at least *min_pads_per_wall* pads is ordered along its
    principal axis (PCA) so the resulting list traces the wall linearly.

    If *max_spacing* is ``None`` an adaptive threshold is computed as
    ``2.5 × median(nearest-neighbour distances)`` clamped to [0.5, 5.0] mm.

    Returns a list of ordered pad groups.
    """
    n = len(pads)
    if n < min_pads_per_wall:
        return []

    pts = np.array(pads)  # (n, 2)

    # --- pairwise distance matrix ---
    diff = pts[:, np.newaxis, :] - pts[np.newaxis, :, :]  # (n, n, 2)
    dist_matrix = np.sqrt((diff ** 2).sum(axis=2))         # (n, n)

    # --- adaptive spacing ---
    if max_spacing is None:
        np.fill_diagonal(dist_matrix, np.inf)
        nn_dists = dist_matrix.min(axis=1)
        np.fill_diagonal(dist_matrix, 0.0)
        if n >= 3:
            max_spacing = float(np.clip(2.5 * np.median(nn_dists), 0.5, 5.0))
        else:
            max_spacing = 2.0

    # --- build adjacency & BFS ---
    adjacency: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if dist_matrix[i, j] <= max_spacing:
                adjacency[i].append(j)
                adjacency[j].append(i)

    visited = [False] * n
    components: list[list[int]] = []
    for start in range(n):
        if visited[start]:
            continue
        queue = [start]
        visited[start] = True
        comp: list[int] = []
        while queue:
            node = queue.pop(0)
            comp.append(node)
            for nb in adjacency[node]:
                if not visited[nb]:
                    visited[nb] = True
                    queue.append(nb)
        components.append(comp)

    # --- order each component along principal axis ---
    walls: list[list[tuple[float, float]]] = []
    for comp in components:
        if len(comp) < min_pads_per_wall:
            continue
        group = pts[comp]  # (m, 2)
        centroid = group.mean(axis=0)
        centred = group - centroid
        cov = np.cov(centred, rowvar=False)
        eigenvalues, eigenvectors = np.linalg.eigh(cov)
        # Principal axis = eigenvector with largest eigenvalue
        principal = eigenvectors[:, np.argmax(eigenvalues)]
        projections = centred @ principal
        order = np.argsort(projections)
        ordered = [tuple(group[i]) for i in order]
        walls.append(ordered)

    return walls


def detect_inner_walls(
    shield_can: Component,
    packages: list[Package],
    *,
    is_bottom: bool = False,
    boundary_tolerance: float = 0.2,
    max_pad_spacing: float | None = None,
    min_pads_per_wall: int = 2,
):
    """Detect inner wall segments inside a shield can.

    Identifies pads that lie inside the shield-can outline but are not part
    of the outer perimeter, clusters them into linear groups, and returns
    each group as a Shapely ``LineString``.

    Parameters
    ----------
    shield_can : Component
        The shield-can component.
    packages : list[Package]
        All EDA packages (used for outline / pin lookup).
    is_bottom : bool
        Whether the shield can is on the bottom layer.
    boundary_tolerance : float
        Distance (mm) from outline to be considered a boundary pad.
    max_pad_spacing : float | None
        Maximum distance (mm) between adjacent inner-wall pads.  ``None``
        enables adaptive spacing based on pad pitch.
    min_pads_per_wall : int
        Minimum pad count for a cluster to be considered a wall.

    Returns
    -------
    list[LineString]
        Detected inner walls (empty when none found or Shapely unavailable).
    """
    if not _HAS_SHAPELY:
        return []

    outline = _get_shield_can_outline(shield_can, packages, is_bottom=is_bottom)
    if outline is None:
        return []

    # Determine whether the outline came from convex-hull fallback
    is_fallback = _resolve_outline(shield_can, packages, is_bottom=is_bottom) is None

    pad_centers = _get_pad_centers(shield_can, packages, is_bottom=is_bottom)
    if len(pad_centers) < min_pads_per_wall:
        return []

    _boundary, interior = _classify_pads_by_boundary(
        pad_centers, outline, boundary_tolerance,
        is_convex_hull_fallback=is_fallback,
    )

    if len(interior) < min_pads_per_wall:
        return []

    groups = _cluster_pads_into_walls(
        interior, max_pad_spacing, min_pads_per_wall=min_pads_per_wall,
    )

    walls = [LineString(g) for g in groups if len(g) >= 2]
    return walls


def find_nearest_inner_wall(
    point: tuple[float, float],
    inner_walls,
):
    """Return the nearest inner wall to *point* and its distance.

    Parameters
    ----------
    point : tuple[float, float]
        Query point in board coordinates (mm).
    inner_walls : list[LineString]
        Inner walls as returned by :func:`detect_inner_walls`.

    Returns
    -------
    tuple[LineString, float] | None
        ``(nearest_wall, distance)`` or ``None`` when *inner_walls* is empty.
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
    """Check if *comp* is within *distance_threshold* of an inner wall.

    Tests both the component board centre and all of its pad centres.

    Parameters
    ----------
    inner_walls : list[LineString] | None
        Pre-computed inner walls (avoids recomputation when checking
        multiple components against the same shield can).
    """
    if not _HAS_SHAPELY:
        return False

    if inner_walls is None:
        inner_walls = detect_inner_walls(
            shield_can, packages,
            is_bottom=sc_is_bottom,
            boundary_tolerance=boundary_tolerance,
        )
    if not inner_walls:
        return False

    # Check component board centre
    result = find_nearest_inner_wall((comp.x, comp.y), inner_walls)
    if result is not None and result[1] <= distance_threshold:
        return True

    # Check pad centres
    pad_centers = _get_pad_centers(comp, packages, is_bottom=comp_is_bottom)
    for px, py in pad_centers:
        result = find_nearest_inner_wall((px, py), inner_walls)
        if result is not None and result[1] <= distance_threshold:
            return True

    return False


# ---------------------------------------------------------------------------
# Shield Can Fill-Cut Detection
# ---------------------------------------------------------------------------

def _arc_seg_to_pts(
    start: tuple[float, float],
    seg: "ArcSegment",
    resolution: int = 32,
) -> list[tuple[float, float]]:
    """Approximate a single ArcSegment as a polyline (local coords).

    Returns a list of ``resolution`` points that traces the arc from *start*
    to ``seg.end``, including both endpoints.
    """
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
    """Extract fill-cut cap polygon vertices from a CONTOUR outline (local coords).

    A fill-cut is the semicircular end-cap region of an oblong (stadium) pad —
    the area bounded by the arc and the straight chord at its base.

    For a well-formed stadium contour the sequence of segments contains exactly
    two arc segments (one per end cap) separated by straight line segments.
    Each arc's polygon is built by tracing the arc then closing with the chord.

    Returns a list of polygon vertex lists (one per end cap), or an empty list
    if the contour is not a stadium shape (transition count != 4).
    """
    segs = contour.segments
    if not segs:
        return []

    arc_flags: list[bool] = [isinstance(seg, ArcSegment) for seg in segs]

    # Verify exactly 4 arc<->line transitions (stadium shape)
    n = len(segs)
    transitions = sum(1 for i in range(n) if arc_flags[i] != arc_flags[(i + 1) % n])
    if transitions != 4:
        return []

    # Build endpoint sequence: pts[i] is the start point of segs[i]
    pts: list[tuple[float, float]] = [(contour.start.x, contour.start.y)]
    for seg in segs:
        pts.append((seg.end.x, seg.end.y))

    cap_polys: list[list[tuple[float, float]]] = []
    for i, seg in enumerate(segs):
        if not arc_flags[i]:
            continue  # only process arc segments

        arc_start = pts[i]
        arc_pts = _arc_seg_to_pts(arc_start, seg, arc_resolution)

        # Polygon = arc path + implicit chord (Shapely closes back to first pt)
        cap_polys.append(arc_pts)

    return cap_polys


def _extract_fill_cuts_from_rc(
    params: dict,
    min_aspect: float = 1.3,
    arc_resolution: int = 32,
) -> list[list[tuple[float, float]]]:
    """Build fill-cut cap polygon vertices for an RC outline (local coords).

    Treats the rectangle as the bounding box of a stadium pad and constructs
    two semicircular end-cap polygons.  Returns an empty list when the aspect
    ratio is below *min_aspect*.
    """
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
        # Vertical pad: top cap faces +y (angles pi→0), bottom cap faces -y (angles 0→-pi)
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
        # Horizontal pad: right cap faces +x, left cap faces -x
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
    """Return fill-cut cap polygon vertex lists for a single pin (local coords).

    Only elongated (line-like) pads are processed.  Dot-like pads — circular
    (CR/CT), square (SQ), RC with aspect ratio below *min_aspect*, or any pad
    whose long side is shorter than *min_long_side_mm* — are skipped.

    Tries CONTOUR outlines first (exact arc extraction), then falls back to
    RC (bounding-box inference).
    """
    for outline in pin.outlines:
        if outline.type == "CONTOUR" and outline.contour is not None:
            result = _extract_fill_cuts_from_contour(outline.contour, arc_resolution)
            if result:
                # Guard: skip near-zero arcs (degenerate pads)
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

    A fill-cut is the semicircular end-cap area of an oblong (stadium) pad —
    the region that is "cut" from the rectangular fill to produce the rounded
    ends.  Each oblong pin produces two fill-cut polygons (one per end).

    Dot-like pads (CR/CT/SQ, RC with aspect ratio below *min_aspect*, or any
    pad shorter than *min_long_side_mm*) are skipped entirely.

    Detection strategy:

    * **CONTOUR outlines** – the arc segments are extracted directly from the
      contour and traced into a closed polygon (exact, rotation-invariant).
    * **RC outlines** (fallback) – semicircular caps are inferred from the
      bounding-box dimensions.

    Parameters
    ----------
    shield_can : Component
        The shield-can component whose pins are inspected.
    packages : list[Package]
        All EDA packages (used for pin/outline lookup).
    is_bottom : bool
        Whether the component is on the bottom layer.
    min_aspect : float
        Minimum length/width ratio for a pad to be treated as oblong.
    min_long_side_mm : float
        Minimum pad long-side length (mm).  Shorter pads are ignored.
    arc_resolution : int
        Number of points used to approximate each arc (higher = smoother).

    Returns
    -------
    list[ShapelyPolygon]
        One polygon per fill-cut cap region, in board coordinates.
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
