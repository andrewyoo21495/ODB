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

from src.models import BBox, Component, EdaData, Package, PinOutline
from src.visualizer.component_overlay import (
    transform_point,
    transform_pts,
)
from src.visualizer.symbol_renderer import contour_to_vertices

try:
    from shapely.geometry import (
        MultiPoint, Point as ShapelyPoint, Polygon as ShapelyPolygon,
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


def get_component_outline(comp: Component, pkg: Package):
    """Build a board-coordinate polygon from **package-level** outlines only.

    Unlike :func:`get_component_footprint` (which includes pin/pad outlines),
    this returns only the physical component body outline.  Returns a shapely
    Polygon (convex hull of package outline points) or None.
    """
    if not _HAS_SHAPELY:
        return None

    pts: list[tuple[float, float]] = []
    for outline in pkg.outlines:
        local_verts = _outline_vertices(outline)
        for lv in local_verts:
            bx, by = transform_point(lv[0], lv[1], comp)
            pts.append((bx, by))

    if len(pts) >= 3:
        return MultiPoint(pts).convex_hull
    return None


def _resolve_outline(comp: Component, packages: list[Package]):
    """Look up the package and build the component outline polygon."""
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return None
    pkg = packages[comp.pkg_ref]
    return get_component_outline(comp, pkg)


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


# ---------------------------------------------------------------------------
# 6. Opposite-Side Overlap Detection
# ---------------------------------------------------------------------------

def find_overlapping_components(
    comp: Component,
    candidates: Sequence[Component],
    packages: list[Package],
) -> list[Component]:
    """Return *candidates* whose footprints overlap *comp*'s footprint.

    Both *comp* and every candidate are assumed to be on opposite sides of
    the PCB so their 2-D projections are compared directly.
    """
    if not _HAS_SHAPELY:
        return []

    fp_comp = _resolve_footprint(comp, packages)
    if fp_comp is None:
        # Fallback: use a small box around the centre
        fp_comp = ShapelyPoint(comp.x, comp.y).buffer(0.1)

    overlapping: list[Component] = []
    for cand in candidates:
        fp_cand = _resolve_footprint(cand, packages)
        if fp_cand is None:
            fp_cand = ShapelyPoint(cand.x, cand.y).buffer(0.1)
        if fp_comp.intersects(fp_cand):
            overlapping.append(cand)
    return overlapping


def overlaps_component_outline(
    comp: Component,
    target: Component,
    packages: list[Package],
) -> bool:
    """Return True if *comp*'s footprint overlaps *target*'s component outline.

    Unlike :func:`find_overlapping_components` (which checks footprint vs
    footprint), this checks *comp*'s full footprint against only the
    package-level outline of *target* (the physical component body, excluding
    pad geometry).  Returns False if the outline cannot be resolved.
    """
    if not _HAS_SHAPELY:
        return False

    fp_comp = _resolve_footprint(comp, packages)
    outline_target = _resolve_outline(target, packages)

    if fp_comp is None or outline_target is None:
        return False

    return fp_comp.intersects(outline_target)


# ---------------------------------------------------------------------------
# 7. Pad-to-Pad Overlap Detection
# ---------------------------------------------------------------------------

def _get_pad_union(comp: Component, packages: list[Package]):
    """Build a union of all individual pad polygons for *comp*.

    For each pin in the package, the pin outline vertices are transformed to
    board coordinates and turned into a Shapely polygon.  Falls back to a
    small circular buffer around the toeprint position if no outline is found.

    Returns a Shapely geometry (union of all pads) or None.
    """
    if not _HAS_SHAPELY:
        return None
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return None

    pkg = packages[comp.pkg_ref]
    pad_polys = []

    for pin in pkg.pins:
        placed = False
        for outline in pin.outlines:
            verts = _outline_vertices(outline)
            if not verts:
                continue
            board_verts = [transform_point(v[0], v[1], comp) for v in verts]
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
            bx, by = transform_point(pin.center.x, pin.center.y, comp)
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
) -> list[Component]:
    """Return *candidates* whose pads overlap *comp*'s pads.

    Unlike :func:`find_overlapping_components` (which uses the full outline
    convex hull), this function checks pad-level geometry only.  Outline
    overlap is acceptable; pad-to-pad contact is not.
    """
    if not _HAS_SHAPELY:
        return []

    pad_union_comp = _get_pad_union(comp, packages)
    if pad_union_comp is None:
        pad_union_comp = ShapelyPoint(comp.x, comp.y).buffer(0.05)

    overlapping: list[Component] = []
    for cand in candidates:
        pad_union_cand = _get_pad_union(cand, packages)
        if pad_union_cand is None:
            pad_union_cand = ShapelyPoint(cand.x, cand.y).buffer(0.05)
        if pad_union_comp.intersects(pad_union_cand):
            overlapping.append(cand)
    return overlapping


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
                            packages: list[Package] | None = None) -> float:
    """Return the minimum distance from *comp*'s pad geometry to the board outline.

    Uses actual pad polygons (via ``_get_pad_union``) rather than just pad
    centre points.  Falls back to toeprint points, then component centre.
    """
    if not _HAS_SHAPELY or board_poly is None:
        return float("inf")

    outline = board_poly.boundary

    if packages is not None:
        pad_geom = _get_pad_union(comp, packages)
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
                              packages: list[Package]) -> float:
    """Return the minimum distance from *comp*'s pads to *other*'s footprint.

    Measures from the actual pad polygons of *comp* to the footprint polygon
    of *other*.  Falls back to ``edge_distance`` if geometry is unavailable.
    """
    if not _HAS_SHAPELY:
        return center_distance(comp, other)

    pad_geom = _get_pad_union(comp, packages)
    fp_other = _resolve_footprint(other, packages)

    if pad_geom is None or fp_other is None:
        return float("inf")

    return pad_geom.distance(fp_other)


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


# ---------------------------------------------------------------------------
# 10. VIA-on-Pad Detection
# ---------------------------------------------------------------------------

def _build_via_positions_by_attribute(
    layers_data: dict,
) -> set[tuple[float, float]]:
    """Return VIA (x, y) positions using the ``.pad_usage`` feature attribute.

    Scans only the top and bottom signal layers.  A pad whose ``.pad_usage``
    raw value is 1 is considered a via (raw value 0 = toeprint).
    """
    from src.models import PadRecord
    from src.visualizer.fid_lookup import _find_top_bottom_signal_layers

    top_name, bot_name = _find_top_bottom_signal_layers(layers_data)
    if top_name is None:
        return set()

    target_names = {top_name, bot_name}
    positions: set[tuple[float, float]] = set()

    for layer_name in target_names:
        ld = layers_data.get(layer_name)
        if ld is None:
            continue
        lf = ld[0]
        via_text = lf.attr_texts.get(1)

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
) -> set[tuple[float, float]]:
    """Return VIA (x, y) positions via EDA subnet FID resolution (fallback)."""
    from src.models import PadRecord

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
                if layer_name is None:
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
) -> set[tuple[float, float]]:
    """Return deduplicated (x, y) board positions of all VIAs.

    Prefers the ``.pad_usage`` feature attribute on the top/bottom signal
    layers (raw value 1 = via).  Falls back to EDA subnet FID resolution
    when the attribute yields no results.

    Positions are rounded to 4 decimal places (0.1 µm in mm) for
    deduplication.
    """
    positions = _build_via_positions_by_attribute(layers_data)
    if not positions:
        positions = _build_via_positions_by_subnet(eda_data, layers_data)
    return positions


def count_vias_at_pad(
    comp: Component,
    pin_center_x: float,
    pin_center_y: float,
    via_positions: set[tuple[float, float]],
    is_bottom: bool = False,
    tolerance: float = 0.05,
) -> int:
    """Count VIAs located at a component pad position.

    Transforms the pin centre from package-local coordinates to board
    coordinates, then counts VIA positions within *tolerance* mm.

    Args:
        comp: The component owning the pad.
        pin_center_x: Pin centre X in package-local coords.
        pin_center_y: Pin centre Y in package-local coords.
        via_positions: Set of (x, y) VIA board positions.
        is_bottom: Whether the component is on the bottom layer.
        tolerance: Maximum distance (mm) to consider a VIA on the pad.
    """
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
