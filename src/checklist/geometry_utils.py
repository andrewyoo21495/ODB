"""Shared geometry utilities for checklist rules.

Provides functions for:
- Component orientation detection (Horizontal / Vertical)
- Component footprint polygon construction from pin outlines
- Edge detection between components
- Distance measurement (center-to-center and edge-to-edge)
- CSV component list loading and filtering

All coordinate data is expected to be pre-normalised to MM.
"""

from __future__ import annotations

import csv
import math
from typing import Optional

import numpy as np

from src.models import BBox, Component, Package, PinOutline
from src.visualizer.component_overlay import (
    transform_point,
    transform_pts,
)
from src.visualizer.symbol_renderer import contour_to_vertices

try:
    from shapely.geometry import MultiPoint, Point as ShapelyPoint, Polygon as ShapelyPolygon
    from shapely.ops import unary_union
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False


# ---------------------------------------------------------------------------
# 1. Component Orientation
# ---------------------------------------------------------------------------

def get_component_orientation(comp: Component,
                              packages: list[Package]) -> str:
    """Determine a component's board-level orientation from its package bbox.

    Returns:
        "Horizontal" – major axis is roughly along the board X-axis
        "Vertical"   – major axis is roughly along the board Y-axis
        "Square"     – aspect ratio is near 1:1
        "Unknown"    – no bbox data available
    """
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return "Unknown"

    pkg = packages[comp.pkg_ref]
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


def get_component_footprint(comp: Component, pkg: Package):
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
                bx, by = transform_point(lv[0], lv[1], comp)
                all_points.append((bx, by))

    # Collect from package-level outlines
    for outline in pkg.outlines:
        local_verts = _outline_vertices(outline)
        for lv in local_verts:
            bx, by = transform_point(lv[0], lv[1], comp)
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


def _resolve_footprint(comp: Component, packages: list[Package]):
    """Look up the package and build the footprint polygon."""
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return None
    pkg = packages[comp.pkg_ref]
    return get_component_footprint(comp, pkg)


# ---------------------------------------------------------------------------
# 3. Edge Detection
# ---------------------------------------------------------------------------

def is_on_edge(comp_a: Component, comp_b: Component,
               packages: list[Package],
               tolerance: float = 0.254) -> bool:
    """Return True if comp_a's footprint is near the boundary of comp_b's footprint.

    "On the edge" means the minimum distance between the two footprint
    boundaries is less than *tolerance*, but comp_a is NOT fully contained
    inside comp_b.

    Args:
        tolerance: Maximum distance in mm to consider "on edge".
    """
    if not _HAS_SHAPELY:
        return False

    fp_a = _resolve_footprint(comp_a, packages)
    fp_b = _resolve_footprint(comp_b, packages)

    if fp_a is None or fp_b is None:
        return False

    boundary_dist = fp_a.boundary.distance(fp_b.boundary)
    fully_inside = fp_b.contains(fp_a)

    return boundary_dist < tolerance and not fully_inside


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
