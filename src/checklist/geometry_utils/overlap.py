"""Opposite-side overlap detection and pad geometry utilities.

Provides:
- find_overlapping_components          — footprint vs footprint overlap
- overlaps_component_outline           — footprint vs outline overlap
- is_sandwiched_between                — sandwich zone detection
- find_outermost_pin_indices           — perimeter pin indices
- find_outermost_pad_overlapping_components
- _symbol_to_shapely / _user_symbol_to_shapely — pad → Shapely geometry
- _get_pad_union / _get_outermost_pad_union    — pad geometry union
- find_pad_overlapping_components
- find_components_inside_outline
- has_empty_center / find_empty_center_ics     — empty-centre IC detection
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from src.models import (
    ArcRecord, Component, LineRecord, Package, PadRecord, Pin,
    SurfaceRecord, UserSymbol,
)
from src.visualizer.component_overlay import transform_point
from src.visualizer.symbol_renderer import (
    arc_to_points,
    contour_to_vertices,
    get_line_width_for_symbol,
)
from src.parsers.symbol_resolver import resolve_symbol
from .polygon import (
    _get_pad_centers,
    _outline_to_shapely,
    _outline_vertices,
    _resolve_footprint,
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
# Opposite-side overlap detection
# ---------------------------------------------------------------------------

def find_overlapping_components(
    comp: Component,
    candidates: Sequence[Component],
    packages: list[Package],
    *,
    is_bottom_primary: bool = False,
    is_bottom_candidates: bool = False,
) -> list[Component]:
    """Return candidates whose footprints overlap comp's footprint."""
    if not _HAS_SHAPELY:
        return []

    fp_comp = _resolve_footprint(comp, packages, is_bottom=is_bottom_primary)
    if fp_comp is None:
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
    """Return True if comp's footprint overlaps target's component outline."""
    if not _HAS_SHAPELY:
        return False

    fp_comp = _resolve_footprint(comp, packages, is_bottom=is_bottom_comp)
    outline_target = _resolve_outline(target, packages, is_bottom=is_bottom_target)

    if fp_comp is None or outline_target is None:
        return False

    return fp_comp.intersects(outline_target)


def is_sandwiched_between(
    cap: Component,
    am_a: Component,
    am_b: Component,
    packages: list[Package],
    *,
    is_bottom_cap: bool = False,
    is_bottom_am: bool = False,
) -> bool:
    """Return True if cap is sandwiched between am_a and am_b.

    With Shapely: the corridor is convex_hull(am_a ∪ am_b) − (am_a ∪ am_b).
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
# Outermost pin detection
# ---------------------------------------------------------------------------

def find_outermost_pin_indices(pins: list[Pin]) -> set[int]:
    """Return indices of pins on the outer perimeter of the pad array.

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

    if x_min == x_max and y_min == y_max:
        return set(range(len(pins)))

    tol = 0.01  # mm

    outermost: set[int] = set()
    for idx, (cx, cy) in enumerate(centres):
        if (cx <= x_min + tol or cx >= x_max - tol or
                cy <= y_min + tol or cy >= y_max - tol):
            outermost.add(idx)

    return outermost


# ---------------------------------------------------------------------------
# Symbol → Shapely geometry helpers
# ---------------------------------------------------------------------------

def _mm_scale(units: str, unit_override: str | None) -> float:
    """Return the scale factor converting symbol params to MM."""
    if unit_override == "I":
        return 0.0254
    if unit_override == "M":
        return 0.001
    if units == "INCH":
        return 0.0254
    return 0.001


def _rot_pts(pts: np.ndarray, cx: float, cy: float, angle_deg: float) -> np.ndarray:
    """Rotate pts (N×2) clockwise by angle_deg around (cx, cy)."""
    a = math.radians(-angle_deg)
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
    """Convert a standard symbol name to a Shapely geometry at board position."""
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
        # Ellipse approximation falls back to circular buffer
        return ShapelyPoint(x, y).buffer(0.025)

    if sym.type == "diamond":
        w = sym.params["width"] * scale / 2
        h = sym.params["height"] * scale / 2
        verts = np.array([[x, y + h], [x + w, y], [x, y - h], [x - w, y]])
        verts = _apply_transform(verts)
        try:
            return ShapelyPolygon(verts)
        except Exception:
            return ShapelyPoint(x, y).buffer(max(w, h))

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
    """Convert a UserSymbol to a Shapely geometry union at board position (x, y)."""
    if not _HAS_SHAPELY:
        return None

    geoms = []
    sym_lookup = {s.index: s for s in symbol.symbols}

    def _local_to_board(pts: np.ndarray) -> np.ndarray:
        out = np.asarray(pts, dtype=float).copy()
        if mirror:
            out[:, 0] = -out[:, 0]
        if rotation:
            a = math.radians(-rotation)
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


# ---------------------------------------------------------------------------
# Pad union construction
# ---------------------------------------------------------------------------

def _get_pad_union(comp: Component, packages: list[Package],
                   *, is_bottom: bool = False, user_symbols: dict | None = None):
    """Build a union of all individual pad polygons for comp.

    Primary path: FID-resolved Toeprint.geom data.
    Fallback: package-level pin outline definitions (EDA data).
    Returns a Shapely geometry or None.
    """
    if not _HAS_SHAPELY:
        return None
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return None

    user_symbols = user_symbols or {}

    tp_geom_polys = []
    for tp in comp.toeprints:
        if tp.geom is None:
            continue
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
            tp_geom_polys.append(g)

    if tp_geom_polys:
        return unary_union(tp_geom_polys)

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

    if not pad_polys:
        for tp in comp.toeprints:
            pad_polys.append(ShapelyPoint(tp.x, tp.y).buffer(0.05))

    if not pad_polys:
        return None

    return unary_union(pad_polys)


def _get_outermost_pad_union(comp: Component, packages: list[Package],
                             *, is_bottom: bool = False,
                             user_symbols: dict | None = None):
    """Build a union of only the outermost pad polygons for comp."""
    if not _HAS_SHAPELY:
        return None
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return None

    user_symbols = user_symbols or {}

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


# ---------------------------------------------------------------------------
# Pad-level overlap detection
# ---------------------------------------------------------------------------

def find_outermost_pad_overlapping_components(
    comp: Component,
    candidates: Sequence[Component],
    packages: list[Package],
    *,
    is_bottom_primary: bool = False,
    is_bottom_candidates: bool = False,
    user_symbols: dict | None = None,
) -> list[Component]:
    """Return candidates whose outermost pads overlap comp's pads."""
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


def find_pad_overlapping_components(
    comp: Component,
    candidates: Sequence[Component],
    packages: list[Package],
    *,
    is_bottom_primary: bool = False,
    is_bottom_candidates: bool = False,
    user_symbols: dict | None = None,
) -> list[Component]:
    """Return candidates whose pads overlap comp's pads."""
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
    """Return candidates whose footprint is inside comp's component outline."""
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
# Empty-centre pad layout detection
# ---------------------------------------------------------------------------

def _median_spacing(values: list[float]) -> float:
    """Return the median gap between consecutive sorted unique values."""
    unique = sorted(set(values))
    if len(unique) < 2:
        return 0.0
    gaps = [unique[i + 1] - unique[i] for i in range(len(unique) - 1)]
    gaps.sort()
    return gaps[len(gaps) // 2]


def has_empty_center(comp: Component, packages: list[Package]) -> bool:
    """Return True if the IC's internal pad grid has no pads in the interior.

    Returns False when the package has fewer than 9 pins or pitch cannot
    be determined.
    """
    if comp.pkg_ref < 0 or comp.pkg_ref >= len(packages):
        return False

    pkg = packages[comp.pkg_ref]
    if len(pkg.pins) < 9:
        return False

    xs = [pin.center.x for pin in pkg.pins]
    ys = [pin.center.y for pin in pkg.pins]

    pitch_x = _median_spacing(xs)
    pitch_y = _median_spacing(ys)
    if pitch_x <= 0 or pitch_y <= 0:
        return False

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    eps = 0.25 * min(pitch_x, pitch_y)
    margin_x = 2.0 * pitch_x - eps
    margin_y = 2.0 * pitch_y - eps
    inner_min_x = min_x + margin_x
    inner_max_x = max_x - margin_x
    inner_min_y = min_y + margin_y
    inner_max_y = max_y - margin_y

    if inner_min_x >= inner_max_x or inner_min_y >= inner_max_y:
        return False

    for px, py in zip(xs, ys):
        if inner_min_x <= px <= inner_max_x and inner_min_y <= py <= inner_max_y:
            return False

    return True


def find_empty_center_ics(
    components: Sequence[Component],
    packages: list[Package],
) -> list[Component]:
    """Return IC components whose pad layout has an empty interior."""
    from src.checklist.component_classifier import find_ics
    return [c for c in find_ics(components) if has_empty_center(c, packages)]
