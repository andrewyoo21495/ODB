"""Vector-based copper ratio calculation using Shapely.

Computes copper fill ratios directly from ODB++ feature geometry
without rasterization.  Every feature (line, pad, arc, surface) is
converted to a Shapely polygon and combined with boolean operations
that respect the ODB++ polarity rules (P = add copper, N = remove).

Advantages over the raster approach (copper_utils.py):
- Mathematically exact — no resolution-dependent pixel counting
- Fine traces are never "merged" by limited pixel density
- Sub-section ratios come from cheap polygon intersection, not
  re-rendering

Public API mirrors copper_utils so callers can switch methods easily.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
from shapely.geometry import (
    LinearRing, LineString, MultiPolygon, Point, Polygon, box,
)
from shapely.ops import unary_union
from shapely import affinity

from src.models import (
    ArcRecord, BarcodeRecord, Contour, ArcSegment, FeaturePolarity,
    LayerFeatures, LineRecord, LineSegment, MatrixLayer, PadRecord,
    Profile, StrokeFont, SurfaceRecord, SymbolRef, TextRecord, UserSymbol,
)
from src.parsers.symbol_resolver import resolve_symbol
from src.visualizer.symbol_renderer import contour_to_vertices


# ---------------------------------------------------------------------------
# Unit conversion  (mirrors symbol_renderer._get_scale_factor)
# ---------------------------------------------------------------------------

def _scale(units: str, unit_override: str = None) -> float:
    """Symbol sub-unit → mm conversion factor."""
    if unit_override == "I":
        return 0.0254
    if unit_override == "M":
        return 1.0 / 1000.0
    return 0.0254 if units == "INCH" else 1.0 / 1000.0


# ---------------------------------------------------------------------------
# Arc interpolation  (same algorithm as symbol_renderer._arc_to_points)
# ---------------------------------------------------------------------------

def _arc_points(xs, ys, xe, ye, xc, yc, clockwise, n=32):
    """Interpolate an arc into a list of (x, y) tuples."""
    r = math.hypot(xs - xc, ys - yc)
    if r < 1e-10:
        return [(xe, ye)]
    sa = math.atan2(ys - yc, xs - xc)
    ea = math.atan2(ye - yc, xe - xc)
    if clockwise:
        if ea >= sa:
            ea -= 2 * math.pi
    else:
        if ea <= sa:
            ea += 2 * math.pi
    # Full circle when start == end
    if abs(xs - xe) < 1e-10 and abs(ys - ye) < 1e-10:
        ea = sa + (-2 * math.pi if clockwise else 2 * math.pi)
    angles = [sa + (ea - sa) * i / (n - 1) for i in range(n)]
    pts = [(xc + r * math.cos(a), yc + r * math.sin(a)) for a in angles]
    pts[-1] = (xe, ye)
    return pts


# ---------------------------------------------------------------------------
# Contour → Shapely ring
# ---------------------------------------------------------------------------

def _contour_to_coords(contour: Contour, n_arc: int = 32) -> list[tuple]:
    """Convert an ODB++ Contour to a coordinate list (closed ring)."""
    pts = [(contour.start.x, contour.start.y)]
    for seg in contour.segments:
        if isinstance(seg, LineSegment):
            pts.append((seg.end.x, seg.end.y))
        elif isinstance(seg, ArcSegment):
            arc = _arc_points(
                pts[-1][0], pts[-1][1],
                seg.end.x, seg.end.y,
                seg.center.x, seg.center.y,
                seg.clockwise, n_arc,
            )
            pts.extend(arc[1:])
    # Ensure closed
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts


# ---------------------------------------------------------------------------
# Symbol → Shapely polygon
# ---------------------------------------------------------------------------

def _rotate_poly(poly, cx, cy, angle_deg):
    """Rotate a Shapely geometry CW by *angle_deg* around (cx, cy)."""
    if not angle_deg:
        return poly
    return affinity.rotate(poly, -angle_deg, origin=(cx, cy))


def _mirror_poly(poly, cx):
    """Mirror a Shapely geometry in X around *cx*."""
    return affinity.affine_transform(poly, [-1, 0, 0, 1, 2 * cx, 0])


def _circle_poly(cx, cy, r, n=64):
    """Create a circular polygon with *n* segments."""
    return Point(cx, cy).buffer(r, resolution=n // 4)


def _oval_poly(cx, cy, w, h, n=64):
    """Oval (stadium / discorectangle) centred at (cx, cy)."""
    if w >= h:
        r = h / 2
        line = LineString([(cx - w / 2 + r, cy), (cx + w / 2 - r, cy)])
    else:
        r = w / 2
        line = LineString([(cx, cy - h / 2 + r), (cx, cy + h / 2 - r)])
    return line.buffer(r, resolution=n // 4)


def _symbol_to_poly(
    sym_name: str,
    cx: float, cy: float,
    rotation: float, mirror: bool,
    units: str, unit_override: str,
    resize_factor: float = None,
) -> Optional[Polygon | MultiPolygon]:
    """Convert a standard or simple symbol to a Shapely polygon."""
    sym = resolve_symbol(sym_name)
    sc = _scale(units, unit_override)
    if resize_factor is not None:
        sc *= resize_factor

    poly = None

    if sym.type == "round":
        r = sym.params["diameter"] * sc / 2
        poly = _circle_poly(cx, cy, r)

    elif sym.type == "square":
        s = sym.params["side"] * sc
        poly = box(cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2)

    elif sym.type in ("rect", "rect_round", "rect_chamfer"):
        w = sym.params["width"] * sc
        h = sym.params["height"] * sc
        if sym.type == "rect_round":
            cr = sym.params.get("corner_radius", 0) * sc
            if cr > 0:
                inner = box(cx - w / 2 + cr, cy - h / 2, cx + w / 2 - cr, cy + h / 2)
                outer = box(cx - w / 2, cy - h / 2 + cr, cx + w / 2, cy + h / 2 - cr)
                poly = inner.union(outer)
                # Add quarter-circles at corners
                for sx, sy in [(1, 1), (-1, 1), (-1, -1), (1, -1)]:
                    corner_cx = cx + sx * (w / 2 - cr)
                    corner_cy = cy + sy * (h / 2 - cr)
                    poly = poly.union(Point(corner_cx, corner_cy).buffer(cr, resolution=8))
            else:
                poly = box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        else:
            poly = box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

    elif sym.type == "oval":
        w = sym.params["width"] * sc
        h = sym.params["height"] * sc
        poly = _oval_poly(cx, cy, w, h)

    elif sym.type == "ellipse":
        w = sym.params["width"] * sc
        h = sym.params["height"] * sc
        # Approximate ellipse as a buffered point scaled
        circle = Point(0, 0).buffer(1.0, resolution=16)
        poly = affinity.scale(circle, w / 2, h / 2, origin=(0, 0))
        poly = affinity.translate(poly, cx, cy)

    elif sym.type == "diamond":
        w = sym.params["width"] * sc / 2
        h = sym.params["height"] * sc / 2
        poly = Polygon([(cx, cy + h), (cx + w, cy), (cx, cy - h), (cx - w, cy)])

    elif sym.type == "octagon":
        w = sym.params["width"] * sc
        h = sym.params["height"] * sc
        r = sym.params["corner_size"] * sc
        hw, hh = w / 2, h / 2
        poly = Polygon([
            (cx - hw + r, cy + hh), (cx + hw - r, cy + hh),
            (cx + hw, cy + hh - r), (cx + hw, cy - hh + r),
            (cx + hw - r, cy - hh), (cx - hw + r, cy - hh),
            (cx - hw, cy - hh + r), (cx - hw, cy + hh - r),
        ])

    elif sym.type == "triangle":
        base = sym.params["base"] * sc
        h = sym.params["height"] * sc
        poly = Polygon([
            (cx - base / 2, cy - h / 2),
            (cx + base / 2, cy - h / 2),
            (cx, cy + h / 2),
        ])

    elif sym.type in ("hex_l", "hex_s"):
        w = sym.params["width"] * sc
        h = sym.params["height"] * sc
        r = sym.params["corner_size"] * sc
        hw, hh = w / 2, h / 2
        if sym.type == "hex_l":
            poly = Polygon([
                (cx - hw, cy), (cx - hw + r, cy + hh),
                (cx + hw - r, cy + hh), (cx + hw, cy),
                (cx + hw - r, cy - hh), (cx - hw + r, cy - hh),
            ])
        else:
            poly = Polygon([
                (cx - hw, cy + hh - r), (cx - hw, cy - hh + r),
                (cx, cy - hh), (cx + hw, cy - hh + r),
                (cx + hw, cy + hh - r), (cx, cy + hh),
            ])

    elif sym.type == "half_oval":
        w = sym.params["width"] * sc
        h = sym.params["height"] * sc
        # Bottom rectangle + top semicircle
        rect = box(cx - w / 2, cy - h / 2, cx + w / 2, cy)
        semi = Point(cx, cy).buffer(w / 2, resolution=16)
        clip = box(cx - w / 2, cy, cx + w / 2, cy + h)
        poly = rect.union(semi.intersection(clip))

    elif sym.type == "donut_r":
        od = sym.params["outer_diameter"] * sc
        id_ = sym.params["inner_diameter"] * sc
        outer = _circle_poly(cx, cy, od / 2)
        inner = _circle_poly(cx, cy, id_ / 2)
        poly = outer.difference(inner)

    elif sym.type == "donut_s":
        od = sym.params["outer_size"] * sc
        id_ = sym.params["inner_size"] * sc
        outer = box(cx - od / 2, cy - od / 2, cx + od / 2, cy + od / 2)
        inner = box(cx - id_ / 2, cy - id_ / 2, cx + id_ / 2, cy + id_ / 2)
        poly = outer.difference(inner)

    elif sym.type == "donut_sr":
        od = sym.params["outer_size"] * sc
        id_ = sym.params["inner_diameter"] * sc
        outer = box(cx - od / 2, cy - od / 2, cx + od / 2, cy + od / 2)
        inner = _circle_poly(cx, cy, id_ / 2)
        poly = outer.difference(inner)

    elif sym.type == "donut_rc":
        ow = sym.params["outer_width"] * sc
        oh = sym.params["outer_height"] * sc
        lw = sym.params["line_width"] * sc
        outer = box(cx - ow / 2, cy - oh / 2, cx + ow / 2, cy + oh / 2)
        inner = box(cx - ow / 2 + lw, cy - oh / 2 + lw,
                    cx + ow / 2 - lw, cy + oh / 2 - lw)
        poly = outer.difference(inner)

    elif sym.type == "donut_o":
        ow = sym.params["outer_width"] * sc
        oh = sym.params["outer_height"] * sc
        lw = sym.params["line_width"] * sc
        outer = _oval_poly(cx, cy, ow, oh)
        inner = _oval_poly(cx, cy, ow - 2 * lw, oh - 2 * lw)
        poly = outer.difference(inner)

    # -- Thermals: annular ring with spoke gaps removed ---
    elif sym.type in ("ths", "thr"):
        od = sym.params["outer_diameter"] * sc
        id_ = sym.params["inner_diameter"] * sc
        gap = sym.params["gap"] * sc
        n_spokes = sym.params.get("num_spokes", 4)
        angle = sym.params.get("angle", 0)
        ring = _circle_poly(cx, cy, od / 2).difference(
            _circle_poly(cx, cy, id_ / 2))
        poly = _cut_thermal_gaps(ring, cx, cy, od, gap, n_spokes, angle)

    elif sym.type in ("s_ths", "s_tho", "s_thr"):
        os_ = sym.params["outer_size"] * sc
        is_ = sym.params["inner_size"] * sc
        gap = sym.params["gap"] * sc
        n_spokes = sym.params.get("num_spokes", 4)
        angle = sym.params.get("angle", 0)
        outer = box(cx - os_ / 2, cy - os_ / 2, cx + os_ / 2, cy + os_ / 2)
        inner = box(cx - is_ / 2, cy - is_ / 2, cx + is_ / 2, cy + is_ / 2)
        ring = outer.difference(inner)
        poly = _cut_thermal_gaps(ring, cx, cy, os_, gap, n_spokes, angle)

    elif sym.type == "sr_ths":
        os_ = sym.params["outer_size"] * sc
        id_ = sym.params["inner_diameter"] * sc
        gap = sym.params["gap"] * sc
        n_spokes = sym.params.get("num_spokes", 4)
        angle = sym.params.get("angle", 0)
        outer = box(cx - os_ / 2, cy - os_ / 2, cx + os_ / 2, cy + os_ / 2)
        inner = _circle_poly(cx, cy, id_ / 2)
        ring = outer.difference(inner)
        poly = _cut_thermal_gaps(ring, cx, cy, os_, gap, n_spokes, angle)

    elif sym.type in ("rc_ths", "rc_tho", "rc_ths_round"):
        rw = sym.params["width"] * sc
        rh = sym.params["height"] * sc
        gap = sym.params["gap"] * sc
        ag = sym.params.get("air_gap", gap) * sc
        n_spokes = sym.params.get("num_spokes", 4)
        angle = sym.params.get("angle", 0)
        outer = box(cx - rw / 2, cy - rh / 2, cx + rw / 2, cy + rh / 2)
        inner = box(cx - rw / 2 + ag, cy - rh / 2 + ag,
                    cx + rw / 2 - ag, cy + rh / 2 - ag)
        ring = outer.difference(inner)
        poly = _cut_thermal_gaps(ring, cx, cy, max(rw, rh), gap, n_spokes, angle)

    elif sym.type in ("o_ths", "oblong_ths"):
        ow = sym.params["outer_width"] * sc
        oh = sym.params["outer_height"] * sc
        lw = sym.params.get("line_width", sym.params.get("gap", 0)) * sc
        gap = sym.params["gap"] * sc
        n_spokes = sym.params.get("num_spokes", 4)
        angle = sym.params.get("angle", 0)
        outer = _oval_poly(cx, cy, ow, oh)
        inner = _oval_poly(cx, cy, ow - 2 * lw, oh - 2 * lw)
        ring = outer.difference(inner)
        poly = _cut_thermal_gaps(ring, cx, cy, max(ow, oh), gap, n_spokes, angle)

    elif sym.type == "hole":
        r = sym.params["diameter"] * sc / 2
        poly = _circle_poly(cx, cy, r)

    elif sym.type == "null":
        return None

    # Fallback: bounding-box approximation for unsupported complex symbols
    if poly is None:
        w = sym.width * sc
        h = sym.height * sc
        if w > 0 and h > 0:
            poly = box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        else:
            return None

    # Apply mirror then rotation
    if mirror:
        poly = _mirror_poly(poly, cx)
    if rotation:
        poly = _rotate_poly(poly, cx, cy, rotation)

    return poly


def _cut_thermal_gaps(ring, cx, cy, size, gap, n_spokes, angle_offset):
    """Remove spoke gaps from a thermal ring."""
    half_gap = gap / 2
    extent = size  # gap rectangles extend beyond the ring
    for i in range(n_spokes):
        a = math.radians(angle_offset + i * 360.0 / n_spokes)
        cos_a, sin_a = math.cos(a), math.sin(a)
        # Build a rectangle aligned with the spoke direction, then rotate
        gap_rect = box(-half_gap, 0, half_gap, extent)
        gap_rect = affinity.rotate(gap_rect, -math.degrees(a) + 90,
                                   origin=(0, 0))
        gap_rect = affinity.translate(gap_rect, cx, cy)
        ring = ring.difference(gap_rect)
    return ring


# ---------------------------------------------------------------------------
# User-defined symbol → Shapely
# ---------------------------------------------------------------------------

def _user_symbol_to_poly(
    symbol: UserSymbol,
    cx: float, cy: float,
    rotation: float, mirror: bool,
) -> Optional[Polygon | MultiPolygon]:
    """Convert a user-defined symbol (composed of sub-features) to Shapely."""
    polys = []
    for feature in symbol.features:
        if isinstance(feature, SurfaceRecord):
            p = _surface_to_poly(feature)
            if p is not None and not p.is_empty:
                polys.append(p)
    if not polys:
        return None
    combined = unary_union(polys)
    if mirror:
        combined = affinity.affine_transform(combined, [-1, 0, 0, 1, 0, 0])
    if rotation:
        combined = affinity.rotate(combined, -rotation, origin=(0, 0))
    combined = affinity.translate(combined, cx, cy)
    return combined


# ---------------------------------------------------------------------------
# Surface → Shapely (island/hole grouping)
# ---------------------------------------------------------------------------

def _surface_to_poly(surface: SurfaceRecord) -> Optional[Polygon | MultiPolygon]:
    """Convert a SurfaceRecord (contour groups) to a Shapely polygon."""
    groups: list[tuple[list, list[list]]] = []
    for contour in surface.contours:
        coords = _contour_to_coords(contour)
        if len(coords) < 4:  # need at least 3 unique + closing
            continue
        if contour.is_island:
            groups.append((coords, []))
        else:
            if groups:
                groups[-1][1].append(coords)

    polygons = []
    for exterior, holes in groups:
        try:
            p = Polygon(exterior, holes)
            if p.is_valid and not p.is_empty:
                polygons.append(p)
            else:
                # Try to fix invalid geometry
                p = p.buffer(0)
                if not p.is_empty:
                    polygons.append(p)
        except Exception:
            continue

    if not polygons:
        return None
    return unary_union(polygons)


# ---------------------------------------------------------------------------
# PCB outline → Shapely
# ---------------------------------------------------------------------------

def _profile_to_poly(profile: Profile) -> Optional[Polygon | MultiPolygon]:
    """Convert the board profile to a Shapely polygon."""
    if not profile or not profile.surface:
        return None
    groups: list[tuple[list, list[list]]] = []
    for contour in profile.surface.contours:
        coords = _contour_to_coords(contour)
        if len(coords) < 4:
            continue
        if contour.is_island:
            groups.append((coords, []))
        else:
            if groups:
                groups[-1][1].append(coords)
    polys = []
    for ext, holes in groups:
        try:
            p = Polygon(ext, holes)
            if not p.is_valid:
                p = p.buffer(0)
            if not p.is_empty:
                polys.append(p)
        except Exception:
            continue
    if not polys:
        return None
    return unary_union(polys)


# ---------------------------------------------------------------------------
# Full layer → copper polygon
# ---------------------------------------------------------------------------

def _build_copper_geometry(
    features: LayerFeatures,
    user_symbols: dict[str, UserSymbol],
) -> Optional[Polygon | MultiPolygon]:
    """Convert all features on a layer into a single copper geometry.

    Processes features in order, applying union for positive polarity
    and difference for negative polarity, matching the ODB++ paint model.
    """
    sym_lookup = {s.index: s for s in features.symbols}

    # Accumulate pending positive polys, flush on polarity change
    copper = None
    pending_pos: list = []

    def _flush_positive():
        nonlocal copper, pending_pos
        if not pending_pos:
            return
        batch = unary_union(pending_pos)
        pending_pos = []
        if copper is None:
            copper = batch
        else:
            copper = copper.union(batch)

    for feat in features.features:
        poly = _feature_to_poly(feat, sym_lookup, features.units, user_symbols)
        if poly is None or poly.is_empty:
            continue

        polarity = getattr(feat, "polarity", FeaturePolarity.P)
        if polarity == FeaturePolarity.P:
            pending_pos.append(poly)
            # Batch flush every 500 features for memory management
            if len(pending_pos) >= 500:
                _flush_positive()
        else:
            # Flush pending positives first, then subtract
            _flush_positive()
            if copper is not None:
                copper = copper.difference(poly)

    _flush_positive()
    return copper


def _feature_to_poly(
    feature,
    sym_lookup: dict[int, SymbolRef],
    units: str,
    user_symbols: dict[str, UserSymbol],
) -> Optional[Polygon | MultiPolygon]:
    """Convert a single feature record to a Shapely polygon."""

    if isinstance(feature, PadRecord):
        sym_ref = sym_lookup.get(feature.symbol_idx)
        if not sym_ref:
            return None
        # User-defined symbol?
        if user_symbols and sym_ref.name in user_symbols:
            return _user_symbol_to_poly(
                user_symbols[sym_ref.name],
                feature.x, feature.y,
                feature.rotation, feature.mirror,
            )
        return _symbol_to_poly(
            sym_ref.name, feature.x, feature.y,
            feature.rotation, feature.mirror,
            units, sym_ref.unit_override,
            feature.resize_factor,
        )

    elif isinstance(feature, LineRecord):
        sym_ref = sym_lookup.get(feature.symbol_idx)
        width = 0.001
        if sym_ref:
            sym = resolve_symbol(sym_ref.name)
            sc = _scale(units, sym_ref.unit_override)
            if sym.type == "round":
                width = sym.params.get("diameter", 0) * sc
            elif sym.type == "square":
                width = sym.params.get("side", 0) * sc
            elif sym.type in ("rect", "rect_round", "rect_chamfer", "oval"):
                width = min(sym.params.get("width", 0),
                            sym.params.get("height", 0)) * sc
            else:
                width = max(sym.width, sym.height) * sc if sym.width > 0 else 0.001
        if width <= 0:
            width = 0.001
        line = LineString([(feature.xs, feature.ys), (feature.xe, feature.ye)])
        if line.length < 1e-10:
            return Point(feature.xs, feature.ys).buffer(width / 2, resolution=8)
        # Round cap style for standard round aperture
        cap = "round"
        if sym_ref:
            sym = resolve_symbol(sym_ref.name)
            if sym.type == "square":
                cap = "flat"
        return line.buffer(width / 2, cap_style=cap, resolution=8)

    elif isinstance(feature, ArcRecord):
        sym_ref = sym_lookup.get(feature.symbol_idx)
        width = 0.001
        if sym_ref:
            sym = resolve_symbol(sym_ref.name)
            sc = _scale(units, sym_ref.unit_override)
            if sym.type == "round":
                width = sym.params.get("diameter", 0) * sc
            elif sym.type == "square":
                width = sym.params.get("side", 0) * sc
            else:
                width = max(sym.width, sym.height) * sc if sym.width > 0 else 0.001
        if width <= 0:
            width = 0.001
        pts = _arc_points(
            feature.xs, feature.ys, feature.xe, feature.ye,
            feature.xc, feature.yc, feature.clockwise, 64,
        )
        if len(pts) < 2:
            return None
        arc_line = LineString(pts)
        return arc_line.buffer(width / 2, cap_style="round", resolution=8)

    elif isinstance(feature, SurfaceRecord):
        return _surface_to_poly(feature)

    elif isinstance(feature, (TextRecord, BarcodeRecord)):
        # Text/barcode contribute negligible copper area; skip for ratio
        return None

    return None


# ===================================================================
# Public API
# ===================================================================

def calculate_copper_ratio(
    layer_name: str,
    profile: Profile,
    layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]],
    user_symbols: dict[str, UserSymbol],
    font: StrokeFont,
) -> Optional[float]:
    """Copper fill ratio for the entire layer (0 -- 1), vector method.

    Signature matches copper_utils.calculate_copper_ratio so callers
    can switch between raster and vector with minimal changes.
    """
    pcb_poly = _profile_to_poly(profile)
    if pcb_poly is None or pcb_poly.is_empty:
        return None
    if layer_name not in layers_data:
        return None

    features, _matrix_layer = layers_data[layer_name]
    copper = _build_copper_geometry(features, user_symbols or {})
    if copper is None or copper.is_empty:
        return 0.0

    copper_inside = copper.intersection(pcb_poly)
    if copper_inside.is_empty:
        return 0.0

    return copper_inside.area / pcb_poly.area


def calculate_subsection_ratios(
    layer_name: str,
    profile: Profile,
    layers_data: dict[str, tuple[LayerFeatures, MatrixLayer]],
    user_symbols: dict[str, UserSymbol],
    font: StrokeFont,
    n_rows: int = 5,
    n_cols: int = 5,
) -> Optional[np.ndarray]:
    """Copper fill ratio per grid cell, vector method.

    Returns np.ndarray of shape (n_rows, n_cols).
    Row 0 = top of PCB (ymax), column 0 = left (xmin).
    Cells with no PCB area are np.nan.

    Signature matches copper_utils.calculate_subsection_ratios.
    """
    pcb_poly = _profile_to_poly(profile)
    if pcb_poly is None or pcb_poly.is_empty:
        return None
    if layer_name not in layers_data:
        return None

    features, _matrix_layer = layers_data[layer_name]
    copper = _build_copper_geometry(features, user_symbols or {})

    # Bounding box of PCB
    xmin, ymin, xmax, ymax = pcb_poly.bounds
    bw = xmax - xmin
    bh = ymax - ymin

    ratios = np.full((n_rows, n_cols), np.nan)
    for i in range(n_rows):
        # Row 0 = top (ymax)
        cell_ymax = ymax - i * bh / n_rows
        cell_ymin = ymax - (i + 1) * bh / n_rows
        for j in range(n_cols):
            cell_xmin = xmin + j * bw / n_cols
            cell_xmax = xmin + (j + 1) * bw / n_cols

            cell_box = box(cell_xmin, cell_ymin, cell_xmax, cell_ymax)
            cell_pcb = pcb_poly.intersection(cell_box)

            if cell_pcb.is_empty or cell_pcb.area < 1e-12:
                continue

            if copper is None or copper.is_empty:
                ratios[i, j] = 0.0
                continue

            cell_copper = copper.intersection(cell_pcb)
            ratios[i, j] = cell_copper.area / cell_pcb.area

    return ratios
